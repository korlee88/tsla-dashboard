"""
주간 영상 자료 생성 스크립트
- 최근 7일 auto-sessions.json 데이터 기반
- Gemini API → 한국어 영상 대본(4 씬)
- Pillow → 씬별 1080×1920 카드 이미지 (YouTube Shorts 세로 포맷)
- 저장: data/weekly-report/YYYY-MM-DD/

종목 설정: config/ticker.json
"""

import os, json, sys, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT_DIR          = Path(__file__).parent.parent
TICKER_CONFIG     = json.loads((ROOT_DIR / "config" / "ticker.json").read_text(encoding="utf-8"))
TICKER            = TICKER_CONFIG["ticker"]
COMPANY_KO        = TICKER_CONFIG["company_ko"]
INDUSTRY_KO       = TICKER_CONFIG.get("industry_ko", "")
BRAND_LABEL       = TICKER_CONFIG["brand_label"]
REPO              = TICKER_CONFIG["repo"]

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
AUTO_SESSIONS     = ROOT_DIR / "data" / "auto-sessions.json"
OUTPUT_BASE       = ROOT_DIR / "data" / "weekly-report"
LOOKBACK_DAYS     = 7

# ── 팔레트 ────────────────────────────────────────────────────────────────
BG      = (14, 17, 23)
WHITE   = (255, 255, 255)
GRAY    = (107, 114, 128)
LGRAY   = (156, 163, 175)
GREEN   = (34, 197, 94)
RED     = (239, 68, 68)
AMBER   = (245, 158, 11)
PURPLE  = (167, 139, 250)
CYAN    = (6, 182, 212)
BLUE    = (59, 130, 246)
W, H    = 1080, 1920

PAD     = 40
COL_W   = W - PAD
SAFE_BOTTOM = 1680
KEY     = (255, 215, 0)
STROKE  = (0, 0, 0)

HEADER_H    = 500
PHOTO_Y     = HEADER_H
PHOTO_H     = 500
BODY_Y      = PHOTO_Y + PHOTO_H
START_Y     = BODY_Y
NAVY        = (15, 32, 70)
NAVY_DEEP   = (10, 22, 50)
CYAN_LIGHT  = (135, 220, 255)

SCENE_ACCENTS = [PURPLE, GREEN, RED, AMBER]

SCENE_WIKI_ARTICLES = TICKER_CONFIG["scene_wiki_articles"]

SCENE_BG_DIR = ROOT_DIR / "data" / "scene-backgrounds"
SCENE_STATIC_BG = [
    (SCENE_BG_DIR / name) if name else None
    for name in TICKER_CONFIG["scene_static_bg_files"]
]

# ── 데이터 로드 ───────────────────────────────────────────────────────────

