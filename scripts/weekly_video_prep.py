"""
TSLA 주간 영상 자료 생성 스크립트
- 최근 7일 auto-sessions.json 데이터 기반
- Gemini API → 한국어 영상 대본(5 씬)
- Pillow → 씬별 1280×720 카드 이미지
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
W, H    = 1280, 720

SCENE_ACCENTS = [PURPLE, GREEN, RED, AMBER, CYAN]
SCENE_MOODS   = ["excited", "happy", "worried", "focused", "happy"]

# 씬별 Wikipedia 배경 이미지 소스
SCENE_WIKI_ARTICLES = [
    "Tesla, Inc.",              # scene 1 - 테슬라 개요
    "Tesla Cybertruck",         # scene 2 - 신제품/호재
    "Elon Musk",                # scene 3 - 머스크 리스크
    "Gigafactory Nevada",       # scene 4 - 생산/기술
    "Tesla Model S",            # scene 5 - 결론/미래
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
    }

# ── 대본 생성 ─────────────────────────────────────────────────────────────

SCRIPT_PROMPT_TEMPLATE = """아래 TSLA 주간 분석 데이터를 바탕으로 60초 이내 유튜브 쇼츠 스타일 나레이션 대본을 작성해줘.

=== 주간 데이터 ({week_start} ~ {week_end}) ===
- 매수지수: 주간 평균 {avg_bi}, 최신 {latest_bi} (0~100점, 65 이상=매수 신호)
- TSLA 주가: ${price}
- 주요 호재:
{b_txt}
- 주요 악재:
{r_txt}
- 단기 예측:
{f_txt}

=== 출력 규칙 (반드시 준수) ===
• 전체 5개 씬, 씬당 나레이션 읽는 시간 8~10초 분량
• 각 씬 최대 4줄, 줄당 최대 20자 (짧고 강렬하게!)
• PPT 낭독 금지 — 뉴스 헤드라인 + 핵심 숫자 중심으로
• 첫 줄 = 임팩트 있는 헤드라인 (5~10자)
• 나머지 = 핵심 숫자/키워드 나열
• 나레이션 톤: 빠르고 활기찬 뉴스 앵커

=== 출력 형식 ===
SCENE_1_TITLE: [6자 이내 제목]
SCENE_1:
[헤드라인]
[핵심 숫자1]
[핵심 숫자2]
[핵심 숫자3]

SCENE_2_TITLE: [6자 이내]
SCENE_2:
[호재 헤드라인]
[호재1 — 한줄 핵심]
[호재2 — 한줄 핵심]
[호재3 — 한줄 핵심]

SCENE_3_TITLE: [6자 이내]
SCENE_3:
[리스크 헤드라인]
[리스크1 — 한줄 핵심]
[리스크2 — 한줄 핵심]
[리스크3 — 한줄 핵심]

SCENE_4_TITLE: [6자 이내]
SCENE_4:
[전망 헤드라인]
[예측1: 날짜 방향 퍼센트]
[예측2: 날짜 방향 퍼센트]
[기술지표 한줄 요약]

