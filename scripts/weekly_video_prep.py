"""
주간 영상 자료 생성 스크립트
- 최근 7일 auto-sessions.json 데이터 기반
- Gemini API → 한국어 영상 대본(4 씬)
- Pillow → 씬별 1080×1920 카드 이미지 (YouTube Shorts 세로 포맷)
- 저장: data/weekly-report/YYYY-MM-DD/

종목 설정: config/ticker.json
"""

import os, json, sys, re, random, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT_DIR          = Path(__file__).parent.parent
TICKER_CONFIG     = json.loads((ROOT_DIR / "config" / "ticker.json").read_text(encoding="utf-8"))
TICKER            = TICKER_CONFIG["ticker"]
COMPANY_KO        = TICKER_CONFIG["company_ko"]
INDUSTRY_KO       = TICKER_CONFIG.get("industry_ko", "")
FUTURE_TECH_EN    = TICKER_CONFIG.get("image_future_tech_en", "")
BRAND_LABEL       = TICKER_CONFIG["brand_label"]
REPO              = TICKER_CONFIG["repo"]

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
AUTO_SESSIONS     = ROOT_DIR / "data" / "auto-sessions.json"
OUTPUT_BASE       = ROOT_DIR / "data" / "weekly-report"
LOOKBACK_DAYS     = 7

# ── 팔레트 ────────────────────────────────────────────────────────────────
BG      = (24, 32, 54)         # 14,17,23 → 밝은 미드나이트 네이비
WHITE   = (255, 255, 255)
GRAY    = (120, 128, 148)
LGRAY   = (185, 192, 210)      # 더 밝은 회색
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
STROKE  = (8, 12, 30)          # 0,0,0 → 부드러운 다크 네이비 (과한 검정 윤곽 완화)

HEADER_H    = 500
PHOTO_Y     = HEADER_H
PHOTO_H     = 500
BODY_Y      = PHOTO_Y + PHOTO_H
START_Y     = BODY_Y
NAVY        = (30, 60, 115)    # 15,32,70 → 밝은 네이비 블루
NAVY_DEEP   = (22, 45, 92)     # 10,22,50 → 밝은 딥 네이비
CYAN_LIGHT  = (160, 235, 255)  # 더 밝게

# ── 카드 배경색 (씬별 톤) ──────────────────────────────────────────────────
CARD_BG     = (36, 46, 78)     # 중립 카드 (was ~14-20 range)
CARD_GREEN  = (22, 58, 36)     # 초록 카드
CARD_RED    = (58, 24, 24)     # 빨강 카드
CARD_AMBER  = (58, 46, 16)     # 앰버 카드
CARD_PURPLE = (42, 20, 78)     # 보라 카드
BADGE_BG    = (20, 26, 48)     # 배지·푸터 배경

SCENE_ACCENTS = [PURPLE, GREEN, (236, 72, 153)]  # 브리핑/호재/미래비전 (인트로·시장반응 제거)

# ── 양산형 탈피: 영상마다 변형 (생성일 시드로 결정 → 격일 생성 시 매번 달라짐) ──
# 인트로/클로징(썸네일) 색상 테마 2~3종 로테이션. 씬1(호재)은 의미상 항상 초록 유지.
ACCENT_THEMES = [
    [(167, 139, 250), GREEN, (236, 72, 153)],  # A 보라·초록·마젠타 (기존)
    [(56, 189, 248),  GREEN, (251, 146, 60)],  # B 시안·초록·오렌지
    [(129, 140, 248), GREEN, (250, 204, 21)],  # C 인디고·초록·골드
]

def _theme_idx(date_str):
    """생성일 문자열로 결정적 테마 인덱스 (prep·make 동일 함수 → 색상 동기화)."""
    return sum(ord(c) for c in (date_str or "")) % len(ACCENT_THEMES)

# 오프닝 훅 스타일 풀 — 매 영상 다른 첫 줄로 '오늘의 뉴스' 식 고정 오프닝 탈피.
HOOK_STYLES = [
    "질문형 — 시청자에게 질문을 던지며 시작 (예: '이번주 OO, 무슨 일이 있었을까요?')",
    "충격 수치형 — 이번주 가장 큰 등락률·수치를 앞세워 강하게 시작",
    "역발상형 — 통념을 뒤집는 한마디로 시작 (예: '다들 걱정했지만, 의외로…')",
    "결론 선공개형 — 핵심 결론을 먼저 던지고 근거로 이어가기",
    "스토리·장면형 — 한 장면을 묘사하듯 몰입감 있게 시작",
    "비교형 — 경쟁사·지난주 대비로 대조를 주며 시작",
    "호기심 유발형 — '왜 갑자기?' 식으로 궁금증을 자극하며 시작",
    "임팩트형 — 이번주 최대 이슈 한 방으로 훅을 걸며 시작",
]

def pick_hook(seed):
    return random.Random(str(seed)).choice(HOOK_STYLES)

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

    # 최신 뉴스가 같은 점수라면 우선 노출 (recency 가중치)
    def _bull_sort_key(n):
        score = n.get("score", 0)
        try:
            from datetime import datetime as _dt2
            days_ago = (_dt2.now() - _dt2.strptime(n.get("date", "")[:10], "%Y-%m-%d")).days
            recency  = max(0.0, (14 - days_ago) / 28.0)  # 2주 이내 최대 +0.5
        except Exception:
            recency = 0.0
        return score + recency

    bullish.sort(key=_bull_sort_key, reverse=True)
    bearish.sort(key=lambda x: x["score"])

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

    # ── 주간 브리핑용: 1주 전 대비 변동률 ──
    week_change_pct = None
    try:
        p_start = float(prices[-1]) if prices else None
        p_end   = float(prices[0]) if prices else None
        if p_start and p_end and p_start > 0:
            week_change_pct = round((p_end - p_start) / p_start * 100, 2)
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
        "week_change_pct": week_change_pct,
        "biggest_impact":  biggest_impact,
        "top_bullish":     bullish[:3],
        "top_bearish":     bearish[:3],
        "forecasts":       latest.get("dailyForecasts", [])[:5],
        "daily_prices":    daily_prices,
        "overall_signal":  overall_signal,
        "trends":          None,        # fetch_google_trends()로 채움
        "next_events":     [],          # load_next_events()로 채움
    }


def search_movement_reason(summary):
    """Gemini + Google Search grounding으로 이번주 주가 변동 원인 검색."""
    if not GEMINI_API_KEY:
        return None
    try:
        from google import genai
        from google.genai import types
        tcp  = summary.get("today_change_pct")
        sign = "+" if tcp and tcp >= 0 else ""
        direction = "상승" if tcp and tcp >= 0 else "하락"
        week_start = summary.get("week_start", "")
        week_end   = summary.get("week_end", "")
        price      = summary.get("latest_price", "")
        q = (
            f"테슬라 TSLA 주가 {week_start}~{week_end} 기간 {direction} 주요 원인 분석. "
            f"현재 주가 ${price}, 변동률 {sign}{tcp}%. "
            f"검색 결과를 바탕으로 핵심 원인 2~3가지를 각 15자 이내 한국어로 작성. "
            f"형식: '원인1 / 원인2 / 원인3'"
        )
        client   = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=q,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
        text = response.text.strip()
        print(f"   🔍 주가 변동 원인: {text[:80]}")
        return text
    except Exception as e:
        print(f"   ⚠ 주가 변동 원인 검색 실패: {e}", file=sys.stderr)
        return None


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