def load_week_sessions():
    if not AUTO_SESSIONS.exists():
        return []
    with open(AUTO_SESSIONS, encoding="utf-8") as f:
        raw = json.load(f)
    sessions = raw if isinstance(raw, list) else raw.get("sessions", [])
    cutoff = (datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    return [s for s in sessions if s.get("date", "") >= cutoff]


def summarize(sessions):
    if not sessions:
        return None

    buy_indices = [s["buyIndex"] for s in sessions if s.get("buyIndex") is not None]
    prices      = [s["latestTslaPrice"] for s in sessions if s.get("latestTslaPrice")]

    bullish, bearish = [], []
    for s in sessions:
        news_map = {str(n["id"]): n for n in s.get("news", [])}
        for nid, a in (s.get("analyses") or {}).items():
            n     = news_map.get(str(nid), {})
            title = n.get("title", "")
            if not title:
                continue
            score = a.get("impact_score", 0) or 0
            dir_  = a.get("direction", "")
            reason = a.get("reasoning", "")
            if dir_ == "bullish" and score >= 2:
                bullish.append({"title": title, "score": score, "reason": reason})
            elif dir_ == "bearish" and score <= -2:
                bearish.append({"title": title, "score": score, "reason": reason})

    bullish.sort(key=lambda x: -x["score"])
    bearish.sort(key=lambda x:  x["score"])

    # 최근 5일 (date, price) 쌍 수집
    seen_dates = {}
    for s in sessions:
        date = s.get("date", "")
        price = s.get("latestTslaPrice")
        if date and price and date not in seen_dates:
            seen_dates[date] = price
    # 날짜 내림차순 정렬 후 최근 5일
    sorted_dates = sorted(seen_dates.keys(), reverse=True)[:5]
    daily_prices = [(d, seen_dates[d]) for d in sorted_dates]

    latest = sessions[0]
    return {
        "week_start":      sessions[-1].get("date", ""),
        "week_end":        sessions[0].get("date", ""),
        "session_count":   len(sessions),
        "buy_indices":     buy_indices,
        "avg_buy_index":   round(sum(buy_indices) / len(buy_indices)) if buy_indices else None,
        "latest_buy_index": buy_indices[0] if buy_indices else None,
        "price_start":     prices[-1] if prices else None,
        "price_end":       prices[0]  if prices else None,
        "latest_price":    latest.get("latestTslaPrice"),
        "top_bullish":     bullish[:3],
        "top_bearish":     bearish[:3],
        "forecasts":       latest.get("dailyForecasts", [])[:3],
        "daily_prices":    daily_prices,
    }

# ── 대본 생성 ─────────────────────────────────────────────────────────────

SCRIPT_PROMPT_TEMPLATE = """아래 {ticker} 주간 분석 데이터를 바탕으로 유튜브 쇼츠 스타일 나레이션 대본을 작성해줘.
전문 투자 용어 대신 일반인도 이해하기 쉬운 일상 언어로 작성해줘.

=== 주간 데이터 ({week_start} ~ {week_end}) ===
- 참고지수: 주간 평균 {avg_bi}, 최신 {latest_bi} (0~100점, 시장 관심도 참고 지표)
- {ticker} 주가: ${price}
{daily_prices_txt}
- 주요 호재:
{b_txt}
- 주요 악재:
{r_txt}

=== 씬 구성 (총 4씬) ===

【씬 1 — 주간 브리핑】
이번 주 가장 중요한 뉴스 1건을 상세히 소개. 정확히 4줄로 작성.
- 줄1: 헤드라인 — 감탄사로 시작, 20자 이내 (예: "와! 이번 주 {company_ko} 빅뉴스!")
- 줄2: 출처 — 언론사·날짜 (예: "Reuters · 05/12 보도")
- 줄3: 상세 내용 — 수치·배경·영향을 구체적으로, **80~120자, 3~4문장** (충분히 길게!)
- 줄4: 전망 — 40~60자, 투자자 관점에서 의미와 앞으로의 방향 설명

【씬 2 — 호재 뉴스】
긍정적 뉴스 TOP 2건. 각 줄 형식: "카테고리: 핵심내용 | 언론사·날짜·등급"
- 카테고리: 5자 이내
- 핵심내용: **반드시 최소 4문장, 최소 120자** — 무슨 일인지, 구체적 수치, 배경 이유, 주가 영향 순서로 자세히. 너무 짧으면 예시와 비교를 추가해 길이를 채울 것.
- 언론사: Reuters/Bloomberg/CNBC/WSJ/YahooFinance 등 실제 경제매체
- 날짜: MM/DD 형식 ({week_start}~{week_end} 내)
- 등급: 호재 / 참고 / 고려 중 하나

【씬 3 — 리스크 뉴스】
부정적/위험 뉴스 TOP 2건. 씬 2와 동일한 형식.
※ 확실하지 않은 루머도 포함 가능.
- 핵심내용: **반드시 최소 4문장, 최소 120자** — 리스크 원인, 구체적 규모, 투자자 반응, 향후 전망 순서로. 짧으면 유사 사례나 배경을 추가해 길이를 채울 것.
- 등급: 악재 / 주의 / 참고 중 하나

【씬 4 — 시장 반응】
유튜브 조회·검색량·커뮤니티 반응 기반 시황 내러티브. 정확히 4줄로 작성.
각 줄 형식: "[라벨] 내용" — **각 줄 반드시 최소 2문장, 최소 60자**로 구체적 묘사
- 줄1: [분위기] 이번 주 시장·투자자 전체 분위기 (감탄사 포함, 구체적 수치나 사례 포함)
- 줄2: [검색·영상] 구글 검색량/유튜브 조회수 트렌드 구체적 묘사
- 줄3: [투자자] 커뮤니티·SNS 투자자 반응 구체적 묘사 (긍정/부정 비율 등)
- 줄4: [시황] 종합 시황 — 긍정/중립/신중 관점 의견 포함 (투자 권유 아닌 개인 분석)

=== 공통 규칙 ===
• 유재석처럼 밝고 에너지 넘치는 MC 어투
• 전문 용어는 쉬운 말로 바꿔서 (예: "EPS" → "주당 순이익", "guidance" → "앞으로 예상")
• PPT 낭독 절대 금지! 생동감 있게!
• **내용은 길게, 자세하게** — 각 항목이 지정 최소 길이보다 짧으면 구체적 사례나 비교를 추가해 반드시 채울 것

=== 출력 형식 ===
SCENE_1_TITLE: [6자 이내]
SCENE_1:
[헤드라인]
[출처]
[상세 내용]
[전망]

SCENE_2_TITLE: [6자 이내]
SCENE_2:
카테고리1: 호재내용1 | 언론사·날짜·등급
카테고리2: 호재내용2 | 언론사·날짜·등급

SCENE_3_TITLE: [6자 이내]
SCENE_3:
카테고리1: 리스크1 | 언론사·날짜·등급
카테고리2: 리스크2 | 언론사·날짜·등급

SCENE_4_TITLE: [6자 이내]
SCENE_4:
[분위기] 내용
[검색·영상] 내용
[투자자] 내용
[시황] 내용

=== 배경 이미지 프롬프트 (Gemini Imagen용) ===
이번 주 뉴스 내용을 반영한 씬별 배경 이미지 프롬프트를 영어로 작성해줘.
규칙:
- 반드시 영어로 작성
- 각 프롬프트 60~80 단어
- 반드시 포함: "no text, no letters, no watermark, no logo"
- 반드시 포함: "9:16 vertical aspect ratio, ultra-high resolution"
- {company_ko}·{industry_ko} 관련 시각 요소 포함
- 씬 분위기에 맞는 색감 지정 (씬1 보라, 씬2 초록, 씬3 빨강, 씬4 주황)
- 이번 주 실제 뉴스 키워드를 시각화할 것

IMAGE_PROMPT_1: [씬1 — 이번 주 메인 뉴스 주제 시각화, 보라빛 미래적 분위기]
IMAGE_PROMPT_2: [씬2 — 호재 뉴스 주제 시각화, 밝고 활기찬 초록빛 분위기]
IMAGE_PROMPT_3: [씬3 — 리스크 뉴스 주제 시각화, 긴장감 있는 붉은빛 분위기]
IMAGE_PROMPT_4: [씬4 — 시장 반응 시각화, 도시·금융·군중 주황빛 분위기]"""


def _build_prompt(summary):
    b_txt = "\n".join(f"  [{n['score']:+d}] {n['title']}: {n['reason'][:70]}" for n in summary["top_bullish"]) or "  없음"
    r_txt = "\n".join(f"  [{n['score']:+d}] {n['title']}: {n['reason'][:70]}" for n in summary["top_bearish"]) or "  없음"

    daily_prices = summary.get("daily_prices", [])
    if daily_prices:
        dp_lines = "\n".join(f"  {d}: ${p:,.2f}" for d, p in daily_prices)
        daily_prices_txt = f"- 최근 주가 흐름:\n{dp_lines}"
    else:
        daily_prices_txt = ""

    return SCRIPT_PROMPT_TEMPLATE.format(
        ticker=TICKER,
        company_ko=COMPANY_KO,
        industry_ko=INDUSTRY_KO,
        week_start=summary["week_start"],
        week_end=summary["week_end"],
        avg_bi=summary["avg_buy_index"],
        latest_bi=summary["latest_buy_index"],
        price=summary["latest_price"],
        b_txt=b_txt, r_txt=r_txt,
        daily_prices_txt=daily_prices_txt,
    )


def generate_script_opus(prompt):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=3072,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def generate_script_gemini(prompt):
    from google import genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-1.5-flash",
        contents=prompt,
    )
    return response.text


