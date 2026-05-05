/**
 * TSLA 다층 강화 채점 모델 v3.0 (백테스트 검증 기반)
 *
 * 레이어 구조:
 *   [Base] 원본 매수지수 (avgScore → buyIndex)
 *   [1]  R24 단독 발동 노이즈 할인 (+9pt)
 *   [2]  강한신호 증폭 (±20 이탈 시 ×1.15)
 *   [3]  매크로 오버레이 (SPY+QQQ 평균 × Tesla beta 2.5)
 *   [4]  전주 TSLA momentum (mean reversion)
 *   [5]  VIX regime (>30 공포장 → 신호 강도 ×0.8)
 *   [6]  RSI 14주 (과매도/과매수 보정)
 *   [7]  neutral 제거 → avgScore tie-break
 *   [8]  MACD (12/26/9) 크로스오버 & 방향 — NEW
 *   [9]  볼린저밴드 위치 (20주) — NEW
 *   [10] WTI 원유 주간 등락 — NEW
 *   [11] CNY/USD 환율 — NEW
 *   [12] 분기 인도량 발표주 신호 증폭 (×1.25) — NEW
 *   [13] 뉴스 카테고리 가중치 (Financial > Tech > Market) — NEW
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

async function loadMacroData() {
  const [spy, qqq, vix, tsla, wti, cny] = await Promise.all([
    fetchYahooWeekly('SPY'),
    fetchYahooWeekly('QQQ'),
    fetchYahooWeekly('^VIX'),
    fetchYahooWeekly('TSLA'),
    fetchYahooWeekly('CL=F'),   // WTI 원유 (EV 수요 연관)
    fetchYahooWeekly('CNY=X'),  // CNY/USD 환율 (중국 매출 영향)
  ]);
  return { spy, qqq, vix, tsla, wti, cny };
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

// ─── 분기 인도량 발표주 판별 ─────────────────────────────────────────────────

/**
 * 해당 주가 테슬라 분기 인도량 발표 주간인지 확인
 * (매 분기 1~5영업일 = 1월 첫주, 4월 첫주, 7월 첫주, 10월 첫주)
 */
function isDeliveryWeek(weekStart) {
  const d   = new Date(weekStart + 'T00:00:00Z');
  const mo  = d.getUTCMonth() + 1; // 1~12
  const day = d.getUTCDate();
  // 분기 첫 주 (1·4·7·10월의 1~7일)
  return [1, 4, 7, 10].includes(mo) && day <= 7;
}

/**
 * 해당 주가 테슬라 실적 발표(EPS) 주간인지 확인
 * (1월 마지막 주 ~ 2월 첫째 주, 4월 마지막 주, 7월 마지막 주, 10월 마지막 주)
 */