def build_next_week_outlook(forecasts):
    """dailyForecasts(일별 가격 예측)를 '다음주 전망' 한 단락으로 요약.

    YouTube 정책상 매수/매도 같은 신호 단어는 제외하고
    가격·변동률 추세만 참고용으로 정리한다.
    change_pct는 '현재가 대비' 누적 예측치(일별 증감 아님).
    """
    if not forecasts:
        return "예측 데이터 없음 — 다음주 일정·이벤트 중심으로 전망"

    def _pct(f):
        try:
            return float(f.get("change_pct"))
        except (TypeError, ValueError):
            return 0.0

    up   = sum(1 for f in forecasts if _pct(f) > 0)
    down = sum(1 for f in forecasts if _pct(f) < 0)

    cum = end = None
    try:
        base = float(forecasts[0].get("basePrice"))
        end  = float(forecasts[-1].get("predictedPrice"))
        if base > 0:
            cum = round((end - base) / base * 100, 1)
    except (TypeError, ValueError, AttributeError):
        pass

    parts = []
    if cum is not None:
        sign = "+" if cum >= 0 else ""
        parts.append(f"다음 주말 예상 변동률 {sign}{cum}% (현재가 대비)")
    if end:
        parts.append(f"예상 도달가 약 ${end:,.0f}")
    parts.append(f"현재가보다 높게 예측된 날 {up}일 / 낮은 날 {down}일")

    daily = " → ".join(
        f"{f.get('label') or f.get('date','')} ${float(f.get('predictedPrice')):,.0f}"
        for f in forecasts if f.get("predictedPrice")
    )
    if daily:
        return "; ".join(parts) + f"\n  일별 예측가: {daily}"
    return "; ".join(parts)

# ── 대본 생성 ─────────────────────────────────────────────────────────────

SCRIPT_PROMPT_TEMPLATE = """아래 {ticker} 주간 데이터를 바탕으로 YouTube Shorts 나레이션 대본을 작성해줘.
**친근한 사람이 옆에서 다정하게 이야기해 주는 톤**으로, 구독자에게 말 걸듯 따뜻하고 자연스러운 구어체로 작성한다.

=== 톤 가이드 (반드시 준수) ===
• 친근한 구어체 어미 사용: "~예요", "~네요", "~더라고요", "~거든요", "~답니다", "~죠", "~봐요", "~해요"
• 다정하게 말 걸기: "여러분", "같이 볼까요?", "~한 점이 눈에 띄네요", "흥미롭죠?" 처럼 대화하듯 자연스럽게
• 딱딱한 분석체 어미 금지: "~로 분석된다", "~로 관측된다", "~할 전망이다", "~로 풀이된다" 같은 보고서 말투는 쓰지 않는다 — 사람이 말하듯 풀어 쓴다
• 과한 클릭베이트 추임새는 지양(충격!·헐!·대박!·소름! 금지)하되, 부드럽고 자연스러운 반응은 환영("좋은 소식이에요", "조금 아쉬운 부분이죠", "눈여겨볼 만해요")
• 단정적 권유 금지 (매수·매도·관망 직접 언급 금지)
• **내부 점수(+N점·-N점) 절대 표기 금지** — 시청자용 지표가 아니다. "좋은 소식"·"호재" / "걱정되는 부분"·"리스크"처럼 풀어 말하고, 점수 대신 구체적 수치·배경·맥락으로 왜 그런지 설명한다.
• 수치·근거는 그대로 살린다: 모든 핵심 줄에 %·$·대수 등 구체 수치를 자연스럽게 녹여 넣는다
• 씬 0: 4줄 / 씬 1: 6줄 / 씬 2: 4줄 (한 줄 30자 이내 권장)

=== 핵심 강조 표시 (반드시 준수) ===
• 각 줄에서 가장 중요한 핵심 글귀(수치·키워드) 1개를 *별표*로 감싼다. 예시: 이번 주 테슬라가 *12% 급등*했어요
• 한 줄에 강조는 최대 1~2개만. 문장 전체를 감싸지 말고 핵심 수치/단어만 감싼다
• 별표로 감싼 부분은 화면에서 강조색(골드)으로 표시되니, 정말 눈에 띄어야 할 수치·키워드에만 사용한다

=== 오프닝 훅 & 차별화 (반드시 준수) ===
• 오프닝(SCENE_0_TITLE·씬0 줄1)은 매 영상 달라야 한다. 이번 영상 오프닝 훅 스타일 → {hook_style}
  ※ "오늘의 뉴스"·"이번주 뉴스 N건 분석했어요" 같은 고정·상투적 오프닝 금지(분석 규모는 뒷줄에 자연스럽게 녹여도 됨).
• 차별화 관점 1줄(필수): 단순 뉴스 요약·낭독을 넘어, 시장 컨센서스·통념과 다른 분석가만의 시각을 한 줄 넣는다
  (예: "시장은 X를 우려하지만, 정작 중요한 건 Y예요"). 씬1 '향후 전망' 또는 씬2에 자연스럽게 배치.

=== 주간 데이터 ({week_start} ~ {week_end}) ===
- {ticker} 현재 주가: ${price}
- 1주 전 대비 변동률: {week_change_pct_str}
- 주가 변동 원인: {movement_reason_str}
- 검색량 트렌드: {trends_str}
- 다음주 예정 이벤트: {next_events_str}
- 다음주 가격 예측(AI 모델, 참고용·매매신호 아님): {next_week_str}
{daily_prices_txt}
- 주요 호재 (점수 표기 금지, 내용만 활용):
{b_txt}
- 주요 리스크 (점수 표기 금지, 내용만 활용):
{r_txt}

=== 씬 구성 (총 3씬) ===

【씬 0 — 주간 브리핑】 (4줄, 한 줄 30자 이내, 핵심 정보만 응축)
- 줄1: 위 '오프닝 훅 스타일'로 시작하는 강렬한 첫 줄 — 변동률·현재 주가 등 핵심 수치를 자연스럽게 녹인다 (30자 이내, 수치 필수). 고정·상투 멘트 금지
- 줄2: 주가 변동 원인 핵심 한 줄 (movement_reason 활용, 30자 이내, 수치 포함)
- 줄3: 이번주 가장 큰 호재 핵심 한 줄 (30자 이내, 수치 포함, 점수 금지)
- 줄4: 이번주 가장 큰 리스크 한 줄 (30자 이내, 수치 포함, 점수 금지)

【씬 1 — 호재 심층 분석 (BEST 1건)】 (6줄, 한 줄 30자 이내, 모든 줄에 수치 필수)
- 줄1: "카테고리: 호재 핵심 (25자 이내)"
- 줄2: "   ↳ 배경: 사건 배경·맥락 (30자 이내, 수치)"
- 줄3: "   ↳ 데이터: 수치·실적 (30자 이내, %·$·대수 의무)"
- 줄4: "   ↳ 임팩트: 주가·시장 반응 (30자 이내, 수치)"
- 줄5: "   ↳ 비교: 경쟁사·과거 대비 (30자 이내, 수치)"
- 줄6: "   ↳ 향후 전망 (30자 이내, 단정적 권유 금지)"

【씬 2 — 다음주 전망 (클로징)】 (6줄, 구어체, 다음주 예측 중심·수치 의무)
※ 이 씬은 한 주를 마무리하며 "다음주에 무슨 일이 있고, 어떻게 움직일지" 예측하는 마지막 씬이다.
- 줄1: 다음주 핵심 일정·이벤트 1건 — next_events 활용 (실적·규제 결정·신제품 등, 25자 이내)
- 줄2: → 그 이벤트로 예상되는 시나리오·관전 포인트 (25자 이내, 가능하면 수치)
- 줄3: 다음주 가격 흐름 예측 요약 — 누적 예측 변동률·예상 도달가 활용 (25자 이내, 수치 필수, 단정 금지·"~예상돼요"·"~흐름이 점쳐져요" 톤)
- 줄4: → 상승/하락 예측 일수 등 흐름 부연 — "며칠은 오르고 며칠은…" 식 (25자 이내, 수치)
- 줄5: 신중하게 봐야 할 변수 1건 — 예측을 흔들 수 있는 리스크 (25자 이내)
- 줄6: 따뜻한 마무리 인사 한 문장 — 날짜·요일에 무관하게 언제든 자연스럽게 쓸 수 있는 표현 ("다음에 또 만나요", "또 봐요!", "함께해 주셔서 감사해요" 등, "다음 주" 표현 금지, 20자 이내)

=== 출력 형식 (반드시 준수) ===
※ 핵심 수치·키워드는 *별표*로 감싸 강조한다 (각 줄 최대 1~2개).
SCENE_0_TITLE: [6자 이내, 친근한 단어 예: "이번주" "한주요약"]
SCENE_0:
[줄1 — 변동률·주가 요약, 핵심 수치 *별표* 강조]
[줄2 — 변동 원인 핵심, 핵심 *별표* 강조]
[줄3 — 최대 호재 핵심, 핵심 *별표* 강조]
[줄4 — 최대 리스크 핵심, 핵심 *별표* 강조]

SCENE_1_TITLE: [6자 이내]
SCENE_1:
카테고리: 호재 핵심 한 줄 (핵심 *별표* 강조)
   ↳ 배경: 사건 배경·맥락 수치 (*별표* 강조)
   ↳ 데이터: 수치·실적 의무 (*별표* 강조)
   ↳ 임팩트: 주가·시장 반응 수치 (*별표* 강조)
   ↳ 비교: 경쟁사·과거 대비 (*별표* 강조)
   ↳ 향후 전망 한 문장

SCENE_2_TITLE: [6자 이내, "다음주" "전망" 같은 단어]
SCENE_2:
[줄1 — 다음주 핵심 일정·이벤트, 핵심 *별표* 강조]
[줄2 — → 예상 시나리오·관전 포인트, *별표* 강조]
[줄3 — 다음주 가격 흐름 예측 요약, 누적 변동률·도달가 *별표* 강조]
[줄4 — → 상승/하락 예측 흐름 부연, 수치 *별표* 강조]
[줄5 — 신중히 볼 변수 1건]
[줄6 — 따뜻한 마무리 인사]

=== 배경 이미지 프롬프트 (Gemini Imagen용, 영어, 3개) ===
각 60단어 이상. 반드시 포함: "no text, no letters, no watermark, no logo", "ultra-high resolution".
{company_ko}·{industry_ko} 관련 시각 요소 포함. 씬별 색감 지정.
★ 각 이미지에 {company_ko}의 미래 기술·사업계획을 시각적으로 반영하라(핵심 제품/로드맵): {future_tech}.
※ 씬 0·1은 16:9 landscape (horizontal strip), 씬 2는 9:16 vertical (full screen) — 프롬프트에 비율 명시.

IMAGE_PROMPT_0: [씬0 — 16:9 landscape · 서울 한강 야경 배경 테슬라 자율주행 전기차, {future_tech}, 남산타워·63빌딩·롯데타워 도심 스카이라인, K-tech 첨단 도시 보라빛 미래적 분석 분위기, Korean futuristic city Seoul skyline Tesla purple violet tech analytics, glowing city lights bokeh, ultra-high resolution, 16:9 landscape, no text, no letters, no watermark, no logo]
IMAGE_PROMPT_1: [씬1 — 16:9 landscape · 한강 반포 다리 초록빛 성장 상승 이미지, 서울 테슬라 전기차 충전·고속 주행, {future_tech}, K-tech 친환경 인프라 밝고 활기찬 분위기, Korean city Seoul Tesla green growth bullish energy vibrant, sunlit modern bridge electric vehicle charging, ultra-high resolution, 16:9 landscape, no text, no letters, no watermark, no logo]
IMAGE_PROMPT_2: [씬2 — 9:16 vertical · 한국 미래 도시: 한강 야경·서울 스카이라인·광화문 광장 배경의 자율주행 테슬라 차량·옵티머스 로봇 + 미래 비전({future_tech}), 첨단 K-tech 도시 풍경, 마젠타·골드빛 영감적 미래 무드, 황금빛 태양·별빛·반짝임, ultra-high resolution, 9:16 vertical, no text, no letters, no watermark, no logo]"""


