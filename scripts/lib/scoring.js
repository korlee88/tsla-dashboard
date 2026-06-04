/**
 * 다층 강화 채점 모델 v5.0 (편향보정·증폭재조정·중립밴드) — 멀티 종목 지원
 *
 * 레이어 구조:
 *   [Base] 원본 매수지수 (avgScore → buyIndex)
 *   [14] R25 종목고유 부스트 (+8pt, R07 동반 시 +5 추가) — TSLA: Optimus
 *   [1]  R24 단독 발동 노이즈 할인
 *   [2]  강한신호 증폭 (±20 이탈 시 ×1.08 — v5.0: 1.15→1.08 과열억제)
 *   [3]  매크로 오버레이 (SPY+QQQ 평균 × beta — v5.0: cfg.beta_coefficient 사용)
 *   [4]  전주 자산 momentum (mean reversion)
 *   [5]  VIX regime (>30 공포장 → 신호 강도 ×0.8)
 *   [6]  RSI 14주 (과매도/과매수 보정)
 *   [7]  중립밴드 도입 — v5.0: bi 43-57 약신호는 neutral 출력 허용
 *   [8]  MACD (12/26/9) 크로스오버 & 방향 (+1pt — v5.0: 2→1 지속트렌드 편향 감소)
 *   [9]  볼린저밴드 위치 (20주 — v5.0: 과매수 페널티 강화)
 *   [10] WTI 원유 주간 등락
 *   [11] CNY/USD 환율
 *   [12] 분기 인도량/실적 발표주 신호 증폭 (v5.0: 1.35→1.15 과신억제)
 *   [13] 뉴스 카테고리 가중치 (Financial > Tech > Market)
 *   [15] 경쟁사 상대강도 (cfg.competitor_ticker) — 백테스트 적용 (Yahoo 주봉)
 *   [16] 옵션 ATM IV 감쇠 — 라이브 전용 (과거 IV 없음 → 백테스트 skip)
 *   [17] 공매도 비율 숏스퀴즈 증폭 — 라이브 전용 (백테스트 skip)
 *   [18] 추세 필터 (v5.0 NEW) — 뉴스 감성과 독립된 3주 가격추세 신호
 *        backtest 동시검증: 2025 57→65%, 2026 40→50% (깨진 예측 0건)
 */

// ─── Yahoo Finance 주봉 로더 ────────────────────────────────────────────────

async function fetchYahooWeekly(symbol) {
  const URLs = [
    `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?range=2y&interval=1wk`,
    `https://query2.finance.yahoo.com/v8/finance/chart/${symbol}?range=2y&interval=1wk`,
  ];
  for (const url of URLs) {
    try {
      const r = await fetch(url, { headers: { 'user-agent': 'Mozilla/5.0' } });
      if (r.ok) {
        const j = await r.json();
        const d = j?.chart?.result?.[0];
        const ts = d?.timestamp || [];
        const q  = d?.indicators?.quote?.[0] || {};
        return ts.map((t, i) => ({
          ts:      t * 1000,
          dateStr: new Date(t * 1000).toISOString().split('T')[0],
          open:    q.open?.[i]  || q.close?.[i] || 0,
          high:    q.high?.[i]  || 0,
          low:     q.low?.[i]   || 0,
          close:   q.close?.[i] || 0,
        })).filter(d => d.close > 0);
      }
    } catch {}
  }
  throw new Error(`${symbol} 주봉 로드 실패`);
}

/**
 * @param {Object} cfg - ticker.json 설정 (ticker, competitor_ticker 사용)
 */
async function loadMacroData(cfg = {}) {
  const ticker     = cfg.ticker            || 'TSLA';
  const competitorTicker = cfg.competitor_ticker || null;

  const [spy, qqq, vix, asset, wti, cny] = await Promise.all([
    fetchYahooWeekly('SPY'),
    fetchYahooWeekly('QQQ'),
    fetchYahooWeekly('^VIX'),
    fetchYahooWeekly(ticker),
    fetchYahooWeekly('CL=F'),   // WTI 원유
    fetchYahooWeekly('CNY=X'),  // CNY/USD 환율
  ]);

  let competitor = [];
  if (competitorTicker) {
    try {
      competitor = await fetchYahooWeekly(competitorTicker);
    } catch {
      // 경쟁사 데이터는 선택적 — 실패해도 파이프라인 유지
    }
  }
  // 하위 호환: 기존 코드가 macroData.tsla / macroData.byd로 접근하는 경우를 위해
  return { spy, qqq, vix, asset, competitor, wti, cny, tsla: asset, byd: competitor };
}

