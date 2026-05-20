"""
주간 영상 자료 생성 스크립트
- 최근 7일 auto-sessions.json 데이터 기반
- Gemini API → 한국어 영상 대본(4 씬)
- Pillow → 씬별 1080×1920 카드 이미지 (YouTube Shorts 세로 포맷)
- 저장: data/weekly-report/YYYY-MM-DD/

종목 설정: config/ticker.json
"""

import os, json, sys, re, urllib.request, urllib.parse
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

SCENE_ACCENTS = [CYAN, PURPLE, GREEN, AMBER, (236, 72, 153)]  # 인트로/브리핑/호재/시황/클로징

SCENE_WIKI_ARTICLES = TICKER_CONFIG["scene_wiki_articles"]
GOOGLE_TRENDS_KEYWORDS = TICKER_CONFIG.get("google_trends_keywords", [])

SCENE_BG_DIR = ROOT_DIR / "data" / "scene-backgrounds"
SCENE_STATIC_BG = [
    (SCENE_BG_DIR / name) if name else None
    for name in TICKER_CONFIG["scene_static_bg_files"]
]

CALENDAR_JSON = ROOT_DIR / "data" / "calendar.json"

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
            score    = a.get("impact_score", 0) or 0
            dir_     = a.get("direction", "")
            reason   = a.get("reasoning", "")
            source   = n.get("source", "")
            date     = n.get("date", "")
            category = n.get("category", "")
            if dir_ == "bullish" and score >= 2:
                bullish.append({"title": title, "score": score, "reason": reason,
                                "source": source, "date": date, "category": category})
            elif dir_ == "bearish" and score <= -2:
                bearish.append({"title": title, "score": score, "reason": reason,
                                "source": source, "date": date, "category": category})

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

    # ── 인트로용: 오늘 vs 전일 변동률 ──
    today_change_pct = None
    if len(daily_prices) >= 2:
        try:
            today_p = float(daily_prices[0][1])
            prev_p  = float(daily_prices[1][1])
            if prev_p > 0:
                today_change_pct = round((today_p - prev_p) / prev_p * 100, 2)
        except (ValueError, TypeError):
            pass

    # ── 인트로용: 이번주 가장 큰 영향 사건 ──
    biggest_impact = None
    bull_top = bullish[0] if bullish else None
    bear_top = bearish[0] if bearish else None
    if bull_top and bear_top:
        if abs(bull_top["score"]) >= abs(bear_top["score"]):
            biggest_impact = {**bull_top, "direction_ko": "호재", "emoji": "🚀"}
        else:
            biggest_impact = {**bear_top, "direction_ko": "악재", "emoji": "⚠"}
    elif bull_top:
        biggest_impact = {**bull_top, "direction_ko": "호재", "emoji": "🚀"}
    elif bear_top:
        biggest_impact = {**bear_top, "direction_ko": "악재", "emoji": "⚠"}

    avg_bi = round(sum(buy_indices) / len(buy_indices)) if buy_indices else None
    overall_signal = ("긍정" if avg_bi >= 65 else "중립" if avg_bi >= 45 else "신중") if avg_bi is not None else None

    return {
        "week_start":      sessions[-1].get("date", ""),
        "week_end":        sessions[0].get("date", ""),
        "session_count":   len(sessions),
        "buy_indices":     buy_indices,
        "avg_buy_index":   avg_bi,
        "latest_buy_index": buy_indices[0] if buy_indices else None,
        "price_start":     prices[-1] if prices else None,
        "price_end":       prices[0]  if prices else None,
        "latest_price":    latest.get("latestTslaPrice"),
        "today_price":     latest.get("latestTslaPrice"),
        "today_change_pct": today_change_pct,
        "biggest_impact":  biggest_impact,
        "top_bullish":     bullish[:3],
        "top_bearish":     bearish[:3],
        "forecasts":       latest.get("dailyForecasts", [])[:3],
        "daily_prices":    daily_prices,
        "overall_signal":  overall_signal,
        "trends":          None,        # fetch_google_trends()로 채움
        "next_events":     [],          # load_next_events()로 채움
    }


def fetch_google_trends(keywords, days=7):
    """지난 7일 vs 직전 7일 검색량 비교 → 증감비율 + 최고 키워드."""
    if not keywords:
        return None
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("   ⚠ pytrends 미설치 — Google Trends 건너뜀", file=sys.stderr)
        return None
    try:
        py = TrendReq(hl='ko-KR', tz=540, timeout=(5, 15))
        py.build_payload(keywords[:5], timeframe=f'now {days*2}-d', geo='KR')
        df = py.interest_over_time()
        if df.empty:
            return None
        kw_cols = [k for k in keywords if k in df.columns]
        if not kw_cols:
            return None
        half = len(df) // 2
        if half < 1:
            return None
        recent = float(df.iloc[half:][kw_cols].mean().mean())
        prev   = float(df.iloc[:half][kw_cols].mean().mean())
        ratio  = round(recent / max(prev, 1), 1)
        top_kw = df[kw_cols].iloc[half:].mean().idxmax()
        return {
            "ratio": ratio,
            "top_keyword": str(top_kw),
            "recent_avg": round(recent),
        }
    except Exception as e:
        print(f"   ⚠ Google Trends 실패: {e}", file=sys.stderr)
        return None