def _build_prompt(summary):
    # 내부 점수([+N])는 시청자용이 아니므로 프롬프트 데이터에서도 노출하지 않는다 (AI 에코 방지).
    b_txt = "\n".join(
        f"  - {n['title']} ({n.get('source','')}·{n.get('date','')}·{n.get('category','')}): {n['reason'][:70]}"
        for n in summary["top_bullish"]
    ) or "  없음"
    r_txt = "\n".join(f"  - {n['title']}: {n['reason'][:70]}" for n in summary["top_bearish"]) or "  없음"

    daily_prices = summary.get("daily_prices", [])
    if daily_prices:
        dp_lines = "\n".join(f"  {d}: ${p:,.2f}" for d, p in daily_prices)
        daily_prices_txt = f"- 최근 주가 흐름:\n{dp_lines}"
    else:
        daily_prices_txt = ""

    # 주간 브리핑용 변동률 문자열 (1주 전 대비)
    wcp = summary.get("week_change_pct")
    if wcp is not None:
        sign = "+" if wcp >= 0 else ""
        week_change_pct_str = f"{sign}{wcp}% (1주 전 대비)"
    else:
        week_change_pct_str = "변동 데이터 없음"

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

    movement_reason = summary.get("movement_reason")
    movement_reason_str = movement_reason if movement_reason else "데이터 수집 중"

    # 다음주 가격 예측 요약 (dailyForecasts 기반, 매매신호 단어 제외)
    next_week_str = build_next_week_outlook(summary.get("forecasts", []))

    hook_style = pick_hook(summary.get("week_end") or summary.get("week_start") or "")
    return SCRIPT_PROMPT_TEMPLATE.format(
        ticker=TICKER,
        company_ko=COMPANY_KO,
        industry_ko=INDUSTRY_KO,
        future_tech=FUTURE_TECH_EN,
        hook_style=hook_style,
        week_start=summary["week_start"],
        week_end=summary["week_end"],
        price=summary["latest_price"],
        b_txt=b_txt, r_txt=r_txt,
        daily_prices_txt=daily_prices_txt,
        week_change_pct_str=week_change_pct_str,
        movement_reason_str=movement_reason_str,
        trends_str=trends_str,
        next_events_str=next_events_str,
        next_week_str=next_week_str,
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
    SCENE_RANGE = range(0, 3)   # 씬 0(주간브리핑)~씬 2(미래비전) · 인트로·시장반응 씬 제거
    # 본문이 넘어가면 안 되는 경계 마커 (특히 마지막 씬이 이미지 프롬프트/섹션을 흡수하는 것 방지)
    BOUNDARY_MARKERS = ("IMAGE_PROMPT_", "=== 배경", "===")
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
            # 다음 씬 타이틀 또는 이미지 프롬프트/섹션 마커 중 가장 먼저 등장하는 곳에서 끊는다
            nxt = raw.find(f"SCENE_{i+1}_TITLE:", s)
            if nxt == -1:
                nxt = len(raw)
            for marker in BOUNDARY_MARKERS:
                m = raw.find(marker, s)
                if m != -1:
                    nxt = min(nxt, m)
            body = raw[s:nxt].strip()
        lines = [l.strip() for l in body.split("\n")]
        scenes.append({"index": i, "title": title, "lines": lines, "body": body})
    return scenes


def parse_image_prompts(raw):
    """대본에서 씬별 Imagen 프롬프트 추출 → {0: "...", 1: "...", ...}"""
    prompts = {}
    for i in range(0, 3):
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


def find_soft_font():
    """둥근·친근한 폰트(나눔스퀘어라운드) 탐색 — 호재 심층 씬 등 부드러운 톤용.

    설치 안 됐으면 (None, None) 반환 → 호출부에서 기본 폰트로 폴백.
    """
    round_reg = [
        "/usr/share/fonts/truetype/nanum/NanumSquareRoundR.ttf",
        "/usr/share/fonts/truetype/nanum/NanumSquareR.ttf",
    ]
    round_bold = [
        "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf",
        "/usr/share/fonts/truetype/nanum/NanumSquareB.ttf",
    ]
    reg  = next((p for p in round_reg  if os.path.exists(p)), None)
    bold = next((p for p in round_bold if os.path.exists(p)), reg)
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


_NANO_BANANA_MODELS = [
    "gemini-2.5-flash-image",          # Nano Banana  (500/일 무료)
    "gemini-3.1-flash-image-preview",  # Nano Banana 2 (100/일 무료, 폴백)
]

def fetch_nano_banana_image(prompt: str, out_path: Path, aspect_ratio: str = "16:9") -> bool:
    """Nano Banana API로 씬 배경 이미지 생성. 실패 시 False 반환.
    aspect_ratio: '16:9' (씬 1~3 가로 strip) 또는 '9:16' (씬 0·4 풀스크린).
    """
    if not GEMINI_API_KEY or not prompt:
        return False
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        for model_id in _NANO_BANANA_MODELS:
            try:
                response = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                        image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
                    ),
                )
                for part in response.parts:
                    if part.inline_data:
                        out_path.write_bytes(part.inline_data.data)
                        return True
            except Exception as e:
                print(f"      ⚠ {model_id} 실패: {e}", file=sys.stderr)
                continue
    except Exception as e:
        print(f"      ⚠ Nano Banana 초기화 실패: {e}", file=sys.stderr)
    return False