// ─── 라이브 전용 스냅샷 (과거 데이터 없음 → 백테스트 미적용) ──────────────────

/**
 * 현재 ATM 옵션 내재변동성(IV) 조회. Yahoo는 현재 스냅샷만 제공(과거 IV 없음).
 * → 라이브 분석에서만 사용, 백테스트에서는 호출하지 않음.
 * @returns {number|null} ATM IV (예: 0.62 = 62%) 또는 null
 */
async function fetchOptionsIV(symbol = 'TSLA') {
  try {
    const r = await fetch(
      `https://query1.finance.yahoo.com/v7/finance/options/${symbol}`,
      { headers: { 'user-agent': 'Mozilla/5.0' } });
    if (!r.ok) return null;
    const j = await r.json();
    const res = j?.optionChain?.result?.[0];
    const spot = res?.quote?.regularMarketPrice;
    const calls = res?.options?.[0]?.calls || [];
    if (!spot || !calls.length) return null;
    // 현재가에 가장 가까운 행사가(ATM)의 IV 추출
    let atm = null, minDiff = Infinity;
    for (const c of calls) {
      const diff = Math.abs((c.strike || 0) - spot);
      if (diff < minDiff && c.impliedVolatility > 0) { minDiff = diff; atm = c.impliedVolatility; }
    }
    return atm ? Math.round(atm * 1000) / 1000 : null;
  } catch { return null; }
}

/**
 * 현재 공매도 비율(short % of float) 조회. Yahoo는 현재 스냅샷만 제공.
 * → 라이브 분석에서만 사용, 백테스트 미적용.
 * @returns {number|null} short % of float (예: 0.032 = 3.2%) 또는 null
 */
async function fetchShortInterest(symbol = 'TSLA') {
  try {
    const r = await fetch(
      `https://query1.finance.yahoo.com/v10/finance/quoteSummary/${symbol}?modules=defaultKeyStatistics`,
      { headers: { 'user-agent': 'Mozilla/5.0' } });
    if (!r.ok) return null;
    const j = await r.json();
    const stats = j?.quoteSummary?.result?.[0]?.defaultKeyStatistics;
    const sp = stats?.shortPercentOfFloat?.raw;
    return (typeof sp === 'number') ? Math.round(sp * 10000) / 10000 : null;
  } catch { return null; }
}

// ─── 기술적 지표 계산 ────────────────────────────────────────────────────────

/** EMA (지수이동평균) */
function calcEMA(arr, period) {
  const k = 2 / (period + 1);
  let ema = null;
  return arr.map(bar => {
    const v = (typeof bar === 'number') ? bar : (bar.close || 0);
    ema = ema === null ? v : v * k + ema * (1 - k);
    return ema;
  });
}

/** MACD (12/26/9 기본값) */
function calcMACD(arr, fast = 12, slow = 26, signal = 9) {
  const emaFast  = calcEMA(arr, fast);
  const emaSlow  = calcEMA(arr, slow);
  const macdLine = arr.map((_, i) => emaFast[i] - emaSlow[i]);
  const sigLine  = calcEMA(macdLine, signal);
  return arr.map((_, i) => ({
    macd:      macdLine[i],
    signal:    sigLine[i],
    hist:      macdLine[i] - sigLine[i],
    // 크로스오버: 이전 주와 이번 주 비교
    crossover: i > 0
      ? (macdLine[i]   > sigLine[i]   && macdLine[i-1] <= sigLine[i-1] ? 'bullish'
       : macdLine[i]   < sigLine[i]   && macdLine[i-1] >= sigLine[i-1] ? 'bearish'
       : null)
      : null,
    trend: macdLine[i] > sigLine[i] ? 'bullish' : 'bearish',
  }));
}