SCENE_5_TITLE: [6자 이내]
SCENE_5:
[결론 헤드라인]
[전략 한줄]
[손절 기준]
본 영상은 투자 조언이 아닙니다"""


def _build_prompt(summary):
    b_txt = "\n".join(f"  [{n['score']:+d}] {n['title']}: {n['reason'][:70]}" for n in summary["top_bullish"]) or "  없음"
    r_txt = "\n".join(f"  [{n['score']:+d}] {n['title']}: {n['reason'][:70]}" for n in summary["top_bearish"]) or "  없음"
    f_txt = "\n".join(f"  {f.get('date','')} {f.get('signal','')} {f.get('change_pct',0):+.1f}%" for f in summary["forecasts"]) or "  없음"
    return SCRIPT_PROMPT_TEMPLATE.format(
        week_start=summary["week_start"],
        week_end=summary["week_end"],
        avg_bi=summary["avg_buy_index"],
        latest_bi=summary["latest_buy_index"],
        price=summary["latest_price"],
        b_txt=b_txt, r_txt=r_txt, f_txt=f_txt,
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
        model="gemini-2.0-flash-lite",
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
    for i in range(1, 6):
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
            nxt = raw.find(f"SCENE_{i+1}_TITLE:", s) if i < 5 else len(raw)
            body = raw[s:nxt].strip()
        # weekly_video_make.py expects "lines" as a list
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


def wrap_text(text, font, draw, max_px):
    """한글/영문 혼합 텍스트 줄 바꿈"""
    lines, cur = [], ""
    for ch in text:
        test = cur + ch
        w = draw.textlength(test, font=font)
        if w > max_px and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def render_lines(draw, text, x, y, font, fill, max_px, line_gap=8):
    """여러 줄 텍스트 렌더링 → 다음 y 반환"""
    for raw_line in text.split("\n"):
        raw_line = raw_line.strip()
        if not raw_line:
            y += line_gap
            continue
        for line in wrap_text(raw_line, font, draw, max_px):
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


def make_canvas(accent, bg_path: Path | None = None):
    from PIL import Image, ImageDraw
    if bg_path and bg_path.exists():
        # 실제 사진을 배경으로 — 어두운 오버레이 적용
        bg = Image.open(bg_path).convert("RGB").resize((W, H), Image.LANCZOS)
        overlay = Image.new("RGBA", (W, H), (8, 10, 16, 195))
        img = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    else:
        img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 6], fill=accent)
    draw.rectangle([0, H - 48, W, H], fill=(8, 10, 16))
    return img, draw


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


def draw_news_card(draw, x, y, w, h, icon, text, col, fnt_icon, fnt_text):
    draw.rectangle([x, y, x + w, y + h], fill=(22, 26, 34), outline=col, width=2)
    draw.rectangle([x, y, x + 6, y + h], fill=col)
    draw.text((x + 18, y + h // 2 - 14), icon, font=fnt_icon, fill=col, anchor="lm")
    draw.text((x + 58, y + h // 2), text, font=fnt_text, fill=WHITE, anchor="lm")


def draw_stat_box(draw, x, y, w, h, label, value, col, fnt_val, fnt_lbl):
    draw.rectangle([x, y, x + w, y + h], fill=(18, 21, 30), outline=(40, 44, 54), width=1)
    draw.text((x + w // 2, y + 18), label, font=fnt_lbl, fill=GRAY, anchor="mt")
    draw.text((x + w // 2, y + h - 22), value, font=fnt_val, fill=col, anchor="mb")


def build_scene_image(scene, summary, font_reg, font_bold, bg_path: Path | None = None):
    from PIL import ImageFont
    idx    = scene["index"]
    title  = scene["title"] or f"씬 {idx}"
    lines  = scene.get("lines") or [l.strip() for l in (scene.get("body") or "").split("\n") if l.strip()]
    accent = SCENE_ACCENTS[idx - 1]

    img, draw = make_canvas(accent, bg_path)

    def fnt(path, size):
        try:
            return ImageFont.truetype(path, size) if path else ImageFont.load_default()
        except Exception:
            return ImageFont.load_default()

    f_xl    = fnt(font_bold, 80)
    f_lg    = fnt(font_bold, 44)
    f_md    = fnt(font_reg,  30)
    f_sm    = fnt(font_reg,  22)
    f_xs    = fnt(font_reg,  17)
    f_icon  = fnt(font_bold, 28)

    # 상단: 씬 번호 + 제목
    draw.text((52, 18), f"  {title}", font=f_lg, fill=WHITE)
    draw.text((52, 18), "▌", font=f_lg, fill=accent)
    # 하단 워터마크
    draw.text((W // 2, H - 28), "TSLA Impact Analyzer  ·  본 영상은 투자 조언이 아닙니다", font=f_xs, fill=(50, 55, 68), anchor="mm")

    PAD = 60

    # ── Scene 1: 매수지수 게이지 + 핵심 3 통계 ──────────────────────────────
    if idx == 1:
        bi    = summary.get("latest_buy_index") or 50
        price = summary.get("latest_price")
        bi_col = GREEN if bi >= 65 else AMBER if bi >= 45 else RED
        sig   = "매수" if bi >= 65 else "관망" if bi >= 45 else "매도"

        # 게이지 (좌측)
        draw_buy_index_gauge(draw, 310, 420, 200, bi, f_xl, f_md)
        draw.text((310, 560), sig, font=f_lg, fill=bi_col, anchor="mm")

        # 우측 통계 박스 3개
        bw, bh = 340, 110
        bx = 660
        stats = [
            ("현재가", f"${price:,.2f}" if price else "N/A", WHITE),
            ("주간 평균", f"매수지수 {summary.get('avg_buy_index', '-')}", AMBER),
            ("세션 수", f"최근 7일  {summary.get('session_count', 0)}건", CYAN),
        ]
        for i, (lbl, val, col) in enumerate(stats):
            draw_stat_box(draw, bx, 160 + i * (bh + 16), bw, bh, lbl, val, col, f_md, f_sm)

    # ── Scene 2: 호재 뉴스카드 ─────────────────────────────────────────────
    elif idx == 2:
        news = [l for l in lines if l.strip() and not l.startswith("SCENE")]
        card_h = 108
        icons  = ["▲", "▲", "▲", "▲"]
        for i, (line, icon) in enumerate(zip(news[:4], icons)):
            draw_news_card(draw, PAD, 110 + i * (card_h + 14), W - PAD * 2, card_h,
                           icon, line[:34], GREEN, f_icon, f_md)

    # ── Scene 3: 리스크 카드 ──────────────────────────────────────────────
    elif idx == 3:
        news  = [l for l in lines if l.strip() and not l.startswith("SCENE")]
        card_h = 108
        icons  = ["▼", "▼", "▼", "▼"]
        for i, (line, icon) in enumerate(zip(news[:4], icons)):
            draw_news_card(draw, PAD, 110 + i * (card_h + 14), W - PAD * 2, card_h,
                           icon, line[:34], RED, f_icon, f_md)

    # ── Scene 4: 예측 차트 + 기술지표 ─────────────────────────────────────
    elif idx == 4:
        forecasts = summary.get("forecasts", [])
        price     = summary.get("latest_price") or 0
        box_w     = (W - PAD * 2 - 28) // 3

        for j, fc in enumerate(forecasts[:3]):
            pct  = fc.get("change_pct") or 0
            sig  = fc.get("signal", "")
            date = str(fc.get("date", f"D+{j+1}"))[-5:]
            col  = GREEN if pct > 0.3 else RED if pct < -0.3 else AMBER
            bx   = PAD + j * (box_w + 14)
            draw.rectangle([bx, 110, bx + box_w, 280], fill=(18, 21, 30), outline=col, width=2)
            draw.text((bx + box_w // 2, 130), date, font=f_sm, fill=GRAY, anchor="mt")
            draw.text((bx + box_w // 2, 185), f"{pct:+.1f}%", font=f_lg, fill=col, anchor="mm")
            draw.text((bx + box_w // 2, 258), sig, font=f_sm, fill=col, anchor="mb")

        # 기술지표 바 (하단)
        tech_items = [
            ("RSI", summary.get("avg_buy_index") or 50, 100, PURPLE),
            ("매수지수", summary.get("latest_buy_index") or 50, 100, GREEN),
        ]
        ty = 320
        bar_max_w = W - PAD * 2 - 120
        for label, val, max_val, col in tech_items:
            ratio    = min(max(val / max_val, 0), 1)
            bar_fill = int(bar_max_w * ratio)
            draw.text((PAD, ty + 8), label, font=f_sm, fill=GRAY)
            draw.rectangle([PAD + 110, ty, PAD + 110 + bar_max_w, ty + 32], fill=(28, 31, 40))
            draw.rectangle([PAD + 110, ty, PAD + 110 + bar_fill, ty + 32], fill=col)
            draw.text((PAD + 110 + bar_max_w + 14, ty + 8), str(val), font=f_sm, fill=col)
            ty += 52

        # 나머지 본문 텍스트
        y = ty + 10
        for line in lines[-2:]:
            if line.strip():
                draw.text((PAD, y), line[:48], font=f_sm, fill=LGRAY)
                y += 34

    # ── Scene 5: 결론 카드 ────────────────────────────────────────────────
    else:
        bi    = summary.get("latest_buy_index") or 50
        bi_col = GREEN if bi >= 65 else AMBER if bi >= 45 else RED
        sig   = "매 수" if bi >= 65 else "관 망" if bi >= 45 else "매 도"

        draw.text((W // 2, 270), sig, font=f_xl, fill=bi_col, anchor="mm")
        draw.rectangle([W // 2 - 160, 310, W // 2 + 160, 316], fill=bi_col)

        strat_lines = [l for l in lines if l.strip()]
        y = 350
        for line in strat_lines[:4]:
            draw.text((W // 2, y), line[:36], font=f_md, fill=LGRAY, anchor="mt")
            y += 48

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
        scenes = [{"index": i, "title": f"씬 {i}", "lines": [], "body": ""} for i in range(1, 6)]
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
    print(f"   🖼 scene_01~05.png — 씬별 배경 카드 이미지 (1280×720)")
    print(f"   CapCut / Premiere 등에서 이미지+자막 조합 후 영상 제작 가능합니다.")


if __name__ == "__main__":
    main()