def make_canvas(accent):
    """다크 배경 캔버스 생성 (1080×1920 세로 포맷)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, W, 6], fill=accent)
    draw.rectangle([0, H - 100, W, H], fill=(24, 32, 54))
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
        draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=CARD_BG)
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
        # 블러 배경 오버레이 — 밝게 (170→90)
        bg_ov = PILImage.new("RGBA", (w, h), (8, 10, 16, 90))
        bg = PILImage.alpha_composite(bg.convert("RGBA"), bg_ov).convert("RGB")

        # ── 전경 레이어: contain-fit (프레임 안에 사진 전체 표시) ──
        if img_ratio > target_ratio:
            fg_w = w
            fg_h = int(w / img_ratio)
        else:
            fg_h = h
            fg_w = int(h * img_ratio)
        fg = photo.resize((fg_w, fg_h), PILImage.LANCZOS)
        # 전경 오버레이 최소화 — 사진 밝게 표시 (80→20)
        fg_ov = PILImage.new("RGBA", (fg_w, fg_h), (8, 10, 16, 20))
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
        draw.rounded_rectangle([x, y, x + w, y + h], radius=6, fill=CARD_BG)


def draw_mbc_header(draw, brand: str, title_main: str, title_sub: str, accent,
                     fnt_brand, fnt_main, fnt_sub):
    """리뉴얼 헤더 — 대각선 텍스처 + accent pill 배지 + 상하 accent 바."""
    # ── 배경 그라데이션 ──
    for yy in range(HEADER_H):
        t = yy / HEADER_H
        r = int(NAVY[0] * (1 - t * 0.35) + NAVY_DEEP[0] * (t * 0.35))
        g = int(NAVY[1] * (1 - t * 0.35) + NAVY_DEEP[1] * (t * 0.35))
        b = int(NAVY[2] * (1 - t * 0.35) + NAVY_DEEP[2] * (t * 0.35))
        draw.line([(0, yy), (W, yy)], fill=(r, g, b))

    # ── 대각선 스트라이프 텍스처 ──
    sc = (max(0, NAVY_DEEP[0] - 6), max(0, NAVY_DEEP[1] - 6), min(255, NAVY_DEEP[2] + 8))
    for xx in range(-HEADER_H, W + HEADER_H, 58):
        draw.line([(xx, 0), (xx + HEADER_H, HEADER_H)], fill=sc, width=22)

    # ── 상단 accent 바 ──
    draw.rectangle([0, 0, W, 10], fill=accent)

    # ── 브랜드 배지 — 채워진 pill (accent 배경 + 다크 텍스트) ──
    brand_y = 70
    bb_b = draw.textbbox((0, 0), brand, font=fnt_brand)
    bw = (bb_b[2] - bb_b[0]) + 64
    bx0 = (W - bw) // 2
    draw.rounded_rectangle([bx0, brand_y - 30, bx0 + bw, brand_y + 30],
                           radius=30, fill=accent)
    draw.text((W // 2, brand_y), brand, font=fnt_brand, fill=BG, anchor="mm")

    # 배지 아래 accent 하이라이트 라인
    draw.line([(bx0 + 24, brand_y + 38), (bx0 + bw - 24, brand_y + 38)],
              fill=accent, width=3)

    # ── 메인 헤드라인 ──
    main_y = 148
    main_lines = wrap_text(draw, title_main, fnt_main, W - 80)
    for wl in main_lines[:2]:
        bb = draw.textbbox((0, 0), wl, font=fnt_main)
        tw = bb[2] - bb[0]
        draw.text(((W - tw) // 2, main_y), wl, font=fnt_main, fill=WHITE,
                  stroke_width=3, stroke_fill=STROKE)
        main_y += (bb[3] - bb[1]) + 14

    # ── 서브 타이틀 (accent 색상) ──
    if title_sub:
        sub_y = main_y + 10
        sub_lines = wrap_text(draw, title_sub, fnt_sub, W - 80)
        for wl in sub_lines[:1]:
            bb = draw.textbbox((0, 0), wl, font=fnt_sub)
            tw = bb[2] - bb[0]
            draw.text(((W - tw) // 2, sub_y), wl, font=fnt_sub, fill=accent,
                      stroke_width=2, stroke_fill=STROKE)

    # ── 하단 accent 바 ──
    draw.rectangle([0, HEADER_H - 10, W, HEADER_H], fill=accent)


def draw_buy_index_gauge(draw, cx, cy, r, bi, fnt_big, fnt_small):
    col = GREEN if bi >= 65 else AMBER if bi >= 45 else RED
    # 배경 반원 (회색)
    draw.arc([cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill=(62, 68, 88), width=22)
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
                            fill=CARD_BG, outline=accent, width=2)

    # 헤더 배경
    draw.rounded_rectangle([x, y, x + w, y + HEADER_H], radius=14, fill=accent)
    draw.rectangle([x, y + HEADER_H - 14, x + w, y + HEADER_H], fill=accent)

    # 챕터 이름 (헤더 왼쪽)
    draw.text((x + 22, y + HEADER_H // 2), chapter[:5],
              font=fnt_bold, fill=BADGE_BG, anchor="lm")

    # 등급 배지 (헤더 오른쪽)
    if badge_text:
        badge_w = 110
        badge_h = 52
        badge_x = x + w - badge_w - 16
        badge_y = y + (HEADER_H - badge_h) // 2
        draw.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                               radius=10, fill=BADGE_BG)
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
    draw.rounded_rectangle([x, footer_y - 6, x + w, y + h], radius=14, fill=BADGE_BG)

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


# ── 강조 마커(*...*) 색상 렌더링 ──────────────────────────────────────────────
# 대본에서 핵심 글귀를 *별표*로 감싸면 화면에서 강조색(기본 골드)으로 표시한다.
_HL_RE    = re.compile(r"\*(.+?)\*")
# 토큰화: 영문/숫자/통화 묶음은 한 덩어리, 공백은 그대로, 그 외(한글 등)는 글자 단위
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9$%.,+\-]*|\s+|[^\sA-Za-z0-9]")


def strip_markup(text: str) -> str:
    """강조 마커(*)를 제거한 순수 텍스트 — 마커를 해석하지 않는 렌더용."""
    return (text or "").replace("*", "")


def split_runs(text: str):
    """'*...*' 마커 기준으로 (조각, 강조여부) 런 리스트 반환. 마커는 제거된다."""
    runs, pos = [], 0
    text = text or ""
    for m in _HL_RE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], False))
        runs.append((m.group(1), True))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], False))
    return [(seg.replace("*", ""), hl) for seg, hl in runs if seg.replace("*", "")]


def wrap_runs(draw, runs, font, max_w):
    """런 리스트를 max_w에 맞춰 여러 시각 줄로 래핑. 각 줄은 (조각, 강조여부) 런 리스트."""
    toks = []
    for seg, hl in runs:
        for t in _TOKEN_RE.findall(seg):
            toks.append((t, hl))

    def line_w(items):
        s = "".join(t for t, _ in items)
        return draw.textlength(s, font=font) if s else 0

    lines, cur = [], []
    for t, hl in toks:
        if t == "\n":
            lines.append(cur); cur = []; continue
        if not cur and t.isspace():
            continue
        if not cur or line_w(cur + [(t, hl)]) <= max_w:
            cur.append((t, hl))
        else:
            lines.append(cur)
            cur = [] if t.isspace() else [(t, hl)]
    if cur:
        lines.append(cur)

    out = []
    for line in lines:
        while line and line[0][0].isspace():
            line = line[1:]
        while line and line[-1][0].isspace():
            line = line[:-1]
        merged = []
        for t, hl in line:
            if merged and merged[-1][1] == hl:
                merged[-1] = (merged[-1][0] + t, hl)
            else:
                merged.append((t, hl))
        if merged:
            out.append(merged)
    return out


def draw_rich_line(draw, x, y, line_runs, font, base_fill, hl_fill,
                   stroke_width=1, stroke_fill=STROKE, center_w=None):
    """한 시각 줄(런 리스트)을 그린다. center_w 지정 시 그 폭 안에서 가운데 정렬."""
    total = sum(draw.textlength(seg, font=font) for seg, _ in line_runs)
    cx = x + max(0, (center_w - total)) / 2 if center_w is not None else x
    for seg, hl in line_runs:
        draw.text((cx, y), seg, font=font,
                  fill=(hl_fill if hl else base_fill),
                  stroke_width=stroke_width, stroke_fill=stroke_fill)
        cx += draw.textlength(seg, font=font)
    return total


def draw_rich_text(draw, text, x, y, font, base_fill, max_w, *, hl_fill=KEY,
                   max_lines=None, center=False, center_x=None, center_w=None,
                   stroke_width=1, stroke_fill=STROKE, line_h=None, line_gap=8):
    """마커 포함 텍스트를 래핑 + 색상 강조하여 그린다. 다음 y를 반환.

    center=True면 center_w(기본 max_w) 안에서 center_x(기본 x) 기준 가운데 정렬.
    """
    runs    = split_runs(strip_emoji(text))
    wrapped = wrap_runs(draw, runs, font, max_w)
    if max_lines:
        wrapped = wrapped[:max_lines]
    bb   = draw.textbbox((0, 0), "가", font=font)
    step = line_h if line_h else (bb[3] - bb[1]) + line_gap
    cw   = (center_w if center_w is not None else max_w) if center else None
    cx   = center_x if center_x is not None else x
    for line_runs in wrapped:
        draw_rich_line(draw, cx, y, line_runs, font, base_fill, hl_fill,
                       stroke_width=stroke_width, stroke_fill=stroke_fill,
                       center_w=cw)
        y += step
    return y


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
                           radius=14, fill=CARD_BG, outline=(55, 65, 95), width=1)

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
    draw.line([(SEP_X, LY + 16), (SEP_X, LY + LH - 16)], fill=(65, 75, 105), width=1)

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
    draw.rectangle([x, y, x + w, y + h], fill=CARD_BG, outline=(55, 65, 95), width=1)
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


def draw_check(draw, x, y, size, color, width=None):
    """체크표시 ✓ (두 선분) — (x, y)는 좌상단, size는 한 변 기준."""
    w = width or max(3, size // 7)
    p1 = (x + size * 0.08, y + size * 0.52)
    p2 = (x + size * 0.38, y + size * 0.82)
    p3 = (x + size * 0.92, y + size * 0.14)
    draw.line([p1, p2], fill=color, width=w)
    draw.line([p2, p3], fill=color, width=w)


def draw_bullish_hero_card(draw, img, x, y, w, h, headline, details, score,
                            source, date, accent, fnt_bold, fnt_content,
                            fnt_source, fnt_content_xl=None, fnt_content_sm=None,
                            category=""):
    """호재 심층 히어로 카드 — BEST 배지 + ✓ 체크 머리기호 + 카테고리 라벨 + 스토리텔링."""
    from PIL import ImageDraw

    HEADER_H = 90
    FOOTER_H = 64

    # 카드 배경
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14,
                            fill=CARD_BG, outline=accent, width=2)

    # 헤더 배경 (GREEN 강조)
    draw.rounded_rectangle([x, y, x + w, y + HEADER_H], radius=14, fill=accent)
    draw.rectangle([x, y + HEADER_H - 14, x + w, y + HEADER_H], fill=accent)

    # 헤더 왼쪽: 카테고리 또는 소스 라벨 ("+4pt" 대신 — 시청자에게 의미 있는 정보)
    header_label = (category or source or "이번주 HOT")[:14]
    draw.text((x + 22, y + HEADER_H // 2), header_label,
              font=fnt_bold, fill=BADGE_BG, anchor="lm",
              stroke_width=2, stroke_fill=(0, 60, 0))

    # 헤더 오른쪽: "BEST" 배지
    badge_w, badge_h = 110, 52
    bx = x + w - badge_w - 16
    by = y + (HEADER_H - badge_h) // 2
    draw.rounded_rectangle([bx, by, bx + badge_w, by + badge_h],
                           radius=10, fill=BADGE_BG)
    draw.text((bx + badge_w // 2, by + badge_h // 2),
              "BEST", font=fnt_bold, fill=KEY, anchor="mm",
              stroke_width=1, stroke_fill=STROKE)

    # 본문 영역 — 각 호재 줄 앞에 초록 체크(✓) 머리기호
    content_x    = x + 28
    content_y    = y + HEADER_H + 16
    content_max_w = w - 28 - 22
    content_area_h = h - HEADER_H - FOOTER_H - 32
    CHECK_W      = 44   # 체크 + 여백 폭

    all_lines = [headline] + [d for d in details if d.strip()]

    # 헤드라인은 항상 xl(62px), 본문은 항상 content(46px) — 일관된 크기 계층
    headline_font = fnt_content_xl if fnt_content_xl else fnt_bold
    body_font     = fnt_content

    bb = draw.textbbox((0, 0), "가", font=body_font)
    char_h = bb[3] - bb[1]
    line_h = char_h + 26  # 충분한 줄 간격으로 가독성 확보

    cy = content_y
    for i, ln in enumerate(all_lines[:6]):   # 헤드라인+5details
        if not ln.strip() or cy + char_h > y + h - FOOTER_H - 8:
            continue
        use_font  = headline_font if i == 0 else body_font
        use_col   = WHITE         if i == 0 else LGRAY
        sw        = 2             if i == 0 else 1
        is_detail = i >= 1                       # 헤드라인 제외, 호재 항목에만 체크
        text_x    = content_x + (CHECK_W if is_detail else 0)
        wrap_w    = content_max_w - (CHECK_W if is_detail else 0)
        wrapped   = wrap_runs(draw, split_runs(strip_emoji(ln)), use_font, wrap_w)
        for j, line_runs in enumerate(wrapped[:2]):
            if cy + char_h > y + h - FOOTER_H - 8:
                break
            if is_detail and j == 0:             # 줄 첫 행에만 ✓
                draw_check(draw, content_x, cy + char_h * 0.12, char_h, GREEN)
            draw_rich_line(draw, text_x, cy, line_runs, use_font, use_col, KEY,
                           stroke_width=sw, stroke_fill=STROKE)
            cy += line_h

    # 하단 출처 바 (source · date)
    footer_y = y + h - FOOTER_H
    draw.rounded_rectangle([x, footer_y - 6, x + w, y + h], radius=14, fill=BADGE_BG)
    footer_text = " · ".join(filter(None, [source, date])) or "출처 미상"
    draw.text((x + 18, footer_y + FOOTER_H // 2), footer_text[:50],
              font=fnt_source, fill=KEY, anchor="lm",
              stroke_width=1, stroke_fill=STROKE)


_FRAME_TEMPLATE_PATH = Path("data/frame-template.png")
_frame_overlay_cache = None
_frame_overlay_loaded = False

def _load_frame_overlay():
    """프레임 템플릿 이미지를 1회 로드 후 캐싱 (없으면 None)."""
    global _frame_overlay_cache, _frame_overlay_loaded
    if _frame_overlay_loaded:
        return _frame_overlay_cache
    _frame_overlay_loaded = True
    if not _FRAME_TEMPLATE_PATH.exists():
        return None
    try:
        from PIL import Image as PILImage
        ov = PILImage.open(_FRAME_TEMPLATE_PATH).convert("RGBA")
        if ov.size != (W, H):
            ov = ov.resize((W, H), PILImage.LANCZOS)
        _frame_overlay_cache = ov
    except Exception as e:
        print(f"   ⚠ frame-template.png 로드 실패: {e}", file=sys.stderr)
    return _frame_overlay_cache


def _apply_frame_overlay(img):
    """씬 이미지 위에 통일 브랜드 프레임 오버레이 합성 (있을 때만)."""
    ov = _load_frame_overlay()
    if ov is None:
        return img
    from PIL import Image as PILImage
    base = img.convert("RGBA")
    return PILImage.alpha_composite(base, ov).convert("RGB")


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

    # ── 폰트 (1080px 세로 포맷 기준 충분히 큰 사이즈) ──
    f_xl    = fnt(font_bold, 72)
    f_lg    = fnt(font_bold, 54)   # 40→54
    f_md    = fnt(font_bold, 48)   # 32→48
    f_nm    = fnt(font_reg,  44)   # 30→44
    f_sm    = fnt(font_reg,  36)   # 22→36
    f_xs    = fnt(font_reg,  30)   # 18→30
    f_src   = fnt(font_reg,  30)   # 20→30
    f_ch    = fnt(font_bold, 48)   # 34→48
    f_ct    = fnt(font_reg,  50)   # 34→50
    f_ct_xl = fnt(font_reg,  62)   # 44→62
    f_ct_sm = fnt(font_reg,  42)   # 28→42
    # MBC 스타일 헤더 폰트
    f_brand = fnt(font_bold, 44)   # 32→44
    f_head_main = fnt(font_bold, 80)
    f_head_sub  = fnt(font_bold, 64)
    # 인트로 전용: 대형 % 숫자
    f_huge      = fnt(font_bold, 200)
    f_huge_sub  = fnt(font_bold, 68)   # 56→68

    # ── 부드러운 라운드 폰트 (호재 심층 씬용 — 딱딱함 완화) ──
    soft_reg, soft_bold = find_soft_font()
    soft_reg  = soft_reg  or font_reg
    soft_bold = soft_bold or font_bold
    sf_ch        = fnt(soft_bold, 48)
    sf_ct        = fnt(soft_reg,  46)
    sf_ct_xl     = fnt(soft_reg,  62)
    sf_ct_sm     = fnt(soft_reg,  42)
    sf_src       = fnt(soft_reg,  30)
    sf_brand     = fnt(soft_bold, 44)
    sf_head_main = fnt(soft_bold, 80)
    sf_head_sub  = fnt(soft_bold, 64)

    news_lines = [l for l in lines if l.strip() and not l.startswith("SCENE")]

    # ╔══════════════════════════════════════════════════════════════════╗
    # ║ 씬 2 — 다음주 전망 (클로징, custom layout)                         ║
    # ╚══════════════════════════════════════════════════════════════════╝
    if idx == 2:
        # ① AI 배경 이미지를 풀스크린으로 깔기 (미래 비전 이미지)
        if bg_path and bg_path.exists():
            try:
                from PIL import Image as PILImage
                bg = PILImage.open(bg_path).convert("RGB")
                bw, bh = bg.size
                ratio = max(W / bw, H / bh)
                nw, nh = int(bw * ratio), int(bh * ratio)
                bg = bg.resize((nw, nh), PILImage.LANCZOS)
                ox, oy = (nw - W) // 2, (nh - H) // 2
                img.paste(bg.crop((ox, oy, ox + W, oy + H)), (0, 0))
                # 마젠타 톤 오버레이 — 0.6→0.42로 밝게
                overlay = PILImage.new("RGB", (W, H), (38, 12, 65))
                img = PILImage.blend(img, overlay, 0.42)
                draw = ImageDraw.Draw(img)
            except Exception:
                pass
        else:
            # 폴백: 기존 검정→마젠타 그라데이션
            for yy in range(H):
                t = yy / H
                draw.line([(0, yy), (W, yy)], fill=(
                    int(35 + 60 * t), int(10 + 28 * t), int(58 + 90 * t)
                ))

        # ── 헤더: 다음주 전망 ─────────────────────────────────────────
        draw.text((W // 2, 80), "다음주 전망",
                  font=f_huge_sub, fill=WHITE, anchor="mt",
                  stroke_width=3, stroke_fill=STROKE)
        draw.line([(W // 2 - 200, 162), (W // 2 + 200, 162)],
                  fill=accent, width=4)

        # ── 3개 메시지 카드 (비전·예상·믿음) ─────────────────────────
        # news_lines: [0]=비전계획, [1]=→예상결과, [2]=다음주포인트, [3]=→기대결과, [4]=추가이벤트, [5]=마무리
        def _nl(i, fallback):
            return strip_emoji(news_lines[i]) if len(news_lines) > i else fallback

        # 카드별 (label, lines[], col, bgcol, max_body_lines)
        MSG_CARDS = [
            ("다음주 일정",  [_nl(0, "다음 주 핵심 이벤트를 주목하세요"),
                              _nl(1, "")],
             KEY,    CARD_AMBER,  2),
            ("가격 전망",    [_nl(2, "변동성 흐름을 지켜봐요"),
                              _nl(3, ""),
                              _nl(4, "")],
             accent, CARD_PURPLE, 3),
            ("마무리",        [_nl(5, "다음에 또 만나요!")],
             GREEN,  CARD_GREEN,  1),
        ]
        LINE_H = 52      # 줄간 px
        LABEL_H = 56     # 라벨 영역 높이 (상단 여백 포함)
        BODY_PAD = 18    # 본문 하단 여백
        MSG_Y = 195
        MSG_GAP = 14
        cy = MSG_Y
        last_cy_bottom = MSG_Y
        for label, body_lines, col, bgcol, max_lines in MSG_CARDS:
            # 실제 출력할 줄(빈 줄 제거, max_lines 제한)
            visible = [l for l in body_lines if l.strip()][:max_lines]
            if not visible:
                visible = [body_lines[0]] if body_lines else [""]
            card_h = LABEL_H + len(visible) * LINE_H + BODY_PAD
            draw.rounded_rectangle([PAD, cy, W - PAD, cy + card_h],
                                   radius=18, fill=bgcol, outline=col, width=3)
            draw.text((PAD + 22, cy + 14), label,
                      font=f_sm, fill=col, anchor="lt")
            ty = cy + LABEL_H
            for txt in visible:
                tw = wrap_runs(draw, split_runs(txt), f_nm, W - PAD * 2 - 44)
                for line_runs in tw[:1]:  # 1 wrapped line per content line
                    draw_rich_line(draw, 0, ty, line_runs, f_nm, WHITE, KEY,
                                   stroke_width=2, stroke_fill=STROKE, center_w=W)
                ty += LINE_H
            last_cy_bottom = cy + card_h
            cy = last_cy_bottom + MSG_GAP

        # ── 다음주 이벤트 한 줄 (있을 때만, 슬림 띠) ─────────────────
        next_events = summary.get("next_events", []) or []
        SLIM_Y = last_cy_bottom + MSG_GAP + 6
        if next_events:
            ev = next_events[0]
            date_s = ev.get("date", "")
            title_s = strip_emoji(ev.get("title", "")[:30])
            SLIM_H = 80
            draw.rounded_rectangle([PAD, SLIM_Y, W - PAD, SLIM_Y + SLIM_H],
                                   radius=14, fill=(38, 22, 62), outline=AMBER, width=2)
            draw.text((PAD + 20, SLIM_Y + SLIM_H // 2), f"▶ {date_s}",
                      font=f_sm, fill=AMBER, anchor="lm")
            draw.text((W - PAD - 20, SLIM_Y + SLIM_H // 2), title_s,
                      font=f_sm, fill=WHITE, anchor="rm",
                      stroke_width=1, stroke_fill=STROKE)
        else:
            # 폴백 자리 비움 (다음 단계 좌표 보존)
            SLIM_H = 0

        # ── AI 생성 고지 (마지막 씬 최하단, 화면 표기 전용) ─────────────
        # script.json lines에 포함되지 않으므로 TTS 나레이션은 읽지 않는다.
        from PIL import Image as PILImage
        NOTICE_LINES = [
            "본 영상은 AI 분석 툴로 수집한 뉴스 자료를 분석해",
            "핵심 내용을 요약·정리한 영상물입니다",
        ]
        band_h = 118
        strip = img.crop((0, H - band_h, W, H)).convert("RGBA")
        shade = PILImage.new("RGBA", (W, band_h), (10, 14, 26, 205))
        img.paste(PILImage.alpha_composite(strip, shade).convert("RGB"), (0, H - band_h))
        draw = ImageDraw.Draw(img)
        ny = H - band_h + 24
        for nl in NOTICE_LINES:
            draw.text((W // 2, ny), nl, font=f_xs, fill=(170, 180, 202), anchor="mt")
            ny += 38

        # CTA 텍스트 없음 (나레이션으로 대체)

        return _apply_frame_overlay(img)

    # ── 씬별 헤드라인 텍스트 결정 (MBC 스타일) ──────────────────────────
    if idx == 0:
        # 메인: 대본 첫 줄 그대로. 큰따옴표 추가.
        first = strip_markup(news_lines[0] if news_lines else f"이번 주 {COMPANY_KO}").strip()
        if not (first.startswith('"') or first.startswith("'")):
            first = f'"{first}"'
        head_main = first
        # 부제: 현재 주가 + 1주 전 대비 변동률(▲/▼) — 점수 대신 직관적 수치
        price = summary.get("latest_price")
        wc    = summary.get("week_change_pct")
        try:
            price_s = f"${float(price):,.0f}" if price else ""
        except Exception:
            price_s = ""
        if wc is not None:
            arrow = "▲" if wc >= 0 else "▼"
            sign  = "+" if wc >= 0 else ""
            chg_s = f"주간 {arrow} {sign}{wc}%"
            head_sub = f"{price_s} · {chg_s}" if price_s else chg_s
        else:
            head_sub = price_s or "주간 브리핑"
    elif idx == 1:
        head_main = '"이번 주 빅 호재"'
        top_bull = (summary.get("top_bullish") or [{}])[0]
        ch, _, _ = parse_news_line(news_lines[0]) if news_lines else ("", "", "")
        cat = top_bull.get("category", "") or ch
        head_sub = strip_markup(cat) if cat else "심층 분석"

    # ── 상단 헤더 (Y=0~500) — 네이비 박스 + 브랜드 + 두줄 헤드라인 ──────
    # 호재 심층 씬(idx 1)은 부드러운 라운드 폰트로 딱딱함 완화
    if idx == 1:
        hdr_brand, hdr_main, hdr_sub = sf_brand, sf_head_main, sf_head_sub
    else:
        hdr_brand, hdr_main, hdr_sub = f_brand, f_head_main, f_head_sub
    draw_mbc_header(draw, BRAND_LABEL, head_main, head_sub, accent,
                    hdr_brand, hdr_main, hdr_sub)

    # ── 사진 배너 (Y=500~1000, 500px) ────────────────────────────────────
    draw_photo_card(img, draw, accent, bg_path, x=0, y=PHOTO_Y, w=W, h=PHOTO_H)
    draw = ImageDraw.Draw(img)

    # 푸터 텍스트는 자막+UI에 가려지므로 제거

    # ── 씬 0: 주간 브리핑 — 본문 영역 (4줄 대본 → 3카드 레이아웃) ──────────
    CONTENT_Y = START_Y + 40   # 사진 하단과 본문 사이 40px 여백
    if idx == 0:
        FC_W = COL_W - PAD
        CARD_GAP = 16
        TOTAL_H  = SAFE_BOTTOM - CONTENT_Y   # 약 640px

        # ─ 변동 원인 사전 측정 → 동적 REASON_H ──────────────────────────────
        movement_reason = strip_markup(strip_emoji(summary.get("movement_reason") or ""))
        if not movement_reason and len(news_lines) >= 2:
            movement_reason = strip_markup(strip_emoji(news_lines[1]))

        # 너무 긴 경우 "/" 또는 "·"로 구분된 핵심 구절 3개로 요약
        if movement_reason and len(movement_reason) > 80:
            parts = [p.strip() for p in re.split(r'[/·/]', movement_reason) if p.strip()]
            if len(parts) > 3:
                movement_reason = " / ".join(parts[:3])

        rw_reason = wrap_text(draw, movement_reason, f_sm, FC_W - 40) if movement_reason else []
        reason_line_count = min(len(rw_reason), 5)  # 최대 5줄
        REASON_H = 66 + reason_line_count * 44 + 20  # 헤더 + 콘텐츠 + 패딩
        REASON_H = max(200, min(340, REASON_H))       # [200, 340] 범위 클램프

        SIDE_H = (TOTAL_H - REASON_H - CARD_GAP * 3) // 2
        SIDE_H = max(140, SIDE_H)  # 최소 가독성 확보

        # ─ 변동 원인 카드 — movement_reason(Google Search) 우선, 없으면 script line 2
        draw.rounded_rectangle([PAD, CONTENT_Y, PAD + FC_W, CONTENT_Y + REASON_H],
                               radius=14, fill=CARD_BG, outline=accent, width=3)
        draw.text((PAD + 20, CONTENT_Y + 14), "이번주 변동 원인",
                  font=f_sm, fill=accent, anchor="lt")
        if movement_reason:
            ky = CONTENT_Y + 66
            for wl in rw_reason[:5]:
                if ky + 38 > CONTENT_Y + REASON_H - 8:
                    break
                bb = draw.textbbox((0, 0), wl, font=f_sm)
                draw.text(((W - (bb[2] - bb[0])) // 2, ky), wl,
                          font=f_sm, fill=WHITE, stroke_width=1, stroke_fill=STROKE)
                ky += 44

        # ─ 호재 카드 — 대본 + top_bullish 원문으로 내용 강화
        BULL_Y = CONTENT_Y + REASON_H + CARD_GAP
        top_bull_data   = (summary.get("top_bullish") or [{}])[0]
        bull_headline   = strip_emoji(news_lines[2]) if len(news_lines) >= 3 else strip_emoji(top_bull_data.get("title", ""))
        bull_detail     = strip_markup(strip_emoji(top_bull_data.get("reason", "")))[:100]
        draw.rounded_rectangle([PAD, BULL_Y, PAD + FC_W, BULL_Y + SIDE_H],
                               radius=12, fill=CARD_GREEN, outline=GREEN, width=2)
        draw.text((PAD + 16, BULL_Y + 12), "▲ 호재", font=f_sm, fill=GREEN)
        cy_bull = BULL_Y + 56
        if bull_headline:
            for line_runs in wrap_runs(draw, split_runs(bull_headline), f_sm, FC_W - 40)[:2]:
                draw_rich_line(draw, PAD + 20, cy_bull, line_runs, f_sm, WHITE, KEY,
                               stroke_width=1, stroke_fill=STROKE)
                cy_bull += 42
        if bull_detail and cy_bull + 38 < BULL_Y + SIDE_H - 8:
            for wl in wrap_text(draw, bull_detail, f_xs, FC_W - 40)[:2]:
                if cy_bull + 34 >= BULL_Y + SIDE_H - 8:
                    break
                draw.text((PAD + 20, cy_bull), wl, font=f_xs, fill=LGRAY,
                          stroke_width=1, stroke_fill=STROKE)
                cy_bull += 36

        # ─ 악재 카드 — 대본 + top_bearish 원문으로 내용 강화
        BEAR_Y = BULL_Y + SIDE_H + CARD_GAP
        top_bear_data   = (summary.get("top_bearish") or [{}])[0]
        bear_headline   = strip_emoji(news_lines[3]) if len(news_lines) >= 4 else strip_emoji(top_bear_data.get("title", ""))
        bear_detail     = strip_markup(strip_emoji(top_bear_data.get("reason", "")))[:100]
        draw.rounded_rectangle([PAD, BEAR_Y, PAD + FC_W, BEAR_Y + SIDE_H],
                               radius=12, fill=CARD_RED, outline=RED, width=2)
        draw.text((PAD + 16, BEAR_Y + 12), "▼ 악재", font=f_sm, fill=RED)
        cy_bear = BEAR_Y + 56
        if bear_headline:
            for line_runs in wrap_runs(draw, split_runs(bear_headline), f_sm, FC_W - 40)[:2]:
                draw_rich_line(draw, PAD + 20, cy_bear, line_runs, f_sm, WHITE, KEY,
                               stroke_width=1, stroke_fill=STROKE)
                cy_bear += 42
        if bear_detail and cy_bear + 38 < BEAR_Y + SIDE_H - 8:
            for wl in wrap_text(draw, bear_detail, f_xs, FC_W - 40)[:2]:
                if cy_bear + 34 >= BEAR_Y + SIDE_H - 8:
                    break
                draw.text((PAD + 20, cy_bear), wl, font=f_xs, fill=LGRAY,
                          stroke_width=1, stroke_fill=STROKE)
                cy_bear += 36

    # ── 씬 1: 호재 심층 — 풀사이즈 히어로 카드 1장 ─────────────────────────
    elif idx == 1:
        CARD_W = COL_W - PAD
        CARD_H = SAFE_BOTTOM - CONTENT_Y
        top_bull    = (summary.get("top_bullish") or [{}])[0]
        bull_source = top_bull.get("source", "")
        bull_date   = top_bull.get("date", "")
        bull_cat    = top_bull.get("category", "")
        bull_reason = strip_emoji(top_bull.get("reason", ""))

        headline = news_lines[0] if news_lines else f"{COMPANY_KO} 주요 호재"
        _, headline_content, _ = parse_news_line(headline)

        # 스크립트 detail 줄들
        script_details = [l.lstrip("↳ ").strip() for l in news_lines[1:6] if l.strip()]
        # reason(세션 원문)으로 보강 — 스크립트가 빈약하면 reason을 줄 단위로 분할해 추가
        script_text = " ".join(script_details)
        if bull_reason and len(script_text) < 80:
            import re as _re
            reason_parts = [p.strip() for p in _re.split(r'[.!?。·]', bull_reason) if len(p.strip()) > 8][:3]
            details = script_details + reason_parts
        else:
            details = script_details

        draw_bullish_hero_card(
            draw, img,
            x=PAD, y=CONTENT_Y, w=CARD_W, h=CARD_H,
            headline=headline_content or top_bull.get("title", headline),
            details=details,
            score=top_bull.get("score", 5),
            source=bull_source, date=bull_date,
            accent=accent,
            fnt_bold=sf_ch, fnt_content=sf_ct, fnt_source=sf_src,
            fnt_content_xl=sf_ct_xl, fnt_content_sm=sf_ct_sm,
            category=bull_cat,
        )
        draw = ImageDraw.Draw(img)

    return _apply_frame_overlay(img)


def build_images(scenes, summary, out_dir, img_prompts=None):
    try:
        from PIL import ImageFont
    except ImportError:
        print("   ⚠ Pillow 없음 — 이미지 건너뜀", file=sys.stderr)
        return

    font_reg, font_bold = find_font()
    if not font_reg:
        print("   ⚠ 한글 폰트 없음 — 이미지 건너뜀", file=sys.stderr)
        return

    if img_prompts is None:
        img_prompts = {}

    # 모든 씬에 AI 배경 이미지 생성
    BG_SCENES = {0, 1, 2}
    # 씬별 aspect ratio — 0·1은 가로 strip(16:9), 2(미래비전)는 풀스크린(9:16)
    BG_ASPECTS = {0: "16:9", 1: "16:9", 2: "9:16"}

    print("   🖼 배경 이미지 준비 중...")
    bg_paths = {}
    for scene in scenes:
        idx      = scene["index"]
        bg_path  = out_dir / f"bg_{idx:02d}.jpg"
        articles = SCENE_WIKI_ARTICLES[idx] if idx < len(SCENE_WIKI_ARTICLES) else ["Tesla, Inc."]

        if idx not in BG_SCENES:
            bg_paths[idx] = None
            continue

        # 1순위: Nano Banana AI 이미지 (GEMINI_API_KEY 필요)
        prompt = img_prompts.get(idx, "")
        aspect = BG_ASPECTS.get(idx, "16:9")
        if prompt:
            ok = fetch_nano_banana_image(prompt, bg_path, aspect_ratio=aspect)
            if ok:
                bg_paths[idx] = bg_path
                print(f"      씬{idx} [Nano Banana AI · {aspect}] ✅")
                continue
            print(f"      씬{idx} Nano Banana 실패 → Wikipedia 폴백", file=sys.stderr)

        # 2순위: Wikipedia
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

    # 양산형 탈피: 생성일 시드로 인트로/클로징(썸네일) 색상 테마 로테이션 (씬1 호재는 초록 유지)
    global SCENE_ACCENTS
    SCENE_ACCENTS = ACCENT_THEMES[_theme_idx(today)]
    print(f"   🎨 색상 테마 #{_theme_idx(today)} 적용 (격일 생성마다 변형)")

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

    # ── 주가 변동 원인 (Google Search grounding) ──
    print("🔍 주가 변동 원인 검색 중...")
    summary["movement_reason"] = search_movement_reason(summary)

    # ── 대본 ──
    img_prompts = {}  # Nano Banana 이미지 생성에 사용 (대본 생성 시 채워짐)
    if not ANTHROPIC_API_KEY and not GEMINI_API_KEY:
        print("⚠ API 키 없음 — 대본 생성 건너뜀", file=sys.stderr)
        scenes = [{"index": i, "title": f"씬 {i}", "lines": [], "body": ""} for i in range(0, 3)]
    else:
        print("✍ 대본 생성 중...")
        raw    = generate_script(summary)
        scenes = parse_script(raw)
        img_prompts = parse_image_prompts(raw)

        # 대시보드용 title/subtitle — 씬0(주간브리핑) 첫 줄에서 추출
        script_title = ""
        script_subtitle = f"{summary['week_start']} ~ {summary['week_end']}"
        scene1 = next((s for s in scenes if s["index"] == 0), None)
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
            scene_names = {0: "씬0 주간브리핑", 1: "씬1 호재심층", 2: "씬2 다음주전망"}
            for i in range(0, 3):
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
    build_images(scenes, summary, out_dir, img_prompts)

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