def generate_script(summary):
    prompt = _build_prompt(summary)
    if ANTHROPIC_API_KEY:
        try:
            print("   🤖 Claude Opus 4로 대본 생성 중...")
            return generate_script_opus(prompt)
        except Exception as e:
            print(f"   ⚠ Opus 실패 ({e}) — Gemini로 전환", file=sys.stderr)
    if GEMINI_API_KEY:
        print("   🤖 Gemini Flash로 대본 생성 중...")
        return generate_script_gemini(prompt)
    raise RuntimeError("ANTHROPIC_API_KEY 또는 GEMINI_API_KEY 필요")


def parse_script(raw):
    scenes = []
    for i in range(1, 5):
        tk = f"SCENE_{i}_TITLE:"
        bk = f"SCENE_{i}:"
        title = ""
        body  = ""
        if tk in raw:
            s = raw.index(tk) + len(tk)
            e = raw.find("\n", s)
            title = raw[s:e].strip() if e != -1 else raw[s:].strip()
        if bk in raw:
            s   = raw.index(bk) + len(bk)
            nxt = raw.find(f"SCENE_{i+1}_TITLE:", s) if i < 4 else len(raw)
            body = raw[s:nxt].strip()
        lines = [l.strip() for l in body.split("\n")]
        scenes.append({"index": i, "title": title, "lines": lines, "body": body})
    return scenes


def parse_image_prompts(raw):
    """대본에서 씬별 Imagen 프롬프트 추출 → {1: "...", 2: "...", ...}"""
    prompts = {}
    for i in range(1, 5):
        key = f"IMAGE_PROMPT_{i}:"
        if key in raw:
            s = raw.index(key) + len(key)
            e = raw.find("\n", s)
            val = (raw[s:e] if e != -1 else raw[s:]).strip()
            # 대괄호 설명 텍스트 제거 (AI가 그대로 반환하는 경우)
            if val.startswith("[") and val.endswith("]"):
                val = ""
            if val:
                prompts[i] = val
    return prompts

# ── 이미지 생성 ───────────────────────────────────────────────────────────

def find_font():
    """시스템 한글 폰트 경로 탐색"""
    reg_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    bold_candidates = [
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf",
        "/usr/share/fonts/truetype/nanum/NanumBarunGothicBold.ttf",
    ]
    reg  = next((p for p in reg_candidates  if os.path.exists(p)), None)
    bold = next((p for p in bold_candidates if os.path.exists(p)), reg)
    return reg, bold


def wrap_text(draw, text, font, max_w):
    """Returns list of lines that fit within max_w."""
    lines = []
    for paragraph in text.split('\n'):
        words = paragraph.split(' ')
        current = ""
        for word in words:
            test = current + (" " if current else "") + word
            bb = draw.textbbox((0, 0), test, font=font)
            if bb[2] - bb[0] <= max_w:
                current = test
            else:
                if current:
                    lines.append(current)
                current = ""
                for char in word:
                    test2 = current + char
                    bb2 = draw.textbbox((0, 0), test2, font=font)
                    if bb2[2] - bb2[0] > max_w and current:
                        lines.append(current)
                        current = char
                    else:
                        current = test2
        if current:
            lines.append(current)
    return lines


def render_lines(draw, text, x, y, font, fill, max_px, line_gap=8):
    """여러 줄 텍스트 렌더링 → 다음 y 반환"""
    for raw_line in text.split("\n"):
        raw_line = raw_line.strip()
        if not raw_line:
            y += line_gap
            continue
        for line in wrap_text(draw, raw_line, font, max_px):
            draw.text((x, y), line, font=font, fill=fill)
            bbox = draw.textbbox((0, 0), line, font=font)
            y += (bbox[3] - bbox[1]) + line_gap
    return y