/** 볼린저밴드 (20주/2σ 기본값) */
function calcBollingerBands(arr, period = 20, devMult = 2) {
  return arr.map((bar, i) => {
    if (i < period - 1) return { upper: 0, middle: 0, lower: 0, pos: 0.5 };
    const closes = arr.slice(i - period + 1, i + 1).map(b => b.close);
    const sma    = closes.reduce((a, b) => a + b, 0) / period;
    const std    = Math.sqrt(closes.reduce((a, b) => a + (b - sma) ** 2, 0) / period);
    const upper  = sma + devMult * std;
    const lower  = sma - devMult * std;
    const pos    = upper > lower ? (bar.close - lower) / (upper - lower) : 0.5;
    return {
      upper:  Math.round(upper  * 100) / 100,
      middle: Math.round(sma    * 100) / 100,
      lower:  Math.round(lower  * 100) / 100,
      pos:    Math.round(Math.max(0, Math.min(1, pos)) * 1000) / 1000,
    };
  });
}

/** RSI (14주 기본값) */
function calcRSI(arr, idx, period = 14) {
  if (idx < period) return 50;
  let gains = 0, losses = 0;
  for (let i = idx - period + 1; i <= idx; i++) {
    const ch = arr[i].close - arr[i - 1].close;
    if (ch > 0) gains += ch; else losses += Math.abs(ch);
  }
  if (losses === 0) return 100;
  const rs = (gains / period) / (losses / period);
  return Math.round((100 - 100 / (1 + rs)) * 10) / 10;
}

// ─── 분기 발표주 판별 ────────────────────────────────────────────────────────

/**
 * 해당 주가 분기 인도량 발표 주간인지 확인.
 * cfg.has_delivery_reports=false 이면 항상 false (비EV 종목 대응).
 */
function isDeliveryWeek(weekStart, cfg = {}) {
  if (!cfg.has_delivery_reports) return false;
  const d   = new Date(weekStart + 'T00:00:00Z');
  const mo  = d.getUTCMonth() + 1;
  const day = d.getUTCDate();
  // 분기 첫 주 (earnings_months 또는 기본값 [1,4,7,10]의 1~7일)
  const months = cfg.earnings_months || [1, 4, 7, 10];
  return months.includes(mo) && day <= 7;
}

/**
 * 해당 주가 실적 발표(EPS) 주간인지 확인.
 * cfg.earnings_months 를 사용하며, 1월 실적의 2월 초 스필오버도 처리.
 */
function isEarningsWeek(weekStart, cfg = {}) {
  const months = cfg.earnings_months || [1, 4, 7, 10];
  const d   = new Date(weekStart + 'T00:00:00Z');
  const mo  = d.getUTCMonth() + 1;
  const day = d.getUTCDate();
  // 1월 실적이 2월 초로 이어지는 경우 (Q4 EPS 발표 패턴)
  if (months.includes(1) && mo === 2 && day <= 7) return true;
  if (!months.includes(mo)) return false;
  if (mo === 1)  return day >= 22;  // Q4 EPS: 1월 말
  return day >= 18;                  // Q1/Q2/Q3 EPS: 월 중하순
}

// ─── 매크로 컨텍스트 빌더 ────────────────────────────────────────────────────

function findClosestBar(arr, weekStart) {
  const t = new Date(weekStart + 'T00:00:00Z').getTime();
  let closest = null, minDiff = Infinity;
  for (const p of arr) {
    const d = Math.abs(p.ts - t);
    if (d < minDiff) { minDiff = d; closest = p; }
  }
  return (!closest || minDiff > 8 * 86400000) ? null : closest;
}

function pctChange(bar) {
  return bar && bar.open > 0
    ? Math.round((bar.close - bar.open) / bar.open * 100 * 100) / 100
    : 0;
}

/**
 * 주어진 주에 대한 전체 매크로 컨텍스트 계산
 * @param {Object} macroData - loadMacroData() 반환값
 * @param {string} weekStart - 'YYYY-MM-DD'
 * @param {Object} cfg       - ticker.json 설정 (has_delivery_reports, earnings_months 등)
 */