def load_next_events(days=14, max_n=3):
    """calendar.json에서 향후 N일 내 high/medium importance 이벤트 추출."""
    if not CALENDAR_JSON.exists():
        return []
    try:
        with open(CALENDAR_JSON, encoding="utf-8") as f:
            raw = json.load(f)
        events = raw if isinstance(raw, list) else raw.get("events", [])
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cutoff = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
        upcoming = [
            e for e in events
            if today < e.get("date", "") <= cutoff
        ]
        # importance: high > medium > low, 그리고 빠른 날짜 우선
        importance_rank = {"high": 0, "medium": 1, "low": 2}
        upcoming.sort(key=lambda e: (
            importance_rank.get(e.get("importance", "low"), 3),
            e.get("date", ""),
        ))
        return upcoming[:max_n]
    except Exception as e:
        print(f"   ⚠ calendar.json 로드 실패: {e}", file=sys.stderr)
        return []

# ── 대본 생성 ─────────────────────────────────────────────────────────────

SCRIPT_PROMPT_TEMPLATE = """아래 {ticker} 주간 데이터를 바탕으로 YouTube Shorts 바이럴 나레이션 대본을 작성해줘.
**자극적 이벤트형 톤**으로 시청자가 첫 3초에 멈춰서 보게 만들어야 한다.

=== 톤 가이드 (반드시 준수) ===
• 강한 감탄사 필수: "충격!", "와!", "헐!", "대박!", "이게 실화!", "헉!"
• 강조 표현: "역대급", "사상 최대", "예측 불가", "충격적", "초비상", "역대 1위"
• 긴급성: "지금 당장", "놓치면 큰일", "오늘만", "단 1주", "마지막 기회"
• 호기심 유발: "여러분 모르셨죠?", "이거 보면 깜짝", "진짜 충격이에요"
• 절대 평이한 설명조 금지 — 모든 줄에 감정 텐션 + 호기심 트리거 필수
• 씬 0·4: 정확히 2줄 / 씬 1~3: 정확히 4줄, 한 줄 25자 이내

=== 주간 데이터 ({week_start} ~ {week_end}) ===
- 참고지수: 평균 {avg_bi}점 / 최신 {latest_bi}점
- {ticker} 주가: ${price}
- 오늘 변동률: {today_change_pct_str}
- 이번주 최대 영향: {biggest_impact_str}
- 검색량 트렌드: {trends_str}
- 다음주 예정 이벤트: {next_events_str}
{daily_prices_txt}
- 주요 호재:
{b_txt}
- 주요 악재:
{r_txt}

=== 씬 구성 (총 5씬) ===

【씬 0 — 충격 인트로】 시청자 시선 강탈, 0.5초도 못 떼게 (2줄)
- 줄1: "충격! 오늘 TSLA {today_change_pct_short}!" (15자 이내, 이모지 없이)
- 줄2: 이번주 최대 영향 사건 자극적 한 문장 (25자 이내, 감탄사+호기심)

【씬 1 — 주간 브리핑】 (4줄, 한 줄 25자 이내)
- 줄1: 감탄사 + 이번주 핵심 헤드라인 (20자 이내, 가장 충격적 사실)
- 줄2: 주가·참고지수 수치 포함 한 문장 (예: "현재 $XXX, 참고지수 XX점!")
- 줄3: 이번주 가장 큰 호재 핵심 (25자 이내, 구체 수치 포함)
- 줄4: 이번주 주목할 체크포인트 한 줄 (25자 이내)

【씬 2 — 호재 심층 분석 (BEST 1건)】 모든 줄에 구체 수치(%, $, 대수, 인도량) 필수
- 줄1: "카테고리: 호재 핵심 (20자 이내, 가장 강렬한 표현)"
- 줄2: "   ↳ 배경·맥락 (25자 이내, 구체 수치 포함)"
- 줄3: "   ↳ 임팩트·영향 (25자 이내, %, $, 주가 등 수치 의무)"
- 줄4: "   ↳ 향후 전망 (25자 이내, 투자 권유 금지)"

【씬 3 — 시장 반응】 (4줄, 한 줄 25자 이내)
- 줄1: "[분위기] 이번 주 투자심리 자극적 한 문장 (감탄사 필수)"
- 줄2: "[거래량] 이번 주 특이 거래·옵션 동향 한 줄 (수치 포함)"
- 줄3: "[애널리스트] 주요 목표주가·의견 변화 한 줄"
- 줄4: "[전망] 긍정/중립/신중 관점 한 문장 (투자 권유 금지)"

【씬 4 — 다음주 예고 + CTA】 (2줄)
- 줄1: "다음주 [이벤트] 임박! 절대 놓치지 마!" (calendar 이벤트 활용)
- 줄2: "구독+알림으로 1초도 늦지 마세요!"

=== 출력 형식 (반드시 준수) ===
SCENE_0_TITLE: [6자 이내, "충격속보" 같은 강한 단어]
SCENE_0:
[줄1 — 충격 헤드라인]
[줄2 — 최대 영향 사건]

SCENE_1_TITLE: [6자 이내]
SCENE_1:
[줄1 — 핵심 헤드라인]
[줄2 — 주가·참고지수 수치]
[줄3 — 최대 호재 핵심]
[줄4 — 최대 악재 핵심]

SCENE_2_TITLE: [6자 이내, "역대급" "충격급" 같은 강한 단어]
SCENE_2:
카테고리: 호재 핵심 한 줄
   ↳ 배경·맥락 수치 포함
   ↳ 임팩트 수치 강조 (%, $, 대수 의무)
   ↳ 향후 전망 한 문장

SCENE_3_TITLE: [6자 이내]
SCENE_3:
[분위기] 내용
[거래량] 내용
[애널리스트] 내용
[전망] 내용

SCENE_4_TITLE: [6자 이내, "예고편" 같은 단어]
SCENE_4:
[줄1 — 다음주 예고]
[줄2 — 구독 CTA]

=== 배경 이미지 프롬프트 (Gemini Imagen용, 영어, 5개) ===
각 60단어 이상. 반드시 포함: "no text, no letters, no watermark, no logo", "9:16 vertical aspect ratio, ultra-high resolution".
{company_ko}·{industry_ko} 관련 시각 요소 포함. 씬별 색감 지정.

IMAGE_PROMPT_0: [씬0 — 충격 인트로, 시안+검정 강한 대비, 번개·폭발 등 임팩트 요소]
IMAGE_PROMPT_1: [씬1 — {company_ko} 관련 보라빛 미래적 분위기]
IMAGE_PROMPT_2: [씬2 — 호재 심층, 밝고 활기찬 초록빛, 성장·상승·폭발 시각화]
IMAGE_PROMPT_3: [씬3 — 시장 반응 시각화, 도시·금융 주황빛]
IMAGE_PROMPT_4: [씬4 — 미래 전망, 마젠타·핑크빛, 별·반짝임]"""


