"""
TSLA 주간 영상 자료 생성 스크립트
- 최근 7일 auto-sessions.json 데이터 기반
- Gemini API → 한국어 영상 대본(5 씬)
- Pillow → 씬별 1280×720 카드 이미지
- 저장: data/weekly-report/YYYY-MM-DD/
"""

import os, json, sys, textwrap
from datetime import datetime, timezone, timedelta
from pathlib import Path

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")   # fallback
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

SCRIPT_PROMPT_TEMPLATE = """아래 TSLA 주간 분석 데이터를 바탕으로 투자 정보 유튜브 영상의 자막 대본을 작성해줘.

=== 주간 데이터 ({week_start} ~ {week_end}) ===
- 매수지수: 주간 평균 {avg_bi}, 최신 {latest_bi} (0~100점, 65 이상=매수 신호)
- TSLA 주가: ${price}
- 주요 호재:
{b_txt}
- 주요 악재:
{r_txt}
- 단기 예측:
{f_txt}

=== 출력 형식 (반드시 아래 형식 준수) ===
SCENE_1_TITLE: [오프닝 제목, 10자 이내]
SCENE_1:
[오프닝 자막, 3~4줄. 이번 주 TSLA 핵심 요약 + 매수지수 현황]

SCENE_2_TITLE: [호재 제목, 10자 이내]
SCENE_2:
[주요 호재 3가지, 각 2줄 이내. 핵심만 간결하게]

SCENE_3_TITLE: [악재 제목, 10자 이내]
SCENE_3:
[주요 악재 3가지, 각 2줄 이내. 핵심만 간결하게]

SCENE_4_TITLE: [전망 제목, 10자 이내]
SCENE_4:
[매수지수 해석 + 단기 예측 + 투자 시사점, 3~4줄]

SCENE_5_TITLE: [클로징 제목, 10자 이내]
SCENE_5:
[마무리 2~3줄. 채널 구독 유도 + "본 영상은 투자 조언이 아닙니다" 문구 포함]

전문적이고 객관적인 톤. 각 씬은 10~20초 분량의 임팩트 있는 자막으로. 숫자·퍼센트 적극 활용."""


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
    """Claude Opus 4 — 대본의 핵심 생성 담당"""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def generate_script_gemini(prompt):
    """Gemini Flash — Opus 키 없을 때 fallback"""
    import google.generativeai as genai
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")
    return model.generate_content(prompt).text


def generate_script(summary):
    prompt = _build_prompt(summary)
    if ANTHROPIC_API_KEY:
        print("   🤖 Claude Opus 4로 대본 생성 중...")
        return generate_script_opus(prompt)
    elif GEMINI_API_KEY:
        print("   🤖 Gemini Flash로 대본 생성 중 (fallback)...")
        return generate_script_gemini(prompt)
    else:
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
        scenes.append({"index": i, "title": title, "body": body})
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


def make_canvas(accent):
    from PIL import Image, ImageDraw
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    # 상단 액센트 바
    draw.rectangle([0, 0, W, 7], fill=accent)
    # 본문 카드
    draw.rectangle([36, 36, W - 36, H - 36], fill=CARD, outline=BORDER, width=1)
    # 하단 워터마크 줄
    draw.rectangle([0, H - 44, W, H], fill=(10, 12, 18))
    return img, draw


def build_scene_image(scene, summary, font_reg, font_bold):
    from PIL import ImageFont
    idx    = scene["index"]
    title  = scene["title"] or f"씬 {idx}"
    body   = scene["body"]  or ""
    accent = SCENE_ACCENTS[idx - 1]

    img, draw = make_canvas(accent)

    def fnt(path, size):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default()

    f_label = fnt(font_reg,  18)
    f_title = fnt(font_bold, 46)
    f_body  = fnt(font_reg,  28)
    f_small = fnt(font_reg,  22)

    # 씬 레이블
    draw.text((60, 52), f"SCENE {idx}", font=f_label, fill=accent)
    # 제목
    draw.text((60, 80), title, font=f_title, fill=WHITE)
    # 하단 워터마크
    draw.text((W - 310, H - 32), "TSLA Impact Analyzer · 투자 조언 아님", font=f_label, fill=(55, 60, 75))

    y0 = 158
    pad_x = 60
    max_w = W - 120

    if idx == 1:
        # 매수지수 큰 숫자 (좌측) + 본문 (우측)
        bi = summary.get("latest_buy_index")
        if bi is not None:
            bi_col = GREEN if bi >= 65 else AMBER if bi >= 45 else RED
            f_big  = fnt(font_bold, 130)
            draw.text((pad_x, y0), str(bi), font=f_big, fill=bi_col)
            label_y = y0 + 140
            draw.text((pad_x + 10, label_y), "매수지수", font=f_body, fill=GRAY)
        render_lines(draw, body, W // 2 + 20, y0 + 20, f_body, LGRAY, W // 2 - 80)

    elif idx in (2, 3):
        col = GREEN if idx == 2 else RED
        lines = [l.strip() for l in body.split("\n") if l.strip()]
        y = y0
        for i, line in enumerate(lines[:7]):
            is_headline = (i % 2 == 0)
            f = f_body if is_headline else f_small
            c = (220, 235, 220) if is_headline and idx == 2 else \
                (235, 210, 210) if is_headline and idx == 3 else GRAY
            y = render_lines(draw, line, pad_x, y, f, c, max_w, 6)
            if is_headline:
                y += 2

    elif idx == 4:
        price = summary.get("latest_price")
        y = y0
        if price:
            draw.text((pad_x, y), f"현재가  ${price:,.2f}", font=f_body, fill=WHITE)
            y += 50

        forecasts = summary.get("forecasts", [])
        box_w = 350
        for j, fc in enumerate(forecasts[:3]):
            pct  = fc.get("change_pct", 0) or 0
            sig  = fc.get("signal", "")
            date = fc.get("date", f"D+{j+1}")
            col  = GREEN if pct > 0.5 else RED if pct < -0.5 else GRAY
            bx   = pad_x + j * (box_w + 14)
            draw.rectangle([bx, y, bx + box_w, y + 88], fill=(20, 23, 30), outline=BORDER, width=1)
            draw.text((bx + 14, y + 10), date,                   font=f_small, fill=GRAY)
            draw.text((bx + 14, y + 36), f"{pct:+.1f}%  {sig}", font=f_body,  fill=col)
        y += 106
        render_lines(draw, body, pad_x, y, f_small, LGRAY, max_w, 8)

    else:  # scene 5
        render_lines(draw, body, pad_x, y0, f_body, LGRAY, max_w, 10)

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

    for scene in scenes:
        img  = build_scene_image(scene, summary, font_reg, font_bold)
        path = out_dir / f"scene_{scene['index']:02d}.png"
        img.save(path, "PNG")
        print(f"   ✅ scene_{scene['index']:02d}.png 저장")

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
        scenes = [{"index": i, "title": f"씬 {i}", "body": ""} for i in range(1, 6)]
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
