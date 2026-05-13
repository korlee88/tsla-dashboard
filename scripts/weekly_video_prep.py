"""
TSLA 주간 영상 자료 생성 스크립트
- 최근 7일 auto-sessions.json 데이터 기반
- Gemini API → 한국어 영상 대본(4 씬)
- Pillow → 씬별 1080×1920 카드 이미지 (YouTube Shorts 세로 포맷)
- 저장: data/weekly-report/YYYY-MM-DD/
"""

import os, json, sys, textwrap, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
AUTO_SESSIONS     = Path(__file__).parent.parent / "data" / "auto-sessions.json"
OUTPUT_BASE       = Path(__file__).parent.parent / "data" / "weekly-report"
LOOKBACK_DAYS     = 7

# ── 팔레트 ────────────────────────────────────────────────────────────────
BG      = (14, 17, 23)
CARD    = (28, 31, 38)
BORDER  = (42, 45, 53)
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
COL_W   = W - PAD          # 1040
START_Y = 400               # 콘텐츠 시작 Y (사진 배너 아래)

SCENE_ACCENTS = [PURPLE, GREEN, RED, AMBER]
SCENE_MOODS   = ["excited", "happy", "worried", "focused"]

# 씬별 Wikipedia 배경 이미지 소스
SCENE_WIKI_ARTICLES = [
    "Tesla, Inc.",              # scene 1 - 브리핑
    "Tesla Cybertruck",         # scene 2 - 호재 뉴스
    "Elon Musk",                # scene 3 - 리스크 뉴스
    "Gigafactory Nevada",       # scene 4 - 시장 동향
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

SCRIPT_PROMPT_TEMPLATE = """아래 TSLA 주간 분석 데이터를 바탕으로 유튜브 쇼츠 스타일 나레이션 대본을 작성해줘.
전문 투자 용어 대신 일반인도 이해하기 쉬운 일상 언어로 작성해줘.

=== 주간 데이터 ({week_start} ~ {week_end}) ===
- 매수지수: 주간 평균 {avg_bi}, 최신 {latest_bi} (0~100점, 65 이상=매수 신호)
- TSLA 주가: ${price}
{daily_prices_txt}
- 주요 호재:
{b_txt}
- 주요 악재:
{r_txt}

=== 씬 구성 (총 4씬) ===

【씬 1 — 주간 브리핑】
이번 주 가장 중요한 뉴스 1건을 상세히 소개. 정확히 4줄로 작성.
- 줄1: 헤드라인 — 감탄사로 시작, 20자 이내 (예: "와! 이번 주 테슬라 빅뉴스!")
- 줄2: 출처 — 언론사·날짜 (예: "Reuters · 05/12 보도")
- 줄3: 상세 내용 — 수치·배경 포함, 40자 이내
- 줄4: 전망 — 20자 이내 (예: "단기 상승 기대됩니다!")

【씬 2 — 호재 뉴스】
긍정적 뉴스 TOP 2건. 각 줄 형식: "카테고리: 핵심내용 | 언론사·날짜·등급"
- 카테고리: 5자 이내
- 핵심내용: 40~60자, 수치·배경 포함, 2~3문장
- 언론사: Reuters/Bloomberg/CNBC/WSJ/YahooFinance 등 실제 경제매체
- 날짜: MM/DD 형식 ({week_start}~{week_end} 내)
- 등급: 호재 / 참고 / 고려 중 하나

【씬 3 — 리스크 뉴스】
부정적/위험 뉴스 TOP 2건. 씬 2와 동일한 형식.
※ 확실하지 않은 루머도 포함 가능.
- 등급: 악재 / 주의 / 참고 중 하나

【씬 4 — 시장 반응】
유튜브 조회·검색량·커뮤니티 반응 기반 시황 내러티브. 정확히 4줄로 작성.
각 줄 형식: "[라벨] 내용 40~60자, 2~3문장으로 사람들 반응·트렌드 묘사"
- 줄1: [분위기] 시장 전체 분위기 묘사 (감탄사 포함)
- 줄2: [검색·영상] 검색량/유튜브 트렌드 묘사
- 줄3: [투자자] 커뮤니티/투자자 반응 묘사
- 줄4: [시황] 종합 시황 한 줄 묘사

=== 공통 규칙 ===
• 유재석처럼 밝고 에너지 넘치는 MC 어투
• 일반인도 쉽게 이해하는 친근한 표현 사용
• PPT 낭독 절대 금지!
• 씬당 나레이션 10~12초 분량

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
[시황] 내용"""


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
        max_tokens=2048,
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


def draw_robot(img, rx: int, ry: int, mood: str = "neutral", accent: tuple = (167, 139, 250)):
    """씬 위에 귀여운 로봇 마스코트 합성."""
    from PIL import Image, ImageDraw

    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d     = ImageDraw.Draw(layer)
    BODY  = (38, 44, 60)
    METAL = (78, 88, 112)
    SHINE = (215, 225, 240)

    # ── 안테나 ──────────────────────────────────────
    ax = rx + 50
    d.line([ax, ry - 26, ax, ry], fill=METAL, width=3)
    d.ellipse([ax - 8, ry - 36, ax + 8, ry - 20], fill=accent, outline=SHINE, width=1)

    # ── 머리 ──────────────────────────────────────
    d.rounded_rectangle([rx, ry, rx + 100, ry + 86], radius=18,
                        fill=BODY, outline=METAL, width=2)

    # ── 눈 (mood별 표정) ──────────────────────────
    ey = ry + 22
    lx, rx2 = rx + 13, rx + 57
    ew, eh  = 28, 22

    if mood == "happy":
        d.arc([lx, ey, lx+ew, ey+eh], start=200, end=340, fill=accent, width=4)
        d.arc([rx2, ey, rx2+ew, ey+eh], start=200, end=340, fill=accent, width=4)
    elif mood == "excited":
        d.ellipse([lx, ey-2, lx+ew, ey+ew-2], fill=accent)
        d.ellipse([rx2, ey-2, rx2+ew, ey+ew-2], fill=accent)
        d.ellipse([lx+4, ey+2, lx+9, ey+7], fill=SHINE)
        d.ellipse([rx2+4, ey+2, rx2+9, ey+7], fill=SHINE)
    elif mood == "worried":
        d.line([lx, ey+10, lx+ew, ey+4], fill=(239, 68, 68), width=5)
        d.line([rx2, ey+4, rx2+ew, ey+10], fill=(239, 68, 68), width=5)
    elif mood == "focused":
        d.rectangle([lx, ey+7, lx+ew, ey+15], fill=accent)
        d.rectangle([rx2, ey+7, rx2+ew, ey+15], fill=accent)
    else:
        d.rectangle([lx, ey, lx+ew, ey+eh], fill=accent)
        d.rectangle([rx2, ey, rx2+ew, ey+eh], fill=accent)
        d.ellipse([lx+4, ey+3, lx+9, ey+9], fill=SHINE)
        d.ellipse([rx2+4, ey+3, rx2+9, ey+9], fill=SHINE)

    # ── 입 ────────────────────────────────────────
    my = ry + 60
    if mood in ("happy", "excited"):
        d.arc([rx+26, my - 8, rx+74, my + 14], start=0, end=180, fill=accent, width=3)
    elif mood == "worried":
        d.arc([rx+26, my, rx+74, my + 18], start=180, end=360, fill=(239, 68, 68), width=3)
    else:
        d.line([rx+30, my + 6, rx+70, my + 6], fill=METAL, width=3)

    # ── 몸통 ──────────────────────────────────────
    bx, by = rx + 12, ry + 94
    d.rounded_rectangle([bx, by, bx+76, by+66], radius=10, fill=BODY, outline=METAL, width=2)

    # 가슴 엠블럼 (T자 마크)
    d.rounded_rectangle([bx+18, by+10, bx+58, by+44], radius=6, fill=accent)
    tx = bx + 28
    d.line([tx, by+16, tx+20, by+16], fill=(255,255,255), width=3)
    d.line([tx+10, by+16, tx+10, by+40], fill=(255,255,255), width=3)

    # 가슴 LED (오른쪽 하단)
    led_col = GREEN if mood in ("happy","excited") else RED if mood=="worried" else AMBER
    d.ellipse([bx+56, by+46, bx+66, by+56], fill=led_col)

    # ── 팔 ────────────────────────────────────────
    d.rounded_rectangle([bx-20, by+8, bx-5, by+48], radius=6, fill=METAL)
    d.rounded_rectangle([bx+81, by+8, bx+96, by+48], radius=6, fill=METAL)

    # 손 (동그라미)
    d.ellipse([bx-24, by+42, bx-6, by+60], fill=METAL)
    d.ellipse([bx+82, by+42, bx+100, by+60], fill=METAL)

    # ── 다리 ──────────────────────────────────────
    d.rounded_rectangle([bx+8,  by+70, bx+30, by+88], radius=6, fill=METAL)
    d.rounded_rectangle([bx+46, by+70, bx+68, by+88], radius=6, fill=METAL)

    # 발
    d.rounded_rectangle([bx+4,  by+84, bx+34, by+96], radius=4, fill=(55,62,80))
    d.rounded_rectangle([bx+42, by+84, bx+72, by+96], radius=4, fill=(55,62,80))

    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def fetch_wiki_image(article: str, out_path: Path) -> bool:
    """Wikipedia 기사 대표 이미지를 다운로드. 실패 시 False 반환."""
    headers = {"User-Agent": "TSLA-Dashboard/2.0 (github.com/korlee88/tsla-dashboard)"}
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
                    out_path.write_bytes(r2.read())
                return True
    except Exception as e:
        print(f"   ⚠ 배경 이미지 다운로드 실패 ({article}): {e}", file=sys.stderr)
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
    """Wikipedia 사진을 세로 포맷 상단 배너에 삽입. 없으면 빈 프레임 표시."""
    from PIL import Image as PILImage
    # 외곽 테두리
    draw.rounded_rectangle([x - 3, y - 3, x + w + 3, y + h + 3],
                           radius=8, outline=accent, width=2)
    if not bg_path or not bg_path.exists():
        draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=(20, 24, 32))
        return
    try:
        photo = PILImage.open(bg_path).convert("RGB")
        pw, ph = photo.size
        # 대상 비율에 맞춰 중앙 크롭
        target_ratio = w / h
        if pw / ph > target_ratio:
            new_w = int(ph * target_ratio)
            left = (pw - new_w) // 2
            photo = photo.crop([left, 0, left + new_w, ph])
        else:
            new_h = int(pw / target_ratio)
            top = (ph - new_h) // 2
            photo = photo.crop([0, top, pw, top + new_h])
        photo = photo.resize((w, h), PILImage.LANCZOS)
        # 약한 어두운 오버레이 (195/255 수준)
        ov = PILImage.new("RGBA", (w, h), (8, 10, 16, 195))
        photo = PILImage.alpha_composite(photo.convert("RGBA"), ov).convert("RGB")
        img.paste(photo, (x, y))
        # 재-draw (paste 이후 draw 객체 갱신)
        from PIL import ImageDraw as ID
        d2 = ID.Draw(img)
        d2.rounded_rectangle([x - 3, y - 3, x + w + 3, y + h + 3],
                             radius=8, outline=accent, width=2)
    except Exception as e:
        draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=(20, 24, 32))