def _build_prompt(summary):
    b_txt = "\n".join(
        f"  [{n['score']:+d}] {n['title']} ({n.get('source','')}·{n.get('date','')}·{n.get('category','')}): {n['reason'][:70]}"
        for n in summary["top_bullish"]
    ) or "  없음"
    r_txt = "\n".join(f"  [{n['score']:+d}] {n['title']}: {n['reason'][:70]}" for n in summary["top_bearish"]) or "  없음"

    daily_prices = summary.get("daily_prices", [])
    if daily_prices:
        dp_lines = "\n".join(f"  {d}: ${p:,.2f}" for d, p in daily_prices)
        daily_prices_txt = f"- 최근 주가 흐름:\n{dp_lines}"
    else:
        daily_prices_txt = ""

    # 인트로용 변동률 문자열
    tcp = summary.get("today_change_pct")
    if tcp is not None:
        sign = "+" if tcp >= 0 else ""
        today_change_pct_str = f"{sign}{tcp}% (전일 대비)"
        today_change_pct_short = f"{sign}{tcp}%"
    else:
        today_change_pct_str = "변동 데이터 없음"
        today_change_pct_short = "주목!"

    # 인트로용 최대 영향 사건
    bi = summary.get("biggest_impact")
    if bi:
        biggest_impact_str = f"[{bi['direction_ko']} {bi['score']:+d}점] {bi['title']}: {bi.get('reason', '')[:80]}"
    else:
        biggest_impact_str = "큰 사건 없음"

    # Google Trends
    trends = summary.get("trends")
    if trends:
        trends_str = f"검색량 {trends['ratio']}배 변화 (최고 키워드: {trends['top_keyword']})"
    else:
        trends_str = "데이터 없음"

    # 다음주 이벤트
    next_events = summary.get("next_events", [])
    if next_events:
        next_events_str = "; ".join(
            f"{e.get('date', '')} {e.get('title', '')}" for e in next_events
        )
    else:
        next_events_str = "예정 이벤트 없음 (실적 발표·신제품 발표 등 일반 모니터링)"

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
        today_change_pct_str=today_change_pct_str,
        today_change_pct_short=today_change_pct_short,
        biggest_impact_str=biggest_impact_str,
        trends_str=trends_str,
        next_events_str=next_events_str,
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


_last_model = "AI"

def generate_script(summary):
    global _last_model
    prompt = _build_prompt(summary)
    if ANTHROPIC_API_KEY:
        try:
            print("   🤖 Claude Opus 4로 대본 생성 중...")
            result = generate_script_opus(prompt)
            _last_model = "Claude Opus 4"
            return result
        except Exception as e:
            print(f"   ⚠ Opus 실패 ({e}) — Gemini로 전환", file=sys.stderr)
    if GEMINI_API_KEY:
        print("   🤖 Gemini Flash로 대본 생성 중...")
        _last_model = "Gemini Flash"
        return generate_script_gemini(prompt)
    raise RuntimeError("ANTHROPIC_API_KEY 또는 GEMINI_API_KEY 필요")


def parse_script(raw):
    scenes = []
    SCENE_RANGE = range(0, 5)   # 씬 0(인트로) ~ 씬 4(클로징)
    for i in SCENE_RANGE:
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
    """대본에서 씬별 Imagen 프롬프트 추출 → {0: "...", 1: "...", ...}"""
    prompts = {}
    for i in range(0, 5):
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


_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # 감정/얼굴
    "\U0001F300-\U0001F5FF"  # 기호/사물
    "\U0001F680-\U0001F6FF"  # 교통/지도
    "\U0001F1E0-\U0001F1FF"  # 국기
    "\U00002700-\U000027BF"  # 기타
    "\U0001F900-\U0001F9FF"  # 보충 기호
    "\U00002600-\U000026FF"  # 잡기호
    "‍"                  # ZWJ
    "️"                  # 변형 선택자
    "]+",
    flags=re.UNICODE,
)

def strip_emoji(text: str) -> str:
    """PIL에서 렌더링 불가한 이모지를 제거한다."""
    return _EMOJI_RE.sub("", text).strip()