function buildMacroContext(macroData, weekStart, cfg = {}) {
  // 신규 키(asset/competitor) + 하위호환 구키(tsla/byd) 모두 지원
  const asset      = macroData.asset      || macroData.tsla      || [];
  const competitor = macroData.competitor || macroData.byd        || [];
  const { spy, qqq, vix, wti = [], cny = [] } = macroData;

  const spyBar        = findClosestBar(spy,        weekStart);
  const qqqBar        = findClosestBar(qqq,        weekStart);
  const vixBar        = findClosestBar(vix,        weekStart);
  const wtiBar        = findClosestBar(wti,        weekStart);
  const cnyBar        = findClosestBar(cny,        weekStart);
  const competitorBar = findClosestBar(competitor, weekStart);

  // 자산 인덱스
  const assetTs = new Date(weekStart + 'T00:00:00Z').getTime();
  let tIdx = -1, minD = Infinity;
  for (let i = 0; i < asset.length; i++) {
    const d = Math.abs(asset[i].ts - assetTs);
    if (d < minD) { minD = d; tIdx = i; }
  }
  if (minD > 8 * 86400000) tIdx = -1;

  // 경쟁사 상대강도: 자산 등락 − 경쟁사 등락 (양수 = 자산 경쟁우위)
  const assetChg       = tIdx >= 0 ? pctChange(asset[tIdx]) : null;
  const competitorChg  = competitorBar ? pctChange(competitorBar) : null;
  const competitorRelStrength = (assetChg !== null && competitorChg !== null)
    ? Math.round((assetChg - competitorChg) * 100) / 100
    : null;

  // MACD / 볼린저밴드 (충분한 데이터 있을 때만)
  let macd = null, bb = null;
  if (tIdx >= 26) {
    const macds = calcMACD(asset);
    macd = macds[tIdx];
  }
  if (tIdx >= 20) {
    const bbs = calcBollingerBands(asset);
    bb = bbs[tIdx];
  }

  // 3주 추세 (현재 주 진입 직전 3주간 누적 등락) — lookahead 없음
  let assetTrend3w = null;
  if (tIdx >= 3) {
    const baseOpen  = asset[tIdx - 3].open;
    const lastClose = asset[tIdx - 1].close;
    if (baseOpen > 0) {
      assetTrend3w = Math.round((lastClose - baseOpen) / baseOpen * 100 * 100) / 100;
    }
  }

  return {
    spyChg:      spyBar  ? pctChange(spyBar)  : 0,
    qqqChg:      qqqBar  ? pctChange(qqqBar)  : 0,
    vixClose:    vixBar  ? vixBar.close        : null,
    wtiChg:      wtiBar  ? pctChange(wtiBar)  : 0,
    cnyChg:      cnyBar  ? pctChange(cnyBar)  : 0,
    competitorChg,               // 경쟁사 주간 등락 (%)
    competitorRelStrength,       // 자산−경쟁사 상대강도 (양수=자산 우위)
    prevAssetChg: tIdx > 0 ? pctChange(asset[tIdx - 1]) : 0,
    assetTrend3w,                // 진입 직전 3주 누적 등락 (%) — 추세 필터용
    rsi:          tIdx > 14 ? calcRSI(asset, tIdx - 1) : null,
    macd,   // { macd, signal, hist, crossover, trend }
    bb,     // { upper, middle, lower, pos }
    isDeliveryWeek: isDeliveryWeek(weekStart, cfg),
    isEarningsWeek: isEarningsWeek(weekStart, cfg),
    // 하위 호환 alias (기존 저장 세션 참조용)
    bydChg:           competitorChg,
    bydRelStrength:   competitorRelStrength,
    prevTslaChg:      tIdx > 0 ? pctChange(asset[tIdx - 1]) : 0,
    tslaTrend3w:      assetTrend3w,
  };
}

// ─── v4.0: Confirmation Logic — 신호 상태 분류 ─────────────────────────────

/**
 * [v4.0 Confirmation Logic]
 * buyIndex + RSI + VIX 조합으로 7단계 신호 상태 결정
 * Strong Bull / Cautionary Bull / Bull / Neutral / Bear / Cautionary Bear / Strong Bear
 */