def draw_buy_index_gauge(draw, cx, cy, r, bi, fnt_big, fnt_small):
    col = GREEN if bi >= 65 else AMBER if bi >= 45 else RED
    # 배경 반원 (회색)
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill=(40, 44, 54), width=22)
    # 값 반원 (컬러)
    end_a = 180 + int(bi / 100 * 180)
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=180, end=end_a, fill=col, width=22)
    # 중앙 숫자
    draw.text((cx, cy - 18), str(bi), font=fnt_big, fill=col, anchor="mm")
    draw.text((cx, cy + 22), "매수지수", font=fnt_small, fill=GRAY, anchor="mm")
    # 범례
    draw.text((cx - r + 8, cy + 14), "0", font=fnt_small, fill=GRAY)
    draw.text((cx + r - 22, cy + 14), "100", font=fnt_small, fill=GRAY)


def draw_news_card_portrait(draw, img, x, y, w, h, chapter, content, source, accent,
                             fnt_bold, fnt_content, fnt_source):
    """세로 포맷 전용 뉴스카드 (헤더 + 내용 + 하단 출처)."""
    from PIL import ImageDraw

    HEADER_H = 56
    FOOTER_H = 32

    # 카드 배경
    draw.rounded_rectangle([x, y, x + w, y + h], radius=10,
                            fill=(16, 19, 27), outline=accent, width=2)

    # 헤더 배경
    draw.rounded_rectangle([x, y, x + w, y + HEADER_H], radius=10, fill=accent)
    # 헤더 하단 모서리 직각화
    draw.rectangle([x, y + HEADER_H - 10, x + w, y + HEADER_H], fill=accent)

    # 챕터 이름 (헤더 왼쪽)
    draw.text((x + 16, y + HEADER_H // 2), chapter[:5],
              font=fnt_bold, fill=(10, 12, 20), anchor="lm")

    # 등급 배지 색상 결정
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

    # 등급 배지 (헤더 오른쪽)
    if badge_text:
        badge_w = 72
        badge_x = x + w - badge_w - 12
        draw.rounded_rectangle([badge_x, y + 8, badge_x + badge_w, y + HEADER_H - 8],
                               radius=6, fill=(10, 12, 20))
        draw.text((badge_x + badge_w // 2, y + HEADER_H // 2),
                  badge_text, font=fnt_source, fill=badge_col, anchor="mm")

    # 내용 영역
    content_x = x + 16
    content_y = y + HEADER_H + 14
    content_max_w = w - 32
    content_area_h = h - HEADER_H - FOOTER_H - 20

    content_lines = wrap_text(draw, content[:200], fnt_content, content_max_w)
    cy = content_y
    line_h = 36
    max_lines = content_area_h // line_h
    for line in content_lines[:max_lines]:
        if cy + line_h > y + h - FOOTER_H - 10:
            break
        draw.text((content_x, cy), line, font=fnt_content, fill=(225, 232, 245))
        cy += line_h

    # 하단 출처 바
    footer_y = y + h - FOOTER_H
    draw.rectangle([x, footer_y, x + w, y + h], fill=(10, 12, 18))
    # 하단 모서리 라운드 복원
    draw.rounded_rectangle([x, footer_y - 4, x + w, y + h], radius=10, fill=(10, 12, 18))

    # 출처 텍스트 (언론사·날짜 — 등급 제거)
    src_display = source
    for grade in grade_map:
        src_display = src_display.replace("·" + grade, "").replace(grade, "").strip("·· ")
    draw.text((x + 14, footer_y + FOOTER_H // 2), src_display[:50],
              font=fnt_source, fill=LGRAY, anchor="lm")


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

    # ── 상단 사진 배너 (Y=90, h=310, 전체 폭) ──────────────────────────────
    draw_photo_card(img, draw, accent, bg_path, x=0, y=90, w=W, h=310)
    draw = ImageDraw.Draw(img)   # paste 이후 draw 갱신

    def fnt(path, size):
        try:
            return ImageFont.truetype(path, size) if path else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()

    f_xl    = fnt(font_bold, 72)
    f_lg    = fnt(font_bold, 40)
    f_md    = fnt(font_bold, 32)
    f_md_r  = fnt(font_reg,  32)
    f_nm    = fnt(font_reg,  26)
    f_sm    = fnt(font_reg,  22)
    f_xs    = fnt(font_reg,  18)
    f_src   = fnt(font_reg,  20)
    f_ch    = fnt(font_bold, 26)   # 뉴스카드 챕터/헤더 폰트
    f_ct    = fnt(font_reg,  26)   # 뉴스카드 내용 폰트

    # ── 상단 제목 바 (Y=0~90) ──────────────────────────────────────────────
    draw.text((PAD, 30), f"  {title}", font=f_lg, fill=WHITE)
    draw.text((PAD, 30), "▌", font=f_lg, fill=accent)

    # ── 하단 푸터 (Y=1840) ────────────────────────────────────────────────
    draw.text((W // 2, 1840), "TSLA Impact Analyzer  ·  본 영상은 투자 조언이 아닙니다",
              font=f_xs, fill=(50, 55, 68), anchor="mm")

    news_lines = [l for l in lines if l.strip() and not l.startswith("SCENE")]

    # ── 씬 1: 주간 브리핑 ──────────────────────────────────────────────────
    if idx == 1:
        # Feature card (Y=400~820)
        FC_Y = START_Y
        FC_H = 420
        FC_W = COL_W

        draw.rounded_rectangle([PAD, FC_Y, PAD + FC_W, FC_Y + FC_H],
                               radius=10, fill=(20, 24, 34), outline=accent, width=2)
        # 헤더바
        draw.rounded_rectangle([PAD, FC_Y, PAD + FC_W, FC_Y + 56],
                               radius=10, fill=accent)
        draw.rectangle([PAD, FC_Y + 46, PAD + FC_W, FC_Y + 56], fill=accent)
        draw.text((PAD + 18, FC_Y + 28), "이번 주 핵심 뉴스",
                  font=f_ch, fill=(10, 12, 20), anchor="lm")

        body_y = FC_Y + 70
        labels = ["", "출처", "내용", "전망"]
        for i, line in enumerate(news_lines[:4]):
            if i == 0:
                # 헤드라인 (font_bold, 32, WHITE) — wrap to 2 lines max
                wrapped = wrap_text(draw, line, f_md, COL_W - 40)
                for wl in wrapped[:2]:
                    draw.text((PAD + 16, body_y), wl, font=f_md, fill=WHITE)
                    bb = draw.textbbox((0, 0), wl, font=f_md)
                    body_y += (bb[3] - bb[1]) + 8
                body_y += 8
            elif i == 1:
                # 출처·날짜 (font size 22, accent color)
                draw.text((PAD + 16, body_y + 2), "출처",
                          font=f_xs, fill=accent)
                draw.text((PAD + 80, body_y), line[:60],
                          font=f_sm, fill=accent)
                body_y += 36
            elif i == 2:
                # 상세 내용 (font size 24, LGRAY) — wrap to 3 lines max
                draw.text((PAD + 16, body_y + 2), "내용",
                          font=f_xs, fill=GRAY)
                content_wrapped = wrap_text(draw, line, f_nm, COL_W - 100)
                cx_y = body_y
                for wl in content_wrapped[:3]:
                    draw.text((PAD + 80, cx_y), wl, font=f_nm, fill=LGRAY)
                    bb = draw.textbbox((0, 0), wl, font=f_nm)
                    cx_y += (bb[3] - bb[1]) + 6
                body_y = cx_y + 8
            else:
                # 전망 (font size 24, accent)
                draw.text((PAD + 16, body_y + 2), "전망",
                          font=f_xs, fill=accent)
                draw.text((PAD + 80, body_y), line[:60],
                          font=f_nm, fill=accent)
                body_y += 36

        # 주간 주가 흐름 스트립 (Y=840~1040)
        STRIP_Y = 840
        STRIP_TITLE_Y = STRIP_Y
        draw.text((PAD, STRIP_TITLE_Y), "주간 주가 흐름",
                  font=f_sm, fill=GRAY)

        daily_prices = summary.get("daily_prices", [])
        BOX_Y = STRIP_TITLE_Y + 36

        if daily_prices:
            # 최대 5개 박스를 가로로 배열
            n = min(len(daily_prices), 5)
            box_gap = 12
            total_gap = box_gap * (n - 1)
            box_w = (COL_W - total_gap) // n
            for j, (date_str, price_val) in enumerate(daily_prices[:n]):
                bx = PAD + j * (box_w + box_gap)
                # MM/DD 형식으로 변환
                try:
                    parts = date_str.split("-")
                    label = f"{parts[1]}/{parts[2]}"
                except Exception:
                    label = date_str[-5:] if len(date_str) >= 5 else date_str
                draw.rounded_rectangle([bx, BOX_Y, bx + box_w, BOX_Y + 140],
                                       radius=8, fill=(18, 21, 30), outline=(40, 44, 54), width=1)
                draw.text((bx + box_w // 2, BOX_Y + 36), label,
                          font=f_xs, fill=GRAY, anchor="mm")
                try:
                    price_str = f"${float(price_val):,.2f}"
                except Exception:
                    price_str = str(price_val)
                draw.text((bx + box_w // 2, BOX_Y + 96), price_str,
                          font=f_sm, fill=WHITE, anchor="mm")
        else:
            # 폴백: 단일 현재가 박스
            price = summary.get("latest_price")
            price_str = f"${float(price):,.2f}" if price else "N/A"
            draw.rounded_rectangle([PAD, BOX_Y, PAD + 300, BOX_Y + 140],
                                   radius=8, fill=(18, 21, 30), outline=(40, 44, 54), width=1)
            draw.text((PAD + 150, BOX_Y + 36), "현재가",
                      font=f_xs, fill=GRAY, anchor="mm")
            draw.text((PAD + 150, BOX_Y + 96), price_str,
                      font=f_sm, fill=WHITE, anchor="mm")

    # ── 씬 2~3: 호재/리스크 — 세로형 대형 카드 2장 ──────────────────────
    elif idx in (2, 3):
        CARD_H = 660
        CARD_W = COL_W - PAD   # 1000
        card_positions = [START_Y, START_Y + 700]

        for i, line in enumerate(news_lines[:2]):
            chapter, content, source = parse_news_line(line)
            cy = card_positions[i]
            draw_news_card_portrait(
                draw, img,
                x=PAD, y=cy, w=CARD_W, h=CARD_H,
                chapter=chapter, content=content, source=source,
                accent=accent,
                fnt_bold=f_ch, fnt_content=f_ct, fnt_source=f_src,
            )
            # paste 후 draw 갱신
            draw = ImageDraw.Draw(img)

    # ── 씬 4: 시장 반응 — 라벨박스 + 내용 4행 ───────────────────────────
    else:
        item_positions = [START_Y, START_Y + 370, START_Y + 740, START_Y + 1110]
        labels = ["분위기", "검색·영상", "투자자", "시황"]
        ITEM_H = 330

        for i, line in enumerate(news_lines[:4]):
            iy = item_positions[i]
            # 라벨 박스 (140×56)
            lab_w = 140
            draw.rounded_rectangle([PAD, iy, PAD + lab_w, iy + 56],
                                   radius=6, fill=(28, 32, 44), outline=accent, width=1)
            draw.text((PAD + lab_w // 2, iy + 28),
                      labels[i] if i < len(labels) else "",
                      font=f_ch, fill=accent, anchor="mm")

            # 내용 (COL_W - 200 폭으로 wrap)
            content_x = PAD + lab_w + 16
            content_max_w = COL_W - lab_w - 60
            # 라벨 접두사 제거 (예: "[분위기] ")
            content_text = line
            if line.startswith("[") and "]" in line:
                bracket_end = line.index("]") + 1
                content_text = line[bracket_end:].strip()

            wrapped = wrap_text(draw, content_text, f_nm, content_max_w)
            cy_item = iy
            for wl in wrapped[:3]:
                draw.text((content_x, cy_item), wl, font=f_nm, fill=LGRAY)
                bb = draw.textbbox((0, 0), wl, font=f_nm)
                cy_item += (bb[3] - bb[1]) + 8

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

    # Wikipedia 배경 이미지 사전 다운로드
    print("   🖼 Wikipedia 배경 이미지 다운로드 중...")
    bg_paths = {}
    for scene in scenes:
        idx     = scene["index"]
        article = SCENE_WIKI_ARTICLES[idx - 1]
        bg_path = out_dir / f"bg_{idx:02d}.jpg"
        ok = fetch_wiki_image(article, bg_path)
        bg_paths[idx] = bg_path if ok else None
        status = "✅" if ok else "⚠ 실패(기본 배경 사용)"
        print(f"      씬{idx} [{article[:20]}] {status}")

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

        with open(out_dir / "script.txt", "w", encoding="utf-8") as f:
            f.write(raw)
        with open(out_dir / "script.json", "w", encoding="utf-8") as f:
            json.dump({"generated_at": today, "summary": summary, "scenes": scenes},
                      f, ensure_ascii=False, indent=2)
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