def fetch_wiki_image(article: str, out_path: Path) -> bool:
    """Wikipedia 기사 대표 이미지를 다운로드. 실패하거나 세로(로고) 이미지면 False 반환."""
    from PIL import Image as _PILImg
    import io as _io
    headers = {"User-Agent": f"{TICKER}-Dashboard/2.0 (github.com/{REPO})"}
    try:
        params = urllib.parse.urlencode({
            "action": "query", "titles": article,
            "prop": "pageimages", "pithumbsize": "1280",
            "format": "json",
        })
        req = urllib.request.Request(
            f"https://en.wikipedia.org/w/api.php?{params}", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        pages = data.get("query", {}).get("pages", {})
        for p in pages.values():
            img_url = p.get("thumbnail", {}).get("source", "")
            if img_url:
                req2 = urllib.request.Request(img_url, headers=headers)
                with urllib.request.urlopen(req2, timeout=15) as r2:
                    raw = r2.read()
                # 세로 비율(로고/아이콘) 이미지 거부 — 가로형만 허용
                try:
                    pimg = _PILImg.open(_io.BytesIO(raw))
                    pw, ph = pimg.size
                    if ph > pw * 1.2:   # 세로가 가로보다 20% 이상 크면 로고 가능성
                        print(f"   ⚠ 세로형 이미지 skip ({article}: {pw}×{ph})", file=sys.stderr)
                        return False
                except Exception:
                    pass
                out_path.write_bytes(raw)
                return True
    except Exception as e:
        print(f"   ⚠ 배경 이미지 다운로드 실패 ({article}): {e}", file=sys.stderr)
    return False


def fetch_wiki_image_with_fallback(articles, out_path: Path) -> bool:
    """후보 기사 목록 중 가로형 이미지를 찾을 때까지 순서대로 시도."""
    for article in (articles if isinstance(articles, list) else [articles]):
        if fetch_wiki_image(article, out_path):
            return True
    return False


def make_canvas(accent):
    """다크 배경 캔버스 생성 (1080×1920 세로 포맷)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 6], fill=accent)
    draw.rectangle([0, H - 100, W, H], fill=(8, 10, 16))
    return img, draw


def draw_photo_card(img, draw, accent, bg_path: Path | None, x, y, w, h):
    """Wikipedia 사진을 프레임에 삽입.
    비율이 안 맞으면 blurred-cover 배경 + contain-fit 전경으로 프레임 가득 채움.
    """
    from PIL import Image as PILImage, ImageFilter
    # 외곽 테두리
    draw.rounded_rectangle([x - 3, y - 3, x + w + 3, y + h + 3],
                           radius=8, outline=accent, width=2)
    if not bg_path or not bg_path.exists():
        draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=(20, 24, 32))
        return
    try:
        photo = PILImage.open(bg_path).convert("RGB")
        pw, ph = photo.size
        target_ratio = w / h
        img_ratio    = pw / ph

        # ── 배경 레이어: cover-crop + 블러 (비율 차이 영역을 가림) ──
        bg = photo.copy()
        if img_ratio > target_ratio:
            new_w = int(ph * target_ratio)
            left = (pw - new_w) // 2
            bg = bg.crop([left, 0, left + new_w, ph])
        else:
            new_h = int(pw / target_ratio)
            top = (ph - new_h) // 2
            bg = bg.crop([0, top, pw, top + new_h])
        bg = bg.resize((w, h), PILImage.LANCZOS)
        bg = bg.filter(ImageFilter.GaussianBlur(radius=24))
        # 배경에 어두운 오버레이
        bg_ov = PILImage.new("RGBA", (w, h), (8, 10, 16, 170))
        bg = PILImage.alpha_composite(bg.convert("RGBA"), bg_ov).convert("RGB")

        # ── 전경 레이어: contain-fit (프레임 안에 사진 전체 표시) ──
        if img_ratio > target_ratio:
            fg_w = w
            fg_h = int(w / img_ratio)
        else:
            fg_h = h
            fg_w = int(h * img_ratio)
        fg = photo.resize((fg_w, fg_h), PILImage.LANCZOS)
        # 전경에 약한 어두운 오버레이 (텍스트 가독성용)
        fg_ov = PILImage.new("RGBA", (fg_w, fg_h), (8, 10, 16, 80))
        fg = PILImage.alpha_composite(fg.convert("RGBA"), fg_ov).convert("RGB")

        # ── 합성: 배경 위에 전경을 중앙 정렬 ──
        bg.paste(fg, ((w - fg_w) // 2, (h - fg_h) // 2))
        img.paste(bg, (x, y))

        # 외곽 테두리 재그리기 (paste 이후)
        from PIL import ImageDraw as ID
        d2 = ID.Draw(img)
        d2.rounded_rectangle([x - 3, y - 3, x + w + 3, y + h + 3],
                             radius=8, outline=accent, width=2)
    except Exception:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=(20, 24, 32))


def draw_mbc_header(draw, brand: str, title_main: str, title_sub: str, accent,
                     fnt_brand, fnt_main, fnt_sub):
    """MBC NEWS 쇼츠 스타일 상단 헤더 — 네이비 박스 + 두줄 헤드라인.

    brand: 좌측 상단 채널 라벨 (예: 'TSLA WEEKLY')
    title_main: 메인 헤드라인 (흰색, 큰따옴표 권장)
    title_sub:  부제 (시안 강조)
    """
    # 네이비 그라데이션 배경
    for yy in range(HEADER_H):
        t = yy / HEADER_H
        r = int(NAVY[0] * (1 - t * 0.3) + NAVY_DEEP[0] * (t * 0.3))
        g = int(NAVY[1] * (1 - t * 0.3) + NAVY_DEEP[1] * (t * 0.3))
        b = int(NAVY[2] * (1 - t * 0.3) + NAVY_DEEP[2] * (t * 0.3))
        draw.line([(0, yy), (W, yy)], fill=(r, g, b))

    # 좌측 accent 스트라이프
    draw.rectangle([0, 0, 10, HEADER_H], fill=accent)

    # 브랜드 배지 (중앙 상단)
    brand_y = 70
    bw = max(220, len(brand) * 22)
    bx0 = (W - bw) // 2
    draw.rounded_rectangle([bx0, brand_y - 26, bx0 + bw, brand_y + 26],
                           radius=6, fill=(255, 255, 255, 0), outline=WHITE, width=0)
    draw.text((W // 2, brand_y), brand, font=fnt_brand, fill=WHITE, anchor="mm",
              stroke_width=1, stroke_fill=STROKE)
    # 브랜드 아래 짧은 가로선
    draw.line([(W // 2 - 60, brand_y + 32), (W // 2 + 60, brand_y + 32)],
              fill=WHITE, width=2)

    # 메인 헤드라인 (흰색)
    main_y = 220
    main_lines = wrap_text(draw, title_main, fnt_main, W - 80)
    for i, wl in enumerate(main_lines[:2]):
        bb = draw.textbbox((0, 0), wl, font=fnt_main)
        tw = bb[2] - bb[0]
        draw.text(((W - tw) // 2, main_y), wl, font=fnt_main, fill=WHITE,
                  stroke_width=3, stroke_fill=STROKE)
        main_y += (bb[3] - bb[1]) + 14

    # 부제 (시안)
    if title_sub:
        sub_y = main_y + 8
        sub_lines = wrap_text(draw, title_sub, fnt_sub, W - 80)
        for wl in sub_lines[:1]:
            bb = draw.textbbox((0, 0), wl, font=fnt_sub)
            tw = bb[2] - bb[0]
            draw.text(((W - tw) // 2, sub_y), wl, font=fnt_sub, fill=CYAN_LIGHT,
                      stroke_width=3, stroke_fill=STROKE)


def draw_buy_index_gauge(draw, cx, cy, r, bi, fnt_big, fnt_small):
    col = GREEN if bi >= 65 else AMBER if bi >= 45 else RED
    # 배경 반원 (회색)
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill=(40, 44, 54), width=22)
    # 값 반원 (컬러)
    end_a = 180 + int(bi / 100 * 180)
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=180, end=end_a, fill=col, width=22)
    # 중앙 숫자
    draw.text((cx, cy - 18), str(bi), font=fnt_big, fill=col, anchor="mm")
    draw.text((cx, cy + 22), "참고지수", font=fnt_small, fill=GRAY, anchor="mm")
    # 범례
    draw.text((cx - r + 8, cy + 14), "0", font=fnt_small, fill=GRAY)
    draw.text((cx + r - 22, cy + 14), "100", font=fnt_small, fill=GRAY)


def draw_news_card_portrait(draw, img, x, y, w, h, chapter, content, source, accent,
                             fnt_bold, fnt_content, fnt_source,
                             fnt_content_xl=None, fnt_content_sm=None):
    """세로 포맷 전용 뉴스카드 (헤더 + 내용 수직중앙 + 하단 출처)."""
    from PIL import ImageDraw

    HEADER_H = 90
    FOOTER_H = 60

    grade_map = {
        "호재": GREEN, "악재": RED, "주의": AMBER,
        "참고": CYAN, "고려": BLUE,
    }
    badge_col = GRAY
    badge_text = ""
    for grade, col in grade_map.items():
        if grade in source:
            badge_col = col
            badge_text = grade
            break

    # 카드 배경
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14,
                            fill=(16, 19, 27), outline=accent, width=2)

    # 헤더 배경
    draw.rounded_rectangle([x, y, x + w, y + HEADER_H], radius=14, fill=accent)
    draw.rectangle([x, y + HEADER_H - 14, x + w, y + HEADER_H], fill=accent)

    # 챕터 이름 (헤더 왼쪽)
    draw.text((x + 22, y + HEADER_H // 2), chapter[:5],
              font=fnt_bold, fill=(10, 12, 20), anchor="lm")

    # 등급 배지 (헤더 오른쪽)
    if badge_text:
        badge_w = 110
        badge_h = 52
        badge_x = x + w - badge_w - 16
        badge_y = y + (HEADER_H - badge_h) // 2
        draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                               radius=10, fill=(10, 12, 20))
        draw.text((badge_x + badge_w // 2, badge_y + badge_h // 2),
                  badge_text, font=fnt_bold, fill=badge_col, anchor="mm")

    # ── 적응형 폰트: 콘텐츠 길이에 따라 자동 선택 ──────────────────────────
    char_count = len(content)
    if fnt_content_xl and char_count < 60:
        adaptive_font = fnt_content_xl   # 48px — 짧은 콘텐츠는 크게
    elif fnt_content_sm and char_count >= 120:
        adaptive_font = fnt_content_sm   # 28px — 긴 콘텐츠는 작게
    else:
        adaptive_font = fnt_content      # 36px — 기본

    # 내용 영역
    content_x = x + 22
    content_y = y + HEADER_H + 16
    content_max_w = w - 44
    content_area_h = h - HEADER_H - FOOTER_H - 32

    content_lines = wrap_text(draw, content, adaptive_font, content_max_w)
    bb_test = draw.textbbox((0, 0), "가", font=adaptive_font)
    char_h = bb_test[3] - bb_test[1]
    line_h = char_h + 14
    max_lines = max(1, content_area_h // line_h)

    # 수직 중앙 정렬
    display_lines = content_lines[:max_lines]
    total_text_h = len(display_lines) * line_h
    cy = content_y + max(0, (content_area_h - total_text_h) // 2)

    for line in display_lines:
        if cy + char_h > y + h - FOOTER_H - 8:
            break
        draw.text((content_x, cy), line, font=adaptive_font, fill=WHITE,
                  stroke_width=1, stroke_fill=STROKE)
        cy += line_h

    # 하단 출처 바
    footer_y = y + h - FOOTER_H
    draw.rounded_rectangle([x, footer_y - 6, x + w, y + h], radius=14, fill=(10, 12, 18))

    # 출처 텍스트 — KEY 노랑으로 강조
    src_display = source
    for grade in grade_map:
        src_display = src_display.replace("·" + grade, "").replace(grade + "·", "").replace(grade, "").strip("· ")
    draw.text((x + 18, footer_y + FOOTER_H // 2), src_display[:50],
              font=fnt_source, fill=KEY, anchor="lm",
              stroke_width=1, stroke_fill=STROKE)


def draw_bi_legend(draw, avg_bi, fnt_label, fnt_val):
    """하단 안전 영역에 매수지수 범례 + 현재 점수 표시 (y=1700~1870)."""
    LX  = PAD
    LY  = SAFE_BOTTOM + 20           # 1700
    LW  = W - PAD * 2                # 1000
    LH  = H - LY - 50                # ~170px

    # 배경 패널
    draw.rounded_rectangle([LX, LY, LX + LW, LY + LH],
                           radius=14, fill=(14, 18, 28), outline=(40, 45, 60), width=1)

    # 현재 매수지수 (왼쪽 강조)
    bi_col = GREEN if avg_bi >= 65 else AMBER if avg_bi >= 45 else RED
    bi_str = str(avg_bi) if avg_bi is not None else "?"
    draw.text((LX + 24, LY + LH // 2), f"{bi_str}점",
              font=fnt_val, fill=bi_col, anchor="lm",
              stroke_width=2, stroke_fill=STROKE)

    signal = "긍정" if avg_bi is not None and avg_bi >= 65 else \
             "중립" if avg_bi is not None and avg_bi >= 45 else "신중"
    draw.text((LX + 24, LY + LH // 2 + 38), signal,
              font=fnt_label, fill=bi_col, anchor="lm",
              stroke_width=1, stroke_fill=STROKE)

    # 구분선
    SEP_X = LX + 140
    draw.line([(SEP_X, LY + 16), (SEP_X, LY + LH - 16)], fill=(40, 45, 60), width=1)

    # 오른쪽: 3단계 범례
    ITEMS = [
        (GREEN, "65점↑", "긍정"),
        (AMBER, "45-64점", "중립"),
        (RED,   "44점↓", "신중"),
    ]
    slot_w = (LX + LW - SEP_X - 16) // 3
    for j, (col, range_lbl, sig_lbl) in enumerate(ITEMS):
        ix = SEP_X + 8 + j * slot_w
        iy = LY + LH // 2 - 28

        # 색상 원
        draw.ellipse([ix, iy, ix + 20, iy + 20], fill=col)
        draw.text((ix + 28, iy), range_lbl,
                  font=fnt_label, fill=LGRAY)
        draw.text((ix + 28, iy + 24), sig_lbl,
                  font=fnt_label, fill=col)

    # 면책 문구 (우측 하단)
    disclaimer = "※ 개인 분석 참고용 · 투자 판단은 본인 책임"
    db = draw.textbbox((0, 0), disclaimer, font=fnt_label)
    dw = db[2] - db[0]
    draw.text((LX + LW - dw - 10, LY + LH - 26),
              disclaimer, font=fnt_label, fill=(70, 78, 95))


def draw_stat_box(draw, x, y, w, h, label, value, col, fnt_val, fnt_lbl):
    draw.rectangle([x, y, x + w, y + h], fill=(18, 21, 30), outline=(40, 44, 54), width=1)
    draw.text((x + w // 2, y + 18), label, font=fnt_lbl, fill=GRAY, anchor="mt")
    draw.text((x + w // 2, y + h - 22), value, font=fnt_val, fill=col, anchor="mb")


def parse_news_line(line):
    """'카테고리: 내용 | 소스' 형식 분리. → (chapter, content, source)"""
    source = ""
    if "|" in line:
        main, source = line.split("|", 1)
        source = source.strip()
    else:
        main = line
    if ": " in main:
        ch, ct = main.split(": ", 1)
        return ch.strip()[:6], ct.strip(), source
    return "뉴스", main.strip(), source


def build_scene_image(scene, summary, font_reg, font_bold, bg_path: Path | None = None):
    from PIL import ImageFont, ImageDraw
    idx    = scene["index"]
    title  = scene["title"] or f"씬 {idx}"
    lines  = scene.get("lines") or [l.strip() for l in (scene.get("body") or "").split("\n") if l.strip()]
    accent = SCENE_ACCENTS[idx - 1]

    img, draw = make_canvas(accent)

    def fnt(path, size):
        try:
            return ImageFont.truetype(path, size) if path else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()

    # ── 폰트 ──
    f_xl    = fnt(font_bold, 72)
    f_lg    = fnt(font_bold, 40)
    f_md    = fnt(font_bold, 32)
    f_nm    = fnt(font_reg,  30)
    f_sm    = fnt(font_reg,  22)
    f_xs    = fnt(font_reg,  18)
    f_src   = fnt(font_reg,  20)
    f_ch    = fnt(font_bold, 34)
    f_ct    = fnt(font_reg,  34)
    f_ct_xl = fnt(font_reg,  44)
    f_ct_sm = fnt(font_reg,  28)
    # MBC 스타일 헤더 폰트
    f_brand = fnt(font_bold, 32)
    f_head_main = fnt(font_bold, 80)
    f_head_sub  = fnt(font_bold, 64)

    news_lines = [l for l in lines if l.strip() and not l.startswith("SCENE")]

    # ── 씬별 헤드라인 텍스트 결정 (MBC 스타일) ──────────────────────────
    if idx == 1:
        # 메인: 대본 첫 줄 그대로 (감탄사 포함). 큰따옴표 추가.
        first = (news_lines[0] if news_lines else f"이번 주 {COMPANY_KO}").strip()
        # 큰따옴표 적용
        if not (first.startswith('"') or first.startswith("'")):
            first = f'"{first}"'
        head_main = first
        # 부제: 매수지수 + 주가
        bi = summary.get("avg_buy_index") or 50
        price = summary.get("latest_price")
        try:
            head_sub = f"참고지수 {bi}점 · ${float(price):,.0f}" if price else f"참고지수 {bi}점"
        except Exception:
            head_sub = f"참고지수 {bi}점"
    elif idx == 2:
        head_main = '"이번 주 빅 호재"'
        chs = []
        for ln in news_lines[:2]:
            ch, _, _ = parse_news_line(ln)
            chs.append(ch)
        head_sub = " · ".join(chs) if chs else "주요 호재 정리"
    elif idx == 3:
        head_main = '"이번 주 리스크"'
        chs = []
        for ln in news_lines[:2]:
            ch, _, _ = parse_news_line(ln)
            chs.append(ch)
        head_sub = " · ".join(chs) if chs else "주요 리스크 정리"
    else:
        bi = summary.get("avg_buy_index") or 50
        head_main = '"이번 주 시장 반응"'
        head_sub = f"참고지수 {bi}점"

    # ── 상단 헤더 (Y=0~500) — 네이비 박스 + 브랜드 + 두줄 헤드라인 ──────
    draw_mbc_header(draw, BRAND_LABEL, head_main, head_sub, accent,
                    f_brand, f_head_main, f_head_sub)

    # ── 사진 배너 (Y=500~1000, 500px) ────────────────────────────────────
    draw_photo_card(img, draw, accent, bg_path, x=0, y=PHOTO_Y, w=W, h=PHOTO_H)
    draw = ImageDraw.Draw(img)

    # 푸터 텍스트는 자막+UI에 가려지므로 제거

    # ── 씬 1: 주간 브리핑 — 본문 영역 Y=1040~1680 (640px) ────────────────
    CONTENT_Y = START_Y + 40   # 사진 하단과 본문 사이 40px 여백
    if idx == 1:
        BODY_H = SAFE_BOTTOM - CONTENT_Y   # 640
        FC_W = COL_W - PAD

        # 본문: 한 단락 카드 + 가격 스트립
        # 상단 단락 카드 (출처/내용/전망) 약 420px
        FC_H = 420
        draw.rounded_rectangle([PAD, CONTENT_Y, PAD + FC_W, CONTENT_Y + FC_H],
                               radius=14, fill=(20, 24, 34), outline=accent, width=2)
        body_y = CONTENT_Y + 24
        INNER_W = FC_W - 40

        # 출처 라인
        if len(news_lines) >= 2:
            draw.text((PAD + 20, body_y), "출처",
                      font=f_src, fill=GRAY)
            draw.text((PAD + 100, body_y - 2), news_lines[1][:60],
                      font=f_sm, fill=KEY,
                      stroke_width=1, stroke_fill=STROKE)
            body_y += 38
            draw.rectangle([PAD + 20, body_y, PAD + 20 + INNER_W, body_y + 1],
                           fill=accent)
            body_y += 14

        # 내용
        if len(news_lines) >= 3:
            draw.text((PAD + 20, body_y), "내용",
                      font=f_src, fill=GRAY)
            body_y += 32
            content_wrapped = wrap_text(draw, news_lines[2], f_nm, INNER_W)
            for wl in content_wrapped[:5]:
                draw.text((PAD + 20, body_y), wl, font=f_nm, fill=WHITE,
                          stroke_width=1, stroke_fill=STROKE)
                bb = draw.textbbox((0, 0), wl, font=f_nm)
                body_y += (bb[3] - bb[1]) + 8
            body_y += 8

        # 전망 (강조)
        if len(news_lines) >= 4:
            outlook_y = CONTENT_Y + FC_H - 80
            draw.rectangle([PAD + 20, outlook_y - 12, PAD + 20 + INNER_W, outlook_y - 11],
                           fill=(accent[0]//2, accent[1]//2, accent[2]//2))
            draw.text((PAD + 20, outlook_y - 2), "전망 ▶",
                      font=f_src, fill=KEY,
                      stroke_width=1, stroke_fill=STROKE)
            outlook_wrapped = wrap_text(draw, news_lines[3], f_md, INNER_W - 110)
            if outlook_wrapped:
                draw.text((PAD + 130, outlook_y - 4), outlook_wrapped[0][:36],
                          font=f_md, fill=KEY,
                          stroke_width=2, stroke_fill=STROKE)

        # 가격 스트립 — 카드 아래
        STRIP_Y = CONTENT_Y + FC_H + 16
        BOX_Y = STRIP_Y + 36
        BOX_H = SAFE_BOTTOM - BOX_Y - 10
        draw.text((PAD, STRIP_Y + 16), "주간 주가 흐름 ($)",
                  font=f_sm, fill=LGRAY, anchor="lm",
                  stroke_width=1, stroke_fill=STROKE)

        daily_prices = summary.get("daily_prices", [])
        if daily_prices:
            n = min(len(daily_prices), 5)
            box_gap = 14
            box_w = (COL_W - PAD - box_gap * (n - 1)) // n
            for j, (date_str, price_val) in enumerate(daily_prices[:n]):
                bx = PAD + j * (box_w + box_gap)
                try:
                    parts = date_str.split("-")
                    lbl = f"{parts[1]}/{parts[2]}"
                except Exception:
                    lbl = date_str[-5:]
                draw.rounded_rectangle([bx, BOX_Y, bx + box_w, BOX_Y + BOX_H],
                                       radius=10, fill=(18, 21, 30), outline=accent, width=2)
                draw.text((bx + box_w // 2, BOX_Y + 26), lbl,
                          font=f_sm, fill=LGRAY, anchor="mm")
                try:
                    price_str = f"${float(price_val):,.0f}"
                except Exception:
                    price_str = str(price_val)
                draw.text((bx + box_w // 2, BOX_Y + BOX_H // 2 + 10), price_str,
                          font=f_md, fill=KEY, anchor="mm",
                          stroke_width=2, stroke_fill=STROKE)
        else:
            price = summary.get("latest_price")
            price_str = f"${float(price):,.2f}" if price else "N/A"
            draw.rounded_rectangle([PAD, BOX_Y, PAD + COL_W - PAD, BOX_Y + BOX_H],
                                   radius=10, fill=(18, 21, 30), outline=accent, width=2)
            draw.text((PAD + (COL_W - PAD) // 2, BOX_Y + 30), "현재가",
                      font=f_sm, fill=LGRAY, anchor="mm")
            draw.text((PAD + (COL_W - PAD) // 2, BOX_Y + BOX_H // 2 + 20), price_str,
                      font=f_lg, fill=KEY, anchor="mm",
                      stroke_width=2, stroke_fill=STROKE)

    # ── 씬 2~3: 호재/리스크 — 세로형 대형 카드 2장 (SAFE_BOTTOM 안에) ──
    elif idx in (2, 3):
        GAP    = 20
        CARD_H = (SAFE_BOTTOM - CONTENT_Y - GAP) // 2
        CARD_W = COL_W - PAD   # 1000
        card_positions = [CONTENT_Y, CONTENT_Y + CARD_H + GAP]

        for i, line in enumerate(news_lines[:2]):
            chapter, content, source = parse_news_line(line)
            cy = card_positions[i]
            draw_news_card_portrait(
                draw, img,
                x=PAD, y=cy, w=CARD_W, h=CARD_H,
                chapter=chapter, content=content, source=source,
                accent=accent,
                fnt_bold=f_ch, fnt_content=f_ct, fnt_source=f_src,
                fnt_content_xl=f_ct_xl, fnt_content_sm=f_ct_sm,
            )
            draw = ImageDraw.Draw(img)

    # ── 씬 4: 시장 반응 — 카드형 4개 항목 (SAFE_BOTTOM 안에) ────────────
    else:
        GAP    = 18
        ITEM_H = (SAFE_BOTTOM - CONTENT_Y - GAP * 3) // 4
        item_positions = [CONTENT_Y + i * (ITEM_H + GAP) for i in range(4)]
        labels = ["분위기", "검색·영상", "투자자", "시황"]

        for i, line in enumerate(news_lines[:4]):
            iy = item_positions[i]
            # 카드 배경
            draw.rounded_rectangle([PAD, iy, PAD + COL_W - PAD, iy + ITEM_H],
                                   radius=10, fill=(16, 19, 27), outline=accent, width=1)
            # 왼쪽 라벨 컬럼 (accent 배경, 전체 높이)
            LAB_W = 140
            draw.rounded_rectangle([PAD, iy, PAD + LAB_W, iy + ITEM_H],
                                   radius=10, fill=accent)
            draw.rectangle([PAD + LAB_W - 10, iy, PAD + LAB_W, iy + ITEM_H], fill=accent)
            draw.text((PAD + LAB_W // 2, iy + ITEM_H // 2),
                      labels[i] if i < len(labels) else "",
                      font=f_ch, fill=(10, 12, 20), anchor="mm")

            # 라벨 접두사 제거 (예: "[분위기] ")
            content_text = line
            if line.startswith("[") and "]" in line:
                bracket_end = line.index("]") + 1
                content_text = line[bracket_end:].strip()

            # 내용 텍스트 (수직 중앙 정렬, 흰색 + stroke)
            content_x   = PAD + LAB_W + 18
            content_maxw = COL_W - PAD - LAB_W - 36
            wrapped = wrap_text(draw, content_text, f_nm, content_maxw)
            bb_h = draw.textbbox((0, 0), "가", font=f_nm)
            lh = (bb_h[3] - bb_h[1]) + 14
            total_h = len(wrapped[:5]) * lh
            start_y = iy + (ITEM_H - total_h) // 2
            for wl in wrapped[:5]:
                if start_y + lh > iy + ITEM_H - 10:
                    break
                draw.text((content_x, start_y), wl, font=f_nm, fill=WHITE,
                          stroke_width=1, stroke_fill=STROKE)
                start_y += lh

    # ── 하단 매수지수 범례 (모든 씬 공통) ─────────────────────────────────────
    draw = ImageDraw.Draw(img)
    avg_bi = summary.get("avg_buy_index") if summary else None
    draw_bi_legend(draw, avg_bi, f_sm, f_md)

    return img


def build_images(scenes, summary, out_dir):
    try:
        from PIL import ImageFont
    except ImportError:
        print("   ⚠ Pillow 없음 — 이미지 건너뜀", file=sys.stderr)
        return

    font_reg, font_bold = find_font()
    if not font_reg:
        print("   ⚠ 한글 폰트 없음 — 이미지 건너뜀", file=sys.stderr)
        return

    # 배경 이미지 준비 (고정 파일 우선, 없으면 Wikipedia 다운로드)
    print("   🖼 배경 이미지 준비 중...")
    bg_paths = {}
    for scene in scenes:
        idx        = scene["index"]
        static_bg  = SCENE_STATIC_BG[idx - 1]
        articles   = SCENE_WIKI_ARTICLES[idx - 1]
        bg_path    = out_dir / f"bg_{idx:02d}.jpg"

        if static_bg and static_bg.exists():
            import shutil as _shutil
            _shutil.copy2(static_bg, bg_path)
            bg_paths[idx] = bg_path
            print(f"      씬{idx} [고정 이미지] ✅")
        else:
            ok = fetch_wiki_image_with_fallback(articles, bg_path)
            bg_paths[idx] = bg_path if ok else None
            status = "✅" if ok else "⚠ 실패(기본 배경 사용)"
            label  = (articles[0] if isinstance(articles, list) else articles)[:20]
            print(f"      씬{idx} [Wikipedia: {label}] {status}")

    for scene in scenes:
        idx  = scene["index"]
        img  = build_scene_image(scene, summary, font_reg, font_bold, bg_paths.get(idx))
        path = out_dir / f"scene_{idx:02d}.png"
        img.save(path, "PNG")
        print(f"   ✅ scene_{idx:02d}.png 저장")

# ── 메인 ──────────────────────────────────────────────────────────────────

def main():
    today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = OUTPUT_BASE / today
    out_dir.mkdir(parents=True, exist_ok=True)

    print("📊 주간 세션 로드...")
    sessions = load_week_sessions()
    if not sessions:
        print("⚠ 최근 7일 세션 없음 — 종료", file=sys.stderr)
        sys.exit(0)

    summary = summarize(sessions)
    print(f"   {summary['week_start']} ~ {summary['week_end']} / {summary['session_count']}개 세션")
    print(f"   평균 매수지수: {summary['avg_buy_index']} / 현재가: ${summary['latest_price']}")

    # ── 대본 ──
    if not ANTHROPIC_API_KEY and not GEMINI_API_KEY:
        print("⚠ API 키 없음 — 대본 생성 건너뜀", file=sys.stderr)
        scenes = [{"index": i, "title": f"씬 {i}", "lines": [], "body": ""} for i in range(1, 5)]
    else:
        print("✍ 대본 생성 중...")
        raw    = generate_script(summary)
        scenes = parse_script(raw)
        img_prompts = parse_image_prompts(raw)

        with open(out_dir / "script.txt", "w", encoding="utf-8") as f:
            f.write(raw)
        with open(out_dir / "script.json", "w", encoding="utf-8") as f:
            json.dump({"generated_at": today, "summary": summary, "scenes": scenes,
                       "image_prompts": img_prompts},
                      f, ensure_ascii=False, indent=2)

        # ── 이미지 프롬프트 별도 저장 (Imagen 복붙용) ──
        if img_prompts:
            lines = [f"# {TICKER} 주간 배경 이미지 프롬프트 — {today}",
                     "# Gemini Imagen에 씬별로 붙여넣기 하세요.\n"]
            scene_names = {1: "씬1 주간브리핑", 2: "씬2 호재뉴스",
                           3: "씬3 리스크뉴스", 4: "씬4 시장반응"}
            for i in range(1, 5):
                if i in img_prompts:
                    lines.append(f"## {scene_names[i]}")
                    lines.append(img_prompts[i])
                    lines.append("")
            with open(out_dir / "image_prompts.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            print(f"   🎨 image_prompts.txt 저장 완료 ({len(img_prompts)}개 씬)")
        print(f"   ✅ 대본 저장 완료")

    # ── 이미지 ──
    print("🖼 카드 이미지 생성 중...")
    build_images(scenes, summary, out_dir)

    # ── 메타 ──
    with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated_at":    today,
            "week_start":      summary["week_start"],
            "week_end":        summary["week_end"],
            "avg_buy_index":   summary["avg_buy_index"],
            "latest_price":    summary["latest_price"],
            "session_count":   summary["session_count"],
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 완료: data/weekly-report/{today}/")
    print(f"   📄 script.txt  — 영상 대본 (자막용)")
    print(f"   🖼 scene_01~04.png — 씬별 배경 카드 이미지 (1080×1920, YouTube Shorts 세로 포맷)")
    print(f"   CapCut / Premiere 등에서 이미지+자막 조합 후 영상 제작 가능합니다.")


if __name__ == "__main__":
    main()