function getSignalState(buyIndex, macroCtx) {
  const rsi      = macroCtx?.rsi      ?? 50;
  const vix      = macroCtx?.vixClose ?? 20;
  const macdTrend = macroCtx?.macd?.trend;

  if (buyIndex >= 75) {
    // 과매수 + 공포장이면 주의 필요
    if (rsi > 75 || vix > 30) return 'cautionary_bull';
    return 'strong_bull';
  }
  if (buyIndex >= 57) {
    if (rsi > 75) return 'cautionary_bull';   // 오버바웃 진입 주의
    return 'bull';
  }
  if (buyIndex >= 44) {
    return 'neutral';
  }
  if (buyIndex >= 32) {
    // 과매도이면 반전 가능성 → 주의 약세
    if (rsi < 30 || vix > 40) return 'cautionary_bear';
    return 'bear';
  }
  // buyIndex < 32
  if (rsi < 30 && vix > 35) return 'cautionary_bear'; // 극단 공포 = 반전 가능
  return 'strong_bear';
}

/**
 * 신호 상태 → 한국어 라벨
 */
const SIGNAL_STATE_LABELS = {
  strong_bull:    { label: '강력 매수',  emoji: '🚀', color: '#22c55e',  desc: '다중 강세 신호 확인, 높은 신뢰도' },
  cautionary_bull:{ label: '주의 매수',  emoji: '⚠📈', color: '#86efac', desc: 'RSI 과매수 또는 공포장 — 진입 분할 권장' },
  bull:           { label: '매수',       emoji: '📈',  color: '#4ade80',  desc: '강세 신호 우세, 순차 진입 고려' },
  neutral:        { label: '관망',       emoji: '⏸',   color: '#f59e0b',  desc: '방향성 불명확, 추가 시그널 대기' },
  bear:           { label: '매도',       emoji: '📉',  color: '#f97316',  desc: '약세 신호 우세, 비중 축소 고려' },
  cautionary_bear:{ label: '주의 매도',  emoji: '⚠📉', color: '#fca5a5', desc: 'RSI 과매도 또는 극단 공포 — 반전 가능성 주시' },
  strong_bear:    { label: '강력 매도',  emoji: '🔻',  color: '#ef4444',  desc: '강한 하락 압력, 비중 최소화' },
};

// ─── 핵심 채점 함수 ──────────────────────────────────────────────────────────

/**
 * 다층 강화 모델 v5.0 매수지수 계산
 * @param {Object} input { avgScore, topRules, bullish, bearish, macroCtx, newsCategories }
 * @param {Object} cfg   ticker.json 설정 (beta_coefficient 등)
 * @returns {Object} { buyIndex, direction, signalState, layers }
 */