function isEarningsWeek(weekStart) {
  const d   = new Date(weekStart + 'T00:00:00Z');
  const mo  = d.getUTCMonth() + 1;
  const day = d.getUTCDate();
  return (mo === 1  && day >= 22) ||  // Q4 EPS: 1월 말
         (mo === 2  && day <= 7)  ||  // Q4 EPS 이어지는 경우
         (mo === 4  && day >= 18) ||  // Q1 EPS: 4월 말
         (mo === 7  && day >= 18) ||  // Q2 EPS: 7월 말
         (mo === 10 && day >= 15);    // Q3 EPS: 10월 중하순
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
 */
function buildMacroContext(macroData, weekStart) {
  const { spy, qqq, vix, tsla, wti = [], cny = [] } = macroData;

  const spyBar = findClosestBar(spy,  weekStart);
  const qqqBar = findClosestBar(qqq,  weekStart);
  const vixBar = findClosestBar(vix,  weekStart);
  const wtiBar = findClosestBar(wti,  weekStart);
  const cnyBar = findClosestBar(cny,  weekStart);

  // TSLA 인덱스
  const tslaTs = new Date(weekStart + 'T00:00:00Z').getTime();
  let tIdx = -1, minD = Infinity;
  for (let i = 0; i < tsla.length; i++) {
    const d = Math.abs(tsla[i].ts - tslaTs);
    if (d < minD) { minD = d; tIdx = i; }
  }
  if (minD > 8 * 86400000) tIdx = -1;

  // MACD / 볼린저밴드 (충분한 데이터 있을 때만)
  let macd = null, bb = null;
  if (tIdx >= 26) {
    const macds = calcMACD(tsla);
    macd = macds[tIdx];
  }
  if (tIdx >= 20) {
    const bbs = calcBollingerBands(tsla);
    bb = bbs[tIdx];
  }

  return {
    spyChg:      spyBar  ? pctChange(spyBar)  : 0,
    qqqChg:      qqqBar  ? pctChange(qqqBar)  : 0,
    vixClose:    vixBar  ? vixBar.close        : null,
    wtiChg:      wtiBar  ? pctChange(wtiBar)  : 0,
    cnyChg:      cnyBar  ? pctChange(cnyBar)  : 0,
    prevTslaChg: tIdx > 0 ? pctChange(tsla[tIdx - 1]) : 0,
    rsi:         tIdx > 14 ? calcRSI(tsla, tIdx - 1) : null,
    macd,   // { macd, signal, hist, crossover, trend }
    bb,     // { upper, middle, lower, pos }
    isDeliveryWeek: isDeliveryWeek(weekStart),
    isEarningsWeek: isEarningsWeek(weekStart),
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
 * 다층 강화 모델 v4.0 매수지수 계산
 * @param {Object} input { avgScore, topRules, bullish, bearish, macroCtx, newsCategories }
 * @returns {Object} { buyIndex, direction, signalState, layers }
 */
function calculateEnhancedScore(input) {
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

  // ── [1] R24 단독 발동 노이즈 할인 (중립 방향으로 25% 이동) ──────────────
  const hasR08 = topRules.includes('R08');
  const hasR24 = topRules.includes('R24');
  if (hasR24 && !hasR08) {
    const before = bi;
    bi = Math.round(50 + (bi - 50) * 0.75);
    layers.r24Discount = bi - before;
  }

  // ── [2] 강한신호 증폭 ─────────────────────────────────────────────────────
  const dist0 = bi - 50;
  if (Math.abs(dist0) >= 20) {
    const before = bi;
    bi = Math.max(0, Math.min(100, Math.round(50 + dist0 * 1.15)));
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
    // ── [3] SPY+QQQ 매크로 오버레이 ────────────────────────────────────────
    const macroAvg = ((macroCtx.spyChg || 0) + (macroCtx.qqqChg || 0)) / 2;
    if (Math.abs(macroAvg) >= 1.5) {
      const before = bi;
      bi = Math.max(0, Math.min(100, bi + Math.round(macroAvg * 2.5)));
      layers.macroOverlay = bi - before;
    }

    // ── [4] 전주 TSLA momentum (mean reversion) ─────────────────────────────
    if (macroCtx.prevTslaChg < -10) { bi = Math.min(100, bi + 10); layers.meanReversion = +10; }
    else if (macroCtx.prevTslaChg > 12) { bi = Math.max(0, bi - 6); layers.meanReversion = -6; }

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

    // ── [8] MACD 크로스오버 & 방향 ─────────────────────────────────────────
    if (macroCtx.macd) {
      const { crossover, trend } = macroCtx.macd;
      if      (crossover === 'bullish') { bi = Math.min(100, bi + 6); layers.macdCross = +6; }
      else if (crossover === 'bearish') { bi = Math.max(0,   bi - 6); layers.macdCross = -6; }
      else if (trend === 'bullish')     { bi = Math.min(100, bi + 2); layers.macdTrend = +2; }
      else if (trend === 'bearish')     { bi = Math.max(0,   bi - 2); layers.macdTrend = -2; }
    }

    // ── [9] 볼린저밴드 위치 ─────────────────────────────────────────────────
    if (macroCtx.bb) {
      const { pos } = macroCtx.bb;
      if      (pos < 0.15) { bi = Math.min(100, bi + 6); layers.bbOversold   = +6; }  // 하단 밴드 근접 = 과매도
      else if (pos < 0.30) { bi = Math.min(100, bi + 2); layers.bbLow        = +2; }
      else if (pos > 0.85) { bi = Math.max(0,   bi - 4); layers.bbOverbought = -4; }  // 상단 밴드 근접 = 과매수
      else if (pos > 0.70) { bi = Math.max(0,   bi - 2); layers.bbHigh       = -2; }
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

    // ── [12] 분기 인도량 / 실적 발표주 신호 증폭 (v4.0: Earnings ×1.5) ───────
    if (macroCtx.isDeliveryWeek || macroCtx.isEarningsWeek) {
      const before  = bi;
      const distNow = bi - 50;
      if (Math.abs(distNow) >= 5) {
        // v4.0: Earnings Week는 뉴스 Base Score 1.5배 → 신호 증폭 ×1.35
        const mult  = macroCtx.isEarningsWeek ? 1.35 : 1.25;
        bi = Math.round(50 + distNow * mult);
        bi = Math.max(0, Math.min(100, bi));
        const label = macroCtx.isEarningsWeek ? 'earningsWeek' : 'deliveryWeek';
        layers[label] = bi - before;
      }
    }
  }

  bi = Math.max(0, Math.min(100, Math.round(bi)));

  // ── [7] 방향 결정 — neutral 제거, avgScore tie-break ─────────────────────
  let direction;
  if      (bi >= 57) direction = 'bullish';
  else if (bi <= 43) direction = 'bearish';
  else direction = bullish > bearish ? 'bullish'
                 : bearish > bullish ? 'bearish'
                 : (avgScore < 0 ? 'bearish' : 'bullish');

  // ── [v4.0] Confirmation Logic — 신호 상태 분류 ───────────────────────────
  const signalState = getSignalState(bi, macroCtx);

  return { buyIndex: bi, direction, signalState, layers };
}

module.exports = {
  fetchYahooWeekly,
  loadMacroData,
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
};