def draw_bell_icon(draw, cx, cy, size, color):
    """PIL 도형으로 그린 벨 아이콘 (🔔 이모지 대체)."""
    s = size
    # 돔 (반원 — 벨 상단)
    draw.pieslice([cx - s // 2, cy - s, cx + s // 2, cy], 180, 0, fill=color)
    # 몸통 (아래로 퍼지는 사다리꼴)
    body = [
        (cx - s // 2,       cy - s // 6),
        (cx + s // 2,       cy - s // 6),
        (cx + s // 2 + s // 5, cy + s // 2),
        (cx - s // 2 - s // 5, cy + s // 2),
    ]
    draw.polygon(body, fill=color)
    # 하단 챙 (가로 타원 아크)
    hw = s // 2 + s // 5 + 8
    draw.arc([cx - hw, cy + s // 3, cx + hw, cy + s // 2 + s // 4],
             0, 180, fill=color, width=max(s // 6, 5))
    # 손잡이 (상단 작은 아치)
    draw.arc([cx - s // 8, cy - s - s // 8, cx + s // 8, cy - s + s // 8],
             180, 0, fill=color, width=max(s // 10, 4))
    # 추 (하단 작은 원)
    cr = s // 8
    draw.ellipse([cx - cr, cy + s // 2, cx + cr, cy + s // 2 + cr * 2], fill=color)


def draw_bi_legend(draw, avg_bi, fnt_label, fnt_val):
    """하단 안전 영역에 매수지수 범례 + 현재 점수 표시 (y=1700~1870). 씬 4에만 사용."""
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

    # 면책 문구 + 참고 뉴스 강조 (우측)
    disclaimer = "※ 투자 권유 아님 · 참고 뉴스 · 투자 판단은 본인 책임"
    db = draw.textbbox((0, 0), disclaimer, font=fnt_label)
    dw = db[2] - db[0]
    draw.text((LX + LW - dw - 10, LY + LH - 26),
              disclaimer, font=fnt_label, fill=(200, 160, 80))


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


def draw_up_arrow(draw, cx, y_top, y_bot, color, width=10):
    """세로 ↑ 화살표 (삼각형 머리 + 직선 몸체)."""
    body_top = y_top + 36
    draw.rectangle([cx - width // 2, body_top, cx + width // 2, y_bot], fill=color)
    head_pts = [(cx, y_top), (cx - 18, body_top), (cx + 18, body_top)]
    draw.polygon(head_pts, fill=color)


def draw_bullish_hero_card(draw, img, x, y, w, h, headline, details, score,
                            source, date, accent, fnt_bold, fnt_content,
                            fnt_source, fnt_content_xl=None, fnt_content_sm=None):
    """호재 심층 히어로 카드 — BEST 배지 + ↑ 화살표 + score 강조 + 4줄 스토리텔링."""
    from PIL import ImageDraw

    HEADER_H = 90
    FOOTER_H = 64

    # 카드 배경
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14,
                            fill=(16, 19, 27), outline=accent, width=2)

    # 헤더 배경 (GREEN 강조)
    draw.rounded_rectangle([x, y, x + w, y + HEADER_H], radius=14, fill=accent)
    draw.rectangle([x, y + HEADER_H - 14, x + w, y + HEADER_H], fill=accent)

    # 헤더 왼쪽: score 강조
    score_text = f"{score:+d}pt"
    draw.text((x + 22, y + HEADER_H // 2), score_text,
              font=fnt_bold, fill=(10, 12, 20), anchor="lm",
              stroke_width=2, stroke_fill=(0, 80, 0))

    # 헤더 오른쪽: "BEST" 배지
    badge_w, badge_h = 110, 52
    bx = x + w - badge_w - 16
    by = y + (HEADER_H - badge_h) // 2
    draw.rounded_rectangle([bx, by, bx + badge_w, by + badge_h],
                           radius=10, fill=(10, 12, 20))
    draw.text((bx + badge_w // 2, by + badge_h // 2),
              "BEST", font=fnt_bold, fill=KEY, anchor="mm",
              stroke_width=1, stroke_fill=STROKE)

    # ↑ 화살표 (카드 왼쪽)
    arrow_cx  = x + 30
    arrow_top = y + HEADER_H + 20
    arrow_bot = y + h - FOOTER_H - 20
    draw_up_arrow(draw, arrow_cx, arrow_top, arrow_bot, GREEN, width=10)

    # 본문 영역 (화살표 오른쪽)
    content_x    = x + 60
    content_y    = y + HEADER_H + 16
    content_max_w = w - 60 - 22
    content_area_h = h - HEADER_H - FOOTER_H - 32

    all_lines = [headline] + [d for d in details if d.strip()]

    char_count = max((len(l) for l in all_lines if l.strip()), default=0)
    if fnt_content_xl and char_count < 60:
        body_font = fnt_content_xl
    elif fnt_content_sm and char_count >= 120:
        body_font = fnt_content_sm
    else:
        body_font = fnt_content

    bb = draw.textbbox((0, 0), "가", font=body_font)
    char_h = bb[3] - bb[1]
    line_h = char_h + 14

    cy = content_y
    for i, ln in enumerate(all_lines[:4]):
        if not ln.strip() or cy + char_h > y + h - FOOTER_H - 8:
            continue
        use_font = fnt_bold if i == 0 else body_font
        use_col  = WHITE    if i == 0 else LGRAY
        sw       = 2        if i == 0 else 1
        wrapped  = wrap_text(draw, strip_emoji(ln), use_font, content_max_w)
        for wl in wrapped[:2]:
            if cy + char_h > y + h - FOOTER_H - 8:
                break
            draw.text((content_x, cy), wl, font=use_font, fill=use_col,
                      stroke_width=sw, stroke_fill=STROKE)
            cy += line_h

    # 하단 출처 바 (source · date)
    footer_y = y + h - FOOTER_H
    draw.rounded_rectangle([x, footer_y - 6, x + w, y + h], radius=14, fill=(10, 12, 18))
    footer_text = " · ".join(filter(None, [source, date])) or "출처 미상"
    draw.text((x + 18, footer_y + FOOTER_H // 2), footer_text[:50],
              font=fnt_source, fill=KEY, anchor="lm",
              stroke_width=1, stroke_fill=STROKE)


def build_scene_image(scene, summary, font_reg, font_bold, bg_path: Path | None = None):
    from PIL import ImageFont, ImageDraw
    idx    = scene["index"]
    title  = scene["title"] or f"씬 {idx}"
    lines  = scene.get("lines") or [l.strip() for l in (scene.get("body") or "").split("\n") if l.strip()]
    accent = SCENE_ACCENTS[idx]   # 0-based: 0=인트로, 1~4=본편, 5=클로징

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
    # 인트로 전용: 대형 % 숫자
    f_huge      = fnt(font_bold, 200)
    f_huge_sub  = fnt(font_bold, 56)

    news_lines = [l for l in lines if l.strip() and not l.startswith("SCENE")]

    # ╔══════════════════════════════════════════════════════════════════╗
    # ║ 씬 0 — 충격 인트로 (custom layout)                                ║
    # ╚══════════════════════════════════════════════════════════════════╝
    if idx == 0:  # ── 씬 0: 충격 인트로 (idx 불변)
        # 전체 배경: 검정 → 시안 그라데이션
        for yy in range(H):
            t = yy / H
            r = int(0 + (6 - 0) * t)
            g = int(0 + (60 - 0) * t)
            b = int(20 + (90 - 20) * t)
            draw.line([(0, yy), (W, yy)], fill=(r, g, b))

        # 상단 충격 라벨
        draw.text((W // 2, 90), "TODAY TSLA",
                  font=f_brand, fill=accent, anchor="mt",
                  stroke_width=2, stroke_fill=STROKE)

        # 거대한 % 숫자
        tcp = summary.get("today_change_pct")
        if tcp is not None:
            pct_str = f"{'+' if tcp >= 0 else ''}{tcp}%"
            pct_color = GREEN if tcp >= 0 else RED
        else:
            pct_str = "TSLA"
            pct_color = accent
        draw.text((W // 2, 350), pct_str,
                  font=f_huge, fill=pct_color, anchor="mm",
                  stroke_width=6, stroke_fill=STROKE)

        # 오늘 주가
        price = summary.get("today_price") or summary.get("latest_price")
        if price:
            try:
                draw.text((W // 2, 540), f"${float(price):,.2f}",
                          font=f_huge_sub, fill=KEY, anchor="mm",
                          stroke_width=2, stroke_fill=STROKE)
            except (ValueError, TypeError):
                pass

        # 충격 멘트 카드 (대본 줄 1, 2 표시)
        IMPACT_Y = 700
        IMPACT_H = 380
        draw.rounded_rectangle([PAD, IMPACT_Y, W - PAD, IMPACT_Y + IMPACT_H],
                               radius=20, fill=(15, 25, 45), outline=accent, width=3)

        # 대본 줄 1 (헤드라인)
        if len(news_lines) >= 1:
            hl_wrapped = wrap_text(draw, strip_emoji(news_lines[0]), f_lg, W - PAD * 2 - 50)
            ky = IMPACT_Y + 50
            for wl in hl_wrapped[:2]:
                bb = draw.textbbox((0, 0), wl, font=f_lg)
                draw.text(((W - (bb[2] - bb[0])) // 2, ky), wl,
                          font=f_lg, fill=accent, anchor="lt",
                          stroke_width=2, stroke_fill=STROKE)
                ky += 56

        # 구분선
        draw.line([(PAD + 60, IMPACT_Y + 180), (W - PAD - 60, IMPACT_Y + 180)],
                  fill=accent, width=2)

        # 대본 줄 2 (충격 사건)
        if len(news_lines) >= 2:
            ev_wrapped = wrap_text(draw, strip_emoji(news_lines[1]), f_md, W - PAD * 2 - 50)
            ky = IMPACT_Y + 220
            for wl in ev_wrapped[:3]:
                bb = draw.textbbox((0, 0), wl, font=f_md)
                draw.text(((W - (bb[2] - bb[0])) // 2, ky), wl,
                          font=f_md, fill=WHITE, anchor="lt",
                          stroke_width=1, stroke_fill=STROKE)
                ky += 44

        # 검색량 트렌드 칩 (있을 때만)
        trends = summary.get("trends")
        if trends and trends.get("ratio") and trends["ratio"] >= 1.3:
            chip_y = IMPACT_Y + IMPACT_H + 40
            chip_text = f"🔥 검색량 {trends['ratio']}배 폭발!"
            cb = draw.textbbox((0, 0), chip_text, font=f_lg)
            cw = cb[2] - cb[0]
            chip_x = (W - cw) // 2 - 30
            draw.rounded_rectangle([chip_x, chip_y, chip_x + cw + 60, chip_y + 80],
                                   radius=40, fill=(80, 20, 20), outline=RED, width=3)
            draw.text((W // 2, chip_y + 40), chip_text,
                      font=f_lg, fill=KEY, anchor="mm",
                      stroke_width=2, stroke_fill=STROKE)

        return img

    # ╔══════════════════════════════════════════════════════════════════╗
    # ║ 씬 4 — 다음주 예고 + 구독 CTA (custom layout)                     ║
    # ╚══════════════════════════════════════════════════════════════════╝
    if idx == 4:
        # 전체 배경: 검정 → 마젠타 그라데이션
        for yy in range(H):
            t = yy / H
            draw.line([(0, yy), (W, yy)], fill=(
                int(15 + 50 * t), int(0 + 15 * t), int(28 + 68 * t)
            ))

        # ── 헤더 ──────────────────────────────────────────────────────
        draw.text((W // 2, 80), "다음주 예고",
                  font=f_huge_sub, fill=WHITE, anchor="mt",
                  stroke_width=3, stroke_fill=STROKE)
        draw.line([(W // 2 - 200, 162), (W // 2 + 200, 162)],
                  fill=accent, width=4)

        # ── 일정 카드 리스트 (최대 3개) ────────────────────────────────
        next_events = summary.get("next_events", []) or []
        CARD_H = 168
        CARD_GAP = 16
        EV_START = 195

        if next_events:
            for i, ev in enumerate(next_events[:3]):
                cy = EV_START + i * (CARD_H + CARD_GAP)
                imp = ev.get("importance", "medium")
                imp_col = RED if imp == "high" else AMBER if imp == "medium" else GRAY
                date_s = ev.get("date", "")
                title_s = strip_emoji(ev.get("title", "")[:40])

                # 카드 배경
                draw.rounded_rectangle([PAD, cy, W - PAD, cy + CARD_H],
                                       radius=16, fill=(20, 12, 34),
                                       outline=imp_col, width=2)
                # 왼쪽 강조 바
                draw.rounded_rectangle([PAD, cy, PAD + 8, cy + CARD_H],
                                       radius=8, fill=imp_col)
                # 중요도 배지
                imp_txt = "HIGH" if imp == "high" else "MED" if imp == "medium" else "LOW"
                bw = 80
                draw.rounded_rectangle([PAD + 20, cy + 14, PAD + 20 + bw, cy + 50],
                                       radius=10, fill=imp_col)
                draw.text((PAD + 20 + bw // 2, cy + 32), imp_txt,
                          font=f_sm, fill=WHITE, anchor="mm")
                # 날짜
                draw.text((W - PAD - 16, cy + 32), date_s,
                          font=f_sm, fill=KEY, anchor="rm")
                # 이벤트 제목
                tw = wrap_text(draw, title_s, f_md, W - PAD * 2 - 36)
                ty = cy + 62
                for wl in tw[:2]:
                    draw.text((PAD + 20, ty), wl,
                              font=f_md, fill=WHITE, anchor="lt",
                              stroke_width=1, stroke_fill=STROKE)
                    ty += 48
        else:
            # 폴백: 대본 텍스트 한 장
            draw.rounded_rectangle([PAD, EV_START, W - PAD, EV_START + CARD_H],
                                   radius=16, fill=(20, 12, 34), outline=accent, width=2)
            line1 = strip_emoji(news_lines[0] if news_lines else "다음주도 TSLA 주목!")
            wrapped = wrap_text(draw, line1, f_lg, W - PAD * 2 - 40)
            ky = EV_START + (CARD_H - 60 * len(wrapped[:2])) // 2
            for wl in wrapped[:2]:
                bb = draw.textbbox((0, 0), wl, font=f_lg)
                draw.text(((W - (bb[2] - bb[0])) // 2, ky), wl,
                          font=f_lg, fill=WHITE, anchor="lt",
                          stroke_width=2, stroke_fill=STROKE)
                ky += 65

        # ── CTA: 구독 / 알림 투버튼 ────────────────────────────────────
        n_ev_shown = max(1, min(len(next_events), 3))
        CTA_TOP = EV_START + n_ev_shown * (CARD_H + CARD_GAP) + 40

        # 태그라인
        draw.text((W // 2, CTA_TOP), "매주 TSLA 주간 분석 · 무료 알림",
                  font=f_sm, fill=(170, 145, 200), anchor="mt")

        BTN_Y = CTA_TOP + 70
        BTN_H  = 200
        BTN_W  = (W - PAD * 2 - 24) // 2

        # [구독] 버튼 — YouTube 레드 그라데이션
        for yy in range(BTN_Y, BTN_Y + BTN_H):
            t = (yy - BTN_Y) / BTN_H
            draw.line([(PAD, yy), (PAD + BTN_W, yy)],
                      fill=(int(210 - 25 * t), int(18 + 18 * t), int(18 + 28 * t)))
        draw.rounded_rectangle([PAD, BTN_Y, PAD + BTN_W, BTN_Y + BTN_H],
                               radius=22, outline=WHITE, width=4)
        draw.text((PAD + BTN_W // 2, BTN_Y + BTN_H // 2 - 16), "구독",
                  font=f_huge_sub, fill=WHITE, anchor="mm",
                  stroke_width=3, stroke_fill=STROKE)
        draw.text((PAD + BTN_W // 2, BTN_Y + BTN_H - 32), "YouTube",
                  font=f_sm, fill=(255, 205, 205), anchor="mm")

        # [알림 ON] 버튼 — 다크 + 마젠타 테두리
        bx = PAD + BTN_W + 24
        for yy in range(BTN_Y, BTN_Y + BTN_H):
            t = (yy - BTN_Y) / BTN_H
            draw.line([(bx, yy), (bx + BTN_W, yy)],
                      fill=(int(28 + 12 * t), int(12 + 10 * t), int(48 + 22 * t)))
        draw.rounded_rectangle([bx, BTN_Y, bx + BTN_W, BTN_Y + BTN_H],
                               radius=22, outline=accent, width=4)
        draw_bell_icon(draw, bx + BTN_W // 2, BTN_Y + BTN_H // 2 - 30, 32, accent)
        draw.text((bx + BTN_W // 2, BTN_Y + BTN_H // 2 + 30), "알림 ON",
                  font=f_huge_sub, fill=accent, anchor="mm",
                  stroke_width=3, stroke_fill=STROKE)
        draw.text((bx + BTN_W // 2, BTN_Y + BTN_H - 32), "알림 설정",
                  font=f_sm, fill=(210, 170, 230), anchor="mm")

        # 하단 매수지수 범례
        draw = ImageDraw.Draw(img)
        avg_bi = summary.get("avg_buy_index") if summary else None
        draw_bi_legend(draw, avg_bi, f_sm, f_md)
        return img

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
        top_bull = (summary.get("top_bullish") or [{}])[0]
        ch, _, _ = parse_news_line(news_lines[0]) if news_lines else ("", "", "")
        cat = top_bull.get("category", "") or ch
        head_sub = cat if cat else "심층 분석"
    elif idx == 3:
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

    # ── 씬 1: 주간 브리핑 — 본문 영역 ───────────────────────────────────────
    CONTENT_Y = START_Y + 40   # 사진 하단과 본문 사이 40px 여백
    if idx == 1:
        FC_W = COL_W - PAD

        # 핵심 인사이트 카드 (두 번째 줄: 주가·참고지수)
        INSIGHT_H = 150
        draw.rounded_rectangle([PAD, CONTENT_Y, PAD + FC_W, CONTENT_Y + INSIGHT_H],
                               radius=14, fill=(20, 24, 34), outline=accent, width=2)
        if len(news_lines) >= 2:
            insight_wrapped = wrap_text(draw, strip_emoji(news_lines[1]), f_md, FC_W - 44)
            total_h = len(insight_wrapped[:2]) * 44
            ky = CONTENT_Y + (INSIGHT_H - total_h) // 2
            for wl in insight_wrapped[:2]:
                bb = draw.textbbox((0, 0), wl, font=f_md)
                draw.text(((W - (bb[2] - bb[0])) // 2, ky), wl,
                          font=f_md, fill=WHITE, stroke_width=1, stroke_fill=STROKE)
                ky += 44

        # 호재·악재 요약 스트립 (3번째/4번째 줄)
        BULL_Y = CONTENT_Y + INSIGHT_H + 16
        BULL_H = 130
        HALF_W = (FC_W - 12) // 2
        bull_text = strip_emoji(news_lines[2]) if len(news_lines) >= 3 else ""
        bear_text = strip_emoji(news_lines[3]) if len(news_lines) >= 4 else ""

        if bull_text:
            draw.rounded_rectangle([PAD, BULL_Y, PAD + HALF_W, BULL_Y + BULL_H],
                                   radius=12, fill=(16, 32, 20), outline=GREEN, width=2)
            draw.text((PAD + 12, BULL_Y + 14), "▲ 호재", font=f_sm, fill=GREEN)
            bw = wrap_text(draw, bull_text, f_xs, HALF_W - 24)
            by = BULL_Y + 44
            for wl in bw[:2]:
                draw.text((PAD + 12, by), wl, font=f_xs, fill=WHITE,
                          stroke_width=1, stroke_fill=STROKE)
                by += 32

        if bear_text:
            bx = PAD + HALF_W + 12
            draw.rounded_rectangle([bx, BULL_Y, bx + HALF_W, BULL_Y + BULL_H],
                                   radius=12, fill=(32, 14, 14), outline=RED, width=2)
            draw.text((bx + 12, BULL_Y + 14), "▼ 악재", font=f_sm, fill=RED)
            rw = wrap_text(draw, bear_text, f_xs, HALF_W - 24)
            ry = BULL_Y + 44
            for wl in rw[:2]:
                draw.text((bx + 12, ry), wl, font=f_xs, fill=WHITE,
                          stroke_width=1, stroke_fill=STROKE)
                ry += 32

        # 가격 스트립
        STRIP_Y = BULL_Y + BULL_H + 20
        BOX_Y   = STRIP_Y + 36
        BOX_H   = SAFE_BOTTOM - BOX_Y - 10
        draw.text((PAD, STRIP_Y + 18), "주간 주가 흐름 ($)",
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

    # ── 씬 2: 호재 심층 — 풀사이즈 히어로 카드 1장 ─────────────────────────
    elif idx == 2:
        CARD_W = COL_W - PAD
        CARD_H = SAFE_BOTTOM - CONTENT_Y
        headline = news_lines[0] if news_lines else f"{COMPANY_KO} 주요 호재"
        details  = [l.lstrip("↳ ").strip() for l in news_lines[1:4]]
        top_bull = (summary.get("top_bullish") or [{}])[0]
        bull_score  = top_bull.get("score", 5)
        bull_source = top_bull.get("source", "")
        bull_date   = top_bull.get("date", "")
        _, headline_content, _ = parse_news_line(headline)
        draw_bullish_hero_card(
            draw, img,
            x=PAD, y=CONTENT_Y, w=CARD_W, h=CARD_H,
            headline=headline_content or headline,
            details=details,
            score=bull_score, source=bull_source, date=bull_date,
            accent=accent,
            fnt_bold=f_ch, fnt_content=f_ct, fnt_source=f_src,
            fnt_content_xl=f_ct_xl, fnt_content_sm=f_ct_sm,
        )
        draw = ImageDraw.Draw(img)

    # ── 씬 3: 시장 반응 — 최대 4개 항목 ─────────────────────────────────────
    elif idx == 3:
        n_items = min(len(news_lines), 4) if news_lines else 2
        n_items = max(n_items, 1)
        GAP    = 18
        ITEM_H = (SAFE_BOTTOM - CONTENT_Y - GAP * (n_items - 1)) // n_items
        item_positions = [CONTENT_Y + i * (ITEM_H + GAP) for i in range(n_items)]
        default_labels = ["분위기", "거래량", "애널리스트", "전망"]

        for i, line in enumerate(news_lines[:n_items]):
            iy = item_positions[i]
            draw.rounded_rectangle([PAD, iy, PAD + COL_W - PAD, iy + ITEM_H],
                                   radius=10, fill=(16, 19, 27), outline=accent, width=2)
            LAB_W = 148
            draw.rounded_rectangle([PAD, iy, PAD + LAB_W, iy + ITEM_H],
                                   radius=10, fill=accent)
            draw.rectangle([PAD + LAB_W - 10, iy, PAD + LAB_W, iy + ITEM_H], fill=accent)

            # 라벨: [분위기] 등 bracket content 추출, 없으면 기본값
            label_txt = default_labels[i] if i < len(default_labels) else ""
            if line.startswith("[") and "]" in line:
                label_txt = line[1:line.index("]")]
            label_font = f_sm if len(label_txt) > 4 else f_ch
            draw.text((PAD + LAB_W // 2, iy + ITEM_H // 2),
                      label_txt, font=label_font, fill=(10, 12, 20), anchor="mm")

            content_text = line
            if line.startswith("[") and "]" in line:
                content_text = line[line.index("]") + 1:].strip()

            content_font = f_nm if n_items >= 4 else f_ct
            content_x    = PAD + LAB_W + 18
            content_maxw = COL_W - PAD - LAB_W - 36
            wrapped = wrap_text(draw, strip_emoji(content_text), content_font, content_maxw)
            bb_h = draw.textbbox((0, 0), "가", font=content_font)
            lh = (bb_h[3] - bb_h[1]) + 12
            total_h = len(wrapped[:3]) * lh
            start_y = iy + (ITEM_H - total_h) // 2
            for wl in wrapped[:3]:
                if start_y + lh > iy + ITEM_H - 8:
                    break
                draw.text((content_x, start_y), wl, font=content_font, fill=WHITE,
                          stroke_width=1, stroke_fill=STROKE)
                start_y += lh

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
        static_bg  = SCENE_STATIC_BG[idx] if idx < len(SCENE_STATIC_BG) else None
        articles   = SCENE_WIKI_ARTICLES[idx] if idx < len(SCENE_WIKI_ARTICLES) else ["Tesla, Inc."]
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
    KST = timezone(timedelta(hours=9))
    today   = datetime.now(KST).strftime("%Y-%m-%d")   # KST 기준 날짜
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
    if summary.get("today_change_pct") is not None:
        print(f"   오늘 변동: {summary['today_change_pct']:+.2f}%")

    # ── Google Trends 수집 ──
    print("📈 Google Trends 수집 중...")
    summary["trends"] = fetch_google_trends(GOOGLE_TRENDS_KEYWORDS)
    if summary["trends"]:
        print(f"   검색량 {summary['trends']['ratio']}배 변화 (최고: {summary['trends']['top_keyword']})")

    # ── Calendar 이벤트 ──
    summary["next_events"] = load_next_events()
    if summary["next_events"]:
        print(f"   다음주 이벤트 {len(summary['next_events'])}건 발견")

    # ── 대본 ──
    if not ANTHROPIC_API_KEY and not GEMINI_API_KEY:
        print("⚠ API 키 없음 — 대본 생성 건너뜀", file=sys.stderr)
        scenes = [{"index": i, "title": f"씬 {i}", "lines": [], "body": ""} for i in range(0, 5)]
    else:
        print("✍ 대본 생성 중...")
        raw    = generate_script(summary)
        scenes = parse_script(raw)
        img_prompts = parse_image_prompts(raw)

        # 대시보드용 title/subtitle — 씬1 첫 줄에서 추출
        script_title = ""
        script_subtitle = f"{summary['week_start']} ~ {summary['week_end']}"
        scene1 = next((s for s in scenes if s["index"] == 1), None)
        if scene1 and scene1.get("lines"):
            first_line = scene1["lines"][0] if scene1["lines"] else ""
            script_title = strip_emoji(first_line).strip('"').strip("'").strip()
        if summary.get("biggest_impact"):
            bi_title = summary["biggest_impact"].get("title", "")
            if bi_title:
                script_subtitle += f" · {bi_title[:30]}"

        with open(out_dir / "script.txt", "w", encoding="utf-8") as f:
            f.write(raw)
        with open(out_dir / "script.json", "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": today,
                "generated_by": _last_model,
                "title": script_title,
                "subtitle": script_subtitle,
                "summary": summary,
                "scenes": scenes,
                "image_prompts": img_prompts,
            }, f, ensure_ascii=False, indent=2)

        # ── 이미지 프롬프트 별도 저장 (Imagen 복붙용) ──
        if img_prompts:
            lines = [f"# {TICKER} 주간 배경 이미지 프롬프트 — {today}",
                     "# Gemini Imagen에 씬별로 붙여넣기 하세요.\n"]
            scene_names = {0: "씬0 충격인트로", 1: "씬1 주간브리핑",
                           2: "씬2 호재심층", 3: "씬3 시장반응",
                           4: "씬4 다음주예고"}
            for i in range(0, 5):
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
            "today_change_pct": summary.get("today_change_pct"),
            "trends":          summary.get("trends"),
        }, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 완료: data/weekly-report/{today}/")
    print(f"   📄 script.txt  — 영상 대본 (5씬, 인트로+클로징 포함)")
    print(f"   🖼 scene_00~04.png — 씬별 배경 카드 이미지 (1080×1920, YouTube Shorts 세로 포맷)")


if __name__ == "__main__":
    main()