function calculateEnhancedScore(input, cfg = {}) {
  const {
    avgScore,
    topRules    = [],
    bullish     = 0,
    bearish     = 0,
    macroCtx    = null,
    newsCategories = null,  // { Financial, Earnings, Delivery, Technology, Musk, Market }
  } = input;

  const layers = {};

  // ── [Base] 원본 매수지수 ──────────────────────────────────────────────────
  let bi = Math.min(100, Math.max(0, Math.round((avgScore + 5) / 10 * 100)));
  layers.base = bi;

  // ── [14] R25 Optimus/로봇 생산·상업화 부스트 ─────────────────────────────
  const hasR25 = topRules.includes('R25');
  const hasR26 = topRules.includes('R26');
  const hasR07 = topRules.includes('R07');
  if (hasR25) {
    // Optimus 확대는 장기 고강도 긍정 촉매 (+8pt)
    const before = bi;
    bi = Math.min(100, bi + 8);
    layers.optimusBoost = bi - before;
    // R07(공장 셧다운) + R25(로봇 전환 목적) 동시 → R07 부정 효과 상쇄 (+5pt 추가)
    if (hasR07) {
      const corr = 5;
      bi = Math.min(100, bi + corr);
      layers.optimusR07Offset = corr;
    }
  }
  // R26 단독(생산 축소, 로봇 전환 언급 없음): 약한 bearish → -3pt
  // R26 + R25 동반: 이미 R25 부스트로 상쇄됨 → 추가 조정 없음
  if (hasR26 && !hasR25) {
    const before = bi;
    bi = Math.max(0, bi - 3);
    layers.prodCutPenalty = bi - before;
  }

  // ── [1] R24 단독 발동 노이즈 할인 (중립 방향으로 25% 이동) ──────────────
  const hasR08 = topRules.includes('R08');
  const hasR24 = topRules.includes('R24');
  if (hasR24 && !hasR08) {
    const before = bi;
    bi = Math.round(50 + (bi - 50) * 0.75);
    layers.r24Discount = bi - before;
  }

  // ── [2] 강한신호 증폭 (v5.0: ×1.15→×1.08 — 강세장 과신 억제) ─────────────
  const dist0 = bi - 50;
  if (Math.abs(dist0) >= 20) {
    const before = bi;
    bi = Math.max(0, Math.min(100, Math.round(50 + dist0 * 1.08)));
    layers.strongAmp = bi - before;
  }

  // ── [13] 뉴스 카테고리 가중치 (Financial/Earnings > Tech > Musk > Market) ─
  if (newsCategories) {
    let catAdj = 0;
    // Financial/Earnings 뉴스 비중이 높을수록 신호 강화
    const finWeight = ((newsCategories.Earnings || 0) + (newsCategories.Delivery || 0)) / Math.max(1, newsCategories.total || 10);
    if (finWeight >= 0.3) {
      const boost = dist0 > 0 ? +3 : dist0 < 0 ? -3 : 0;
      catAdj += boost;
      if (boost !== 0) layers.catFinancial = boost;
    }
    // Musk 관련 뉴스 비중이 과도하면 신호 약화 (노이즈)
    const muskWeight = ((newsCategories.Musk || 0)) / Math.max(1, newsCategories.total || 10);
    if (muskWeight >= 0.4) {
      const damp = dist0 > 0 ? -2 : dist0 < 0 ? +2 : 0;
      catAdj += damp;
      if (damp !== 0) layers.catMuskDamp = damp;
    }
    if (catAdj !== 0) bi = Math.max(0, Math.min(100, bi + catAdj));
  }

  // ── 매크로 컨텍스트 레이어 ────────────────────────────────────────────────
  if (macroCtx) {
    // ── [3] SPY+QQQ 매크로 오버레이 (beta: cfg.beta_coefficient) ────────────
    const beta     = cfg.beta_coefficient ?? 2.0;
    const macroAvg = ((macroCtx.spyChg || 0) + (macroCtx.qqqChg || 0)) / 2;
    if (Math.abs(macroAvg) >= 1.5) {
      const before = bi;
      bi = Math.max(0, Math.min(100, bi + Math.round(macroAvg * beta)));
      layers.macroOverlay = bi - before;
    }

    // ── [4] 전주 자산 momentum (mean reversion) ──────────────────────────────
    // 하위 호환: 신규 prevAssetChg, 또는 구키 prevTslaChg
    const prevChg = macroCtx.prevAssetChg ?? macroCtx.prevTslaChg ?? 0;
    const highVix = macroCtx.vixClose && macroCtx.vixClose > 25;
    if      (prevChg < -10 && !highVix) { bi = Math.min(100, bi + 10); layers.meanReversion = +10; }
    else if (prevChg < -10 &&  highVix) { bi = Math.min(100, bi + 4);  layers.meanReversion = +4;  }
    else if (prevChg < -5  && !highVix) { bi = Math.min(100, bi + 5);  layers.meanReversion = +5;  }
    else if (prevChg > 12)               { bi = Math.max(0,   bi - 8);  layers.meanReversion = -8;  }
    else if (prevChg > 7)                { bi = Math.max(0,   bi - 5);  layers.meanReversion = -5;  }

    // ── [5] VIX Adaptive Weighting (v4.0 강화) ─────────────────────────────
    // VIX>30: 기술지표 비중 -20%, 매크로 오버레이 비중 +40%
    if (macroCtx.vixClose && macroCtx.vixClose > 30) {
      const before = bi;
      // 신호 강도를 0.8배로 줄이는 기존 로직 유지 + 매크로 재증폭
      bi = Math.round(50 + (bi - 50) * 0.8);
      const macroBoost = Math.round(((macroCtx.spyChg || 0) + (macroCtx.qqqChg || 0)) / 2 * 1.0);
      if (macroBoost !== 0) bi = Math.max(0, Math.min(100, bi + macroBoost));
      layers.vixAdaptive = bi - before;
    }

    // ── [6] RSI 보정 ────────────────────────────────────────────────────────
    if (macroCtx.rsi !== null && macroCtx.rsi !== undefined) {
      if      (macroCtx.rsi < 30) { bi = Math.min(100, bi + 6); layers.rsiOversold  = +6; }
      else if (macroCtx.rsi > 75) { bi = Math.max(0,   bi - 4); layers.rsiOverbought = -4; }
    }

    // ── [8] MACD 크로스오버 & 방향 (v5.0: 지속트렌드 +2→+1 — 편향 감소) ────
    if (macroCtx.macd) {
      const { crossover, trend } = macroCtx.macd;
      if      (crossover === 'bullish') { bi = Math.min(100, bi + 6); layers.macdCross = +6; }
      else if (crossover === 'bearish') { bi = Math.max(0,   bi - 6); layers.macdCross = -6; }
      else if (trend === 'bullish')     { bi = Math.min(100, bi + 1); layers.macdTrend = +1; }
      else if (trend === 'bearish')     { bi = Math.max(0,   bi - 1); layers.macdTrend = -1; }
    }

    // ── [9] 볼린저밴드 위치 (v5.0: 과매수 페널티 강화) ─────────────────────
    if (macroCtx.bb) {
      const { pos } = macroCtx.bb;
      if      (pos < 0.15) { bi = Math.min(100, bi + 6); layers.bbOversold   = +6; }  // 하단 밴드 근접 = 과매도
      else if (pos < 0.30) { bi = Math.min(100, bi + 2); layers.bbLow        = +2; }
      else if (pos > 0.85) { bi = Math.max(0,   bi - 6); layers.bbOverbought = -6; }  // 과매수 강화
      else if (pos > 0.70) { bi = Math.max(0,   bi - 3); layers.bbHigh       = -3; }
    }

    // ── [10] WTI 원유 주간 등락 ──────────────────────────────────────────────
    // 비싼 원유 = EV 가치 상승, 폭락 = 경기침체 신호
    if (macroCtx.wtiChg !== undefined && macroCtx.wtiChg !== 0) {
      if      (macroCtx.wtiChg > 5)  { bi = Math.min(100, bi + 2); layers.wtiUp   = +2; }
      else if (macroCtx.wtiChg < -6) { bi = Math.max(0,   bi - 3); layers.wtiDown = -3; }
    }

    // ── [11] CNY/USD 환율 ────────────────────────────────────────────────────
    // CNY 약세(CNY=X 상승) = 중국 구매력 하락 → Tesla 중국 매출 타격
    if (macroCtx.cnyChg !== undefined && macroCtx.cnyChg !== 0) {
      if      (macroCtx.cnyChg > 1.0) { bi = Math.max(0,   bi - 3); layers.cnyWeak   = -3; }
      else if (macroCtx.cnyChg < -0.8){ bi = Math.min(100, bi + 2); layers.cnyStrong = +2; }
    }

    // ── [15] 경쟁사 상대강도 (cfg.competitor_ticker) ────────────────────────
    // 하위 호환: 신규 competitorRelStrength, 또는 구키 bydRelStrength
    const compRS = macroCtx.competitorRelStrength ?? macroCtx.bydRelStrength ?? null;
    if (compRS !== null) {
      if      (compRS <= -5) { bi = Math.max(0,   bi - 3); layers.competitorUnderperform = -3; }
      else if (compRS >=  5) { bi = Math.min(100, bi + 2); layers.competitorOutperform   = +2; }
    }

    // ── [16] 옵션 IV (라이브 전용 — 백테스트엔 atmIV 없음 → 자동 skip) ───────
    // 극단적 고변동성 = 불확실성 프리미엄 → 신호 강도 감쇠 (VIX와 유사, TSLA 고유)
    if (macroCtx.atmIV !== null && macroCtx.atmIV !== undefined) {
      if (macroCtx.atmIV > 0.80) {
        const before = bi;
        bi = Math.round(50 + (bi - 50) * 0.85);   // 신호 강도 15% 감쇠
        layers.highIV = bi - before;
      }
    }

    // ── [17] 공매도 비율 (라이브 전용 — 백테스트엔 shortPercent 없음 → skip) ─
    // 공매도 과다 + 강세 신호 = 숏스퀴즈 가능성 → 강세 증폭
    if (macroCtx.shortPercent !== null && macroCtx.shortPercent !== undefined) {
      if (macroCtx.shortPercent > 0.04 && (bi - 50) > 5) {
        bi = Math.min(100, bi + 3); layers.shortSqueeze = +3;
      }
    }

    // ── [12] 분기 인도량 / 실적 발표주 신호 증폭 (v5.0: 1.35→1.15 과신억제) ──
    if (macroCtx.isDeliveryWeek || macroCtx.isEarningsWeek) {
      const before  = bi;
      const distNow = bi - 50;
      if (Math.abs(distNow) >= 5) {
        // v5.0: MACD 방향 일치 여부로 확신도 분기
        const macdConfirms = !macroCtx.macd || (
          distNow > 0 ? macroCtx.macd.trend === 'bullish'
                      : macroCtx.macd.trend === 'bearish'
        );
        const mult = macroCtx.isEarningsWeek
          ? (macdConfirms ? 1.15 : 1.08)   // was 1.35
          : (macdConfirms ? 1.12 : 1.08);  // was 1.25
        bi = Math.round(50 + distNow * mult);
        bi = Math.max(0, Math.min(100, bi));
        const label = macroCtx.isEarningsWeek ? 'earningsWeek' : 'deliveryWeek';
        layers[label] = bi - before;
      }
    }

    // ── [18] 추세 필터 (v5.0 — 뉴스 감성과 독립된 가격 추세 신호) ────────────
    // 하위 호환: 신규 assetTrend3w, 또는 구키 tslaTrend3w
    const trend3w = macroCtx.assetTrend3w ?? macroCtx.tslaTrend3w ?? null;
    if (trend3w !== null) {
      const t = trend3w;
      const before = bi;
      if      (t < -5 && avgScore < 2)   { bi = Math.max(0, bi - 12); }
      else if (t < -3 && avgScore < 1.5) { bi = Math.max(0, bi - 6);  }
      else if (t > 10)                   { bi = Math.max(0, bi - 6);  }
      if (bi !== before) layers.trendFilter = bi - before;
    }
  }

  bi = Math.max(0, Math.min(100, Math.round(bi)));

  // ── [7] 방향 결정 — v5.0: 중립밴드 도입 (약신호 neutral 허용) ────────────
  let direction;
  if (bi >= 58) {
    direction = 'bullish';
  } else if (bi <= 42) {
    direction = 'bearish';
  } else {
    // 중립밴드 (43-57): 신호가 약하면 neutral 허용
    const margin = bullish - bearish;
    if (Math.abs(avgScore) < 0.4 && Math.abs(margin) <= 1) {
      // avgScore가 거의 0이고 뉴스 방향도 박빙 → neutral
      direction = 'neutral';
    } else {
      direction = margin > 0 ? 'bullish'
                : margin < 0 ? 'bearish'
                : (avgScore < 0 ? 'bearish' : avgScore > 0 ? 'bullish' : 'neutral');
    }
  }

  // ── [v4.0] Confirmation Logic — 신호 상태 분류 ───────────────────────────
  const signalState = getSignalState(bi, macroCtx);

  return { buyIndex: bi, direction, signalState, layers };
}

// ─── 설정 로더 (Node.js 전용) ──────────────────────────────────────────────

function loadTickerConfig(cfgPath) {
  const { loadTickerConfig: _load } = require('./prompt');
  return _load(cfgPath);
}

function loadRulesConfig(cfgPath) {
  const { loadRulesConfig: _load } = require('./prompt');
  return _load(cfgPath);
}

module.exports = {
  fetchYahooWeekly,
  loadMacroData,
  fetchOptionsIV,
  fetchShortInterest,
  buildMacroContext,
  calculateEnhancedScore,
  getSignalState,
  SIGNAL_STATE_LABELS,
  calcMACD,
  calcBollingerBands,
  calcRSI,
  calcEMA,
  isDeliveryWeek,
  isEarningsWeek,
  findClosestBar,
  pctChange,
  loadTickerConfig,
  loadRulesConfig,
};
