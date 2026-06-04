/**
 * 자동 뉴스 수집 & 분석 스크립트 (멀티 종목 지원)
 * GitHub Actions에서 하루 4회 실행 (KST 03:00 / 09:00 / 15:00 / 21:00)
 * Node.js 20+ 내장 fetch 사용 (별도 패키지 불필요)
 */

const fs   = require('fs');
const path = require('path');
const { loadMacroData, buildMacroContext, calculateEnhancedScore, fetchOptionsIV, fetchShortInterest } = require('./lib/scoring');
const { loadTickerConfig, loadRulesConfig, buildSystemPrompt } = require('./lib/prompt');

const cfg      = loadTickerConfig();
const rulesData = loadRulesConfig();
const TICKER    = cfg.ticker;
const COMPANY_KO = cfg.company_ko;

const API_KEY = process.env.GEMINI_API_KEY;
if (!API_KEY) { console.error('❌ GEMINI_API_KEY 환경변수가 없습니다.'); process.exit(1); }

// 기본 모델 + 과부하 시 폴백 모델
const MODELS = [
  'gemini-2.5-flash',
  'gemini-2.0-flash',
  'gemini-1.5-flash',
];
const makeUrl = m => `https://generativelanguage.googleapis.com/v1beta/models/${m}:generateContent?key=${API_KEY}`;
const GEMINI_URL = makeUrl(MODELS[0]); // 기본값 (하위 호환용)
const DATA_FILE  = path.join(__dirname, '..', 'data', 'auto-sessions.json');
const MAX_SESSIONS = 90; // 최대 90개 (약 3주치)

// ─── 시스템 프롬프트 (config/rules.json + config/ticker.json 기반 동적 생성) ──

const SYSTEM_PROMPT = buildSystemPrompt(cfg, rulesData);

// ─── 유틸 ────────────────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function getTopRules(analyses) {
  const cnt = {};
  analyses.forEach(a => (a?.triggered_rules || []).forEach(r => { cnt[r] = (cnt[r] || 0) + 1; }));
  return Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([r]) => r);
}

async function geminiPost(body, retries = 7) {
  let lastError;
  // 모델 순서: 0-3회→gemini-2.5-flash, 4-5회→gemini-2.0-flash, 6+회→gemini-1.5-flash
  for (let attempt = 0; attempt <= retries; attempt++) {
    const modelIdx = attempt < 4 ? 0 : attempt < 6 ? 1 : 2;
    const model = MODELS[modelIdx];
    const url = makeUrl(model);
    // thinkingConfig는 gemini-2.5-flash(thinking 지원 모델)에서만 유효 — 폴백 시 제거
    let actualBody = body;
    if (modelIdx > 0 && body.generationConfig?.thinkingConfig) {
      const { thinkingConfig, ...restGen } = body.generationConfig;
      actualBody = { ...body, generationConfig: restGen };
    }
    try {
      const res = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(actualBody) });
      if (res.ok) {
        if (modelIdx > 0) console.log(`   ✅ 폴백 모델 ${model} 성공`);
        return res.json();
      }
      const e = await res.json().catch(() => ({}));
      const msg = e?.error?.message || `HTTP ${res.status}`;
      const retryable = res.status === 503 || res.status === 429 || res.status === 500 || res.status === 529;
      if (!retryable) throw new Error(msg);
      lastError = new Error(msg);
    } catch (fetchErr) {
      if (fetchErr.message.includes('HTTP ') || fetchErr.message.includes('503') || fetchErr.message.includes('429')) {
        lastError = fetchErr;
      } else throw fetchErr;
    }
    if (attempt < retries) {
      // 지수 백오프: 10s → 20s → 40s → 60s(폴백 전환) → 60s → 60s → 60s
      const baseDelay = attempt < 3
        ? Math.min(10000 * Math.pow(2, attempt), 60000)
        : 60000;
      const delay = baseDelay + Math.random() * 5000;
      console.warn(`   ⏳ 과부하(${model}), ${Math.round(delay/1000)}초 후 재시도 (${attempt + 1}/${retries})...`);
      await sleep(delay);
    }
  }
  throw lastError;
}

// ─── 뉴스 수집 (Google Search Grounding) ────────────────────────────────────

async function collectNews() {
  const today = new Date().toISOString().split('T')[0];
  const keyPeopleStr = (cfg.key_people || []).join(' and ');
  const data = await geminiPost({
    tools: [{ google_search: {} }],
    contents: [{
      role: 'user',
      parts: [{ text: `[필수 규칙] title과 summary는 반드시 한국어(Korean)로 작성. 영어 원문은 한국어로 번역할 것. source·category만 영어 유지.\n\nSearch for the latest ${cfg.company_en} (${TICKER}) and ${keyPeopleStr} news from today or past 24 hours that could impact ${TICKER} stock.\nOnly include articles from major financial/tech news outlets: Reuters, Bloomberg, CNBC, Wall Street Journal, Financial Times, Associated Press, MarketWatch, Barron's, Seeking Alpha, Electrek, The Verge, TechCrunch, Forbes, CNN Business, Fox Business.\nReturn ONLY a JSON array of exactly 10 most market-impactful items, strictly no duplicates, each from a different angle or event:\n[{"id":1,"title":"(한국어 번역 제목 예: ${cfg.company_ko}, 1분기 실적 예상치 하회)","summary":"(한국어 2~3문장 요약)","source":"Reuters","date":"${today}","category":"Earnings|Delivery|Product|Competition|Regulatory|Macro|Energy|Market|Legal"}]\n⚠️ title·summary에 영어 사용 절대 금지. 반드시 한국어로만 작성.\nReturn ONLY the JSON array, no other text.` }],
    }],
    generationConfig: { maxOutputTokens: 8192, temperature: 0.1, thinkingConfig: { thinkingBudget: 0 } },
  });
  const parts  = data.candidates?.[0]?.content?.parts || [];
  const raw    = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
  const clean  = raw.replace(/```json\s*/gi, '').replace(/```\s*/g, '').trim();
  const s = clean.indexOf('['), e = clean.lastIndexOf(']');
  if (s === -1 || e === -1) throw new Error('뉴스 JSON 파싱 실패: ' + raw.slice(0, 200));
  const items = JSON.parse(clean.slice(s, e + 1));
  return items.slice(0, 10).map((n, i) => ({ ...n, id: Date.now() + i }));
}

// ─── 개별 뉴스 분석 ──────────────────────────────────────────────────────────

async function analyzeNewsItem(newsItem) {
  const userContent = `Analyze this ${cfg.company_en}-related news for ${TICKER} stock impact:\n\nTitle: ${newsItem.title}\n\nSummary: ${newsItem.summary}\n\nSource: ${newsItem.source} | Date: ${newsItem.date} | Category: ${newsItem.category}`;
  const data = await geminiPost({
    system_instruction: { parts: [{ text: SYSTEM_PROMPT }] },
    contents: [{ role: 'user', parts: [{ text: userContent }] }],
    generationConfig: {
      responseMimeType: 'application/json',
      maxOutputTokens: 600,
      temperature: 0.2,
      thinkingConfig: { thinkingBudget: 0 },
    },
  });
  const parts = data.candidates?.[0]?.content?.parts || [];
  const raw   = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
  const clean = raw.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim();
  const m = clean.match(/\{[\s\S]*\}/);
  if (!m) throw new Error('JSON 파싱 실패: ' + raw.slice(0, 100));
  return JSON.parse(m[0]);
}

// ─── 핵심 인물 X 센티먼트 수집 (Gemini Search Grounding) ─────────────────────

async function collectKeyPersonSentiment(dateStr) {
  const people    = cfg.key_people || ['Elon Musk'];
  const handles   = people.map(p => `@${p.replace(/\s+/g, '')}`).join(', ');
  const topics    = `${cfg.ticker}, ${cfg.company_en}, stock`;
  try {
    const data = await geminiPost({
      tools: [{ google_search: {} }],
      contents: [{
        role: 'user',
        parts: [{ text: `Search X (Twitter) and web for ${handles} posts from the past 7 days (around ${dateStr}) related to ${topics}.\nAnalyze the overall tone and sentiment of their recent public communications about ${cfg.company_en}.\nReturn ONLY JSON:\n{"posts":[{"date":"YYYY-MM-DD","content":"(한국어 내용 요약)","sentiment":"bullish|bearish|neutral","engagement":"high|medium|low"}],"overall_sentiment":"bullish|bearish|neutral","sentiment_score":<integer -3 to +3>,"post_count":<number of found posts>,"reasoning":"(한국어 한 문장 설명)"}\nCRITICAL: Return ONLY the JSON object.` }],
      }],
      generationConfig: { maxOutputTokens: 1024, temperature: 0.1, thinkingConfig: { thinkingBudget: 0 } },
    });
    const parts = data.candidates?.[0]?.content?.parts || [];
    const raw   = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
    const clean = raw.replace(/```json\s*/gi, '').replace(/```\s*/g, '').trim();
    const m = clean.match(/\{[\s\S]*\}/);
    if (!m) return null;
    const result = JSON.parse(m[0]);
    console.log(`   🐦 ${people[0]} X: 센티먼트 ${result.overall_sentiment} (${result.sentiment_score >= 0 ? '+' : ''}${result.sentiment_score}) | 포스트 ${result.post_count || '?'}건`);
    return result;
  } catch (e) {
    console.warn(`   ⚠ 핵심 인물 X 센티먼트 수집 실패: ${e.message}`);
    return null;
  }
}

// ─── 구글 트렌드 수집 (Gemini Search Grounding) ──────────────────────────────

async function collectGoogleTrends(dateStr) {
  try {
    const data = await geminiPost({
      tools: [{ google_search: {} }],
      contents: [{
        role: 'user',
        parts: [{ text: `Search Google Trends data for the keyword "Tesla" in the United States for the past 7 days (around ${dateStr}).

Find the current relative search interest score (0-100 scale, where 100 = peak popularity for the time period), whether the trend is rising, stable, or falling compared to the prior week, and any breakout/spike in search interest.

Return ONLY JSON:
{"current_score":<0-100>,"week_avg":<0-100>,"trend":"rising|stable|falling","spike":true|false,"top_queries":["query1","query2","query3"],"reasoning":"(한국어 한 문장 설명)"}
CRITICAL: Return ONLY the JSON object.` }],
      }],
      generationConfig: { maxOutputTokens: 512, temperature: 0.1, thinkingConfig: { thinkingBudget: 0 } },
    });
    const parts = data.candidates?.[0]?.content?.parts || [];
    const raw   = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
    const clean = raw.replace(/```json\s*/gi, '').replace(/```\s*/g, '').trim();
    const m = clean.match(/\{[\s\S]*\}/);
    if (!m) return null;
    const result = JSON.parse(m[0]);
    const trendEmoji = result.trend === 'rising' ? '↑' : result.trend === 'falling' ? '↓' : '→';
    console.log(`   📈 구글 트렌드: ${result.current_score}/100 ${trendEmoji} (${result.trend})${result.spike ? ' 🔥급등' : ''}`);
    return result;
  } catch (e) {
    console.warn(`   ⚠ 구글 트렌드 수집 실패: ${e.message}`);
    return null;
  }
}

// ─── D+1~D+5 일별 예측 생성 (예측 정확도 추적용) ────────────────────────────

async function generateDailyForecast(buyIndex, avgScore, macroCtx, dateStr, recentBuyIndexes = []) {
  try {
    const dayNames = ['일','월','화','수','목','금','토'];
    const dayRows = Array.from({ length: 5 }, (_, i) => {
      const d = new Date(Date.now() + (i + 1) * 86400000);
      const day = d.getUTCDay();
      if (day === 6) d.setUTCDate(d.getUTCDate() + 2);
      else if (day === 0) d.setUTCDate(d.getUTCDate() + 1);
      const label = i === 0 ? '내일' : `D+${i + 1}`;
      const dateLabel = `${d.getUTCMonth()+1}/${d.getUTCDate()}(${dayNames[d.getUTCDay()]})`;
      return `  {"day":${i+1},"label":"${label}","date":"${dateLabel}","change_pct":<float -5.0 to +5.0>,"signal":"<매수|관망|매도>"}`;
    }).join(',\n');

    const macroSummary = macroCtx
      ? `SPY:${macroCtx.spyChg >= 0 ? '+' : ''}${macroCtx.spyChg}% QQQ:${macroCtx.qqqChg >= 0 ? '+' : ''}${macroCtx.qqqChg}% VIX:${macroCtx.vixClose} RSI:${macroCtx.rsi ?? '-'} MACD:${macroCtx.macd?.trend || '-'}`
      : 'N/A';

    // 추세 계산 (최근 세션 buyIndex 기반)
    const trendHistory = [buyIndex, ...recentBuyIndexes].slice(0, 7);
    let trendRule = '';
    if (trendHistory.length >= 3) {
      const oldest    = trendHistory[trendHistory.length - 1];
      const delta     = buyIndex - oldest;
      const dir       = delta >  8 ? 'RISING' : delta < -8 ? 'FALLING' : 'FLAT';
      const speed     = Math.abs(delta) > 20 ? 'fast' : Math.abs(delta) > 10 ? 'moderate' : 'slow';
      const histStr   = [...trendHistory].reverse().join(' → ');
      const weeklySum = dir === 'FALLING' && speed === 'fast' ? '−3% ~ +2%'
                      : dir === 'FALLING'                     ? '−1% ~ +2%'
                      : dir === 'FLAT'                        ? '−2% ~ +3%'
                      : speed === 'fast'                      ? '+5% ~ +10%'
                      :                                         '+2% ~ +5%';
      trendRule = `\nBuyIndex trend (oldest→newest): ${histStr}
Trend: ${dir} (${delta >= 0 ? '+' : ''}${delta} pts, ${speed})
${dir === 'FALLING'
  ? `RULE: D+3~5 MUST converge toward 0%. ${speed === 'fast' ? 'At least 2 of D+3~5 should be ≤ 0%.' : 'D+4~5 should be near ±0.5%.'}
DO NOT predict all 5 days uniformly positive.`
  : dir === 'RISING'
  ? `RULE: positive bias appropriate across days.`
  : `RULE: cluster near ±0.5% — no strong directional bias.`}
7-day cumulative sum guideline: ${weeklySum}`;
    }

    const data = await geminiPost({
      system_instruction: { parts: [{ text: `You are a ${TICKER} stock prediction AI. Return ONLY valid JSON with no explanation.` }] },
      contents: [{ role: 'user', parts: [{ text: `${TICKER} Analysis (${dateStr}):
- buyIndex: ${buyIndex}/100 (≥65=bullish, 45-64=neutral, ≤44=bearish)
- avgNewsScore: ${avgScore >= 0 ? '+' : ''}${avgScore} (range -5 to +5)
- Macro: ${macroSummary}
${trendRule}

Predict ${TICKER} daily closing price change % for the next 5 trading days (skip weekends).
Rules: Be conservative — typical daily range is -3% to +3%. Use ±1~2% for normal signals.
Negative days are realistic — include them when trend warrants.
signal: "매수" if change_pct > 0.8, "매도" if change_pct < -0.8, else "관망"

Return ONLY this JSON (no markdown):
{"daily_forecasts":[
${dayRows}
]}` }] }],
      generationConfig: {
        responseMimeType: 'application/json',
        maxOutputTokens: 512,
        temperature: 0.3,
        thinkingConfig: { thinkingBudget: 0 },
      },
    });
    const parts = data.candidates?.[0]?.content?.parts || [];
    const raw   = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
    const clean = raw.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim();
    const m = clean.match(/\{[\s\S]*\}/);
    if (!m) return null;
    const result = JSON.parse(m[0]);
    const forecasts = result.daily_forecasts || [];
    const preview = forecasts.map(f => `${f.label}:${f.change_pct >= 0 ? '+' : ''}${f.change_pct}%`).join(' ');
    console.log(`   🔮 D+1~D+5 예측: ${preview}`);
    return forecasts;
  } catch (e) {
    console.warn(`   ⚠ 일별 예측 생성 실패: ${e.message}`);
    return null;
  }
}

// ─── 메인 ────────────────────────────────────────────────────────────────────

async function main() {
  // KST 시간 (UTC+9)
  const nowKST  = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const kstStr  = nowKST.toISOString().replace('T', ' ').slice(0, 16) + ' KST';
  const dateStr = nowKST.toISOString().split('T')[0];
  const timeStr = nowKST.toISOString().slice(11, 16);

  console.log(`\n🚀 ${TICKER} 자동 분석 시작: ${kstStr}`);
  console.log('━'.repeat(60));

  // 1. 뉴스 수집
  console.log('\n📰 뉴스 수집 중 (Google Search Grounding)...');
  const newsItems = await collectNews();
  console.log(`   ✅ ${newsItems.length}건 수집 완료`);

  // 1-2. 핵심 인물 X 센티먼트 수집
  console.log('\n🐦 핵심 인물 X 센티먼트 수집 중...');
  const muskXData = await collectKeyPersonSentiment(dateStr);
  console.log('');

  // 1-3. 구글 트렌드 수집
  console.log('📈 구글 트렌드 수집 중...');
  const trendsData = await collectGoogleTrends(dateStr);
  console.log('');

  // 1-4. YouTube 관심도 데이터 로드 (youtube_sentiment.py 실행 결과)
  let youtubeData = null;
  try {
    const ytFile = path.join(__dirname, '..', 'data', 'youtube-sentiment.json');
    if (fs.existsSync(ytFile)) {
      youtubeData = JSON.parse(fs.readFileSync(ytFile, 'utf-8'));
      if (typeof youtubeData.score === 'number' && youtubeData.video_count > 0) {
        console.log(`📺 YouTube 관심도: ${youtubeData.score >= 0 ? '+' : ''}${youtubeData.score} (${youtubeData.video_count}개 영상, 총 ${(youtubeData.total_views || 0).toLocaleString()}회)`);
      }
    }
  } catch (e) {
    console.warn('   ⚠ YouTube 데이터 로드 실패:', e.message);
  }

  // 2. 개별 뉴스 분석 (Rate limit: 1.2초 간격)
  console.log('🔍 뉴스 분석 중...');
  const analyses = {};
  let failCount  = 0;

  for (let i = 0; i < newsItems.length; i++) {
    const news = newsItems[i];
    try {
      const result = await analyzeNewsItem(news);
      analyses[news.id] = result;
      const score = result.impact_score;
      const dir   = result.direction === 'bullish' ? '📈' : result.direction === 'bearish' ? '📉' : '➡';
      console.log(`   [${String(i+1).padStart(2,'0')}/${newsItems.length}] ${dir} ${score >= 0 ? '+' : ''}${score}  ${news.title.slice(0, 55)}`);
    } catch (e) {
      failCount++;
      console.error(`   [${String(i+1).padStart(2,'0')}/${newsItems.length}] ⚠ 실패: ${e.message}`);
    }
    if (i < newsItems.length - 1) await sleep(1200);
  }

  // 3. 집계
  const analyzed = newsItems.filter(n => analyses[n.id]);
  if (analyzed.length === 0) throw new Error('분석 성공 건수 0건 — 세션 저장 중단');

  const scores   = analyzed.map(n => analyses[n.id].impact_score);
  const avgScore = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length * 10) / 10;
  const bullish  = analyzed.filter(n => analyses[n.id].direction === 'bullish').length;
  const bearish  = analyzed.filter(n => analyses[n.id].direction === 'bearish').length;
  const topRules = getTopRules(analyzed.map(n => analyses[n.id]));

  // 뉴스 카테고리 집계 (Grok 제안 #2)
  const newsCategories = { total: analyzed.length };
  analyzed.forEach(n => { const c = n.category || 'Market'; newsCategories[c] = (newsCategories[c] || 0) + 1; });

  // ── 다층 강화 채점 모델 v3.0 (백테스트 ±2% 이상 주 72%) ─────────────────
  let macroCtx = null;
  let latestPrice = null;   // dailyForecasts basePrice 계산용
  try {
    console.log(`   📊 매크로 컨텍스트 로드 중 (SPY/QQQ/VIX/${TICKER}/WTI/CNY)...`);
    const macroData = await loadMacroData(cfg);
    macroCtx = buildMacroContext(macroData, dateStr, cfg);
    // 최신 주봉 종가 → 일별 예측 기준가로 사용
    const assetArr = macroData.asset || macroData.tsla || [];
    if (assetArr.length) {
      latestPrice = Math.round(assetArr[assetArr.length - 1].close * 100) / 100;
    }
    const wtiStr  = macroCtx.wtiChg >= 0 ? '+' : '';
    const cnyStr  = macroCtx.cnyChg >= 0 ? '+' : '';
    const macdStr = macroCtx.macd?.crossover ? `MACD ${macroCtx.macd.crossover}` : `MACD ${macroCtx.macd?.trend || '-'}`;
    const bbStr   = macroCtx.bb ? `BB:${Math.round(macroCtx.bb.pos*100)}%` : '';
    const compRS  = macroCtx.competitorRelStrength ?? macroCtx.bydRelStrength;
    const compStr = compRS !== null && compRS !== undefined
      ? ` ${cfg.competitor_ticker || 'COMP'}-RS:${compRS >= 0 ? '+' : ''}${compRS}%` : '';
    console.log(`   ✅ SPY:${macroCtx.spyChg >= 0 ? '+' : ''}${macroCtx.spyChg}% QQQ:${macroCtx.qqqChg >= 0 ? '+' : ''}${macroCtx.qqqChg}% VIX:${macroCtx.vixClose} WTI:${wtiStr}${macroCtx.wtiChg}% CNY:${cnyStr}${macroCtx.cnyChg}% RSI:${macroCtx.rsi} ${macdStr} ${bbStr}${compStr}${latestPrice ? ` ${TICKER}:$${latestPrice}` : ''}`);

    // ── 라이브 전용 스냅샷: 옵션 IV + 공매도 비율 (과거 데이터 없어 백테스트 미적용) ──
    const [atmIV, shortPercent] = await Promise.all([
      fetchOptionsIV(TICKER),
      fetchShortInterest(TICKER),
    ]);
    if (atmIV !== null)        macroCtx.atmIV = atmIV;
    if (shortPercent !== null) macroCtx.shortPercent = shortPercent;
    const ivStr = atmIV !== null ? ` IV:${Math.round(atmIV*100)}%` : '';
    const siStr = shortPercent !== null ? ` Short:${Math.round(shortPercent*1000)/10}%` : '';
    if (ivStr || siStr) console.log(`   ✅ 라이브 스냅샷${ivStr}${siStr}`);
  } catch (e) {
    console.warn('   ⚠ 매크로 데이터 로드 실패 — 기본 채점만 적용:', e.message);
  }

  // 머스크 X 센티먼트를 buyIndex에 반영 (독립 신호)
  let muskXAdj = 0;
  if (muskXData && typeof muskXData.sentiment_score === 'number') {
    // -3~+3 → -4~+4pt 범위로 변환 (R08/R24보다 약하게)
    muskXAdj = Math.round(muskXData.sentiment_score * 1.3);
    console.log(`   🐦 머스크 X 보정: ${muskXAdj >= 0 ? '+' : ''}${muskXAdj}pt (원점수: ${muskXData.sentiment_score})`);
  }

  const enhanced = calculateEnhancedScore({ avgScore, topRules, bullish, bearish, macroCtx, newsCategories }, cfg);

  // 구글 트렌드 보정 (소매 관심도 신호 — 방향 증폭기)
  let trendsAdj = 0;
  if (trendsData && trendsData.trend) {
    if (trendsData.trend === 'rising') trendsAdj += 2;
    else if (trendsData.trend === 'falling') trendsAdj -= 1;
    // 급등 시 기존 방향 증폭 (나쁜 뉴스 바이럴도 있으므로 방향 독립 적용 안 함)
    if (trendsData.spike) trendsAdj += Math.sign(avgScore || (enhanced.buyIndex - 50)) * 2;
    trendsAdj = Math.max(-4, Math.min(4, trendsAdj));
    console.log(`   📈 구글 트렌드 보정: ${trendsAdj >= 0 ? '+' : ''}${trendsAdj}pt (${trendsData.trend}${trendsData.spike ? ' 급등' : ''})`);
  }

  // YouTube 관심도 보정 (소매 투자자 관심 신호 — 방향 증폭기, 범위 -3 ~ +3)
  let youtubeAdj = 0;
  if (youtubeData && typeof youtubeData.score === 'number' && youtubeData.video_count > 0) {
    // score(-3~+3) → adj(-3~+3)pt: 구글 트렌드보다 약하게, 방향성 보조 신호로 사용
    youtubeAdj = Math.max(-3, Math.min(3, youtubeData.score));
    console.log(`   📺 YouTube 관심도 보정: ${youtubeAdj >= 0 ? '+' : ''}${youtubeAdj}pt (${youtubeData.velocity_label || ''})`);
  }

  let buyIndex    = Math.max(0, Math.min(100, enhanced.buyIndex + muskXAdj + trendsAdj + youtubeAdj));
  const direction = buyIndex >= 57 ? 'bullish' : buyIndex <= 43 ? 'bearish' : enhanced.direction;
  const scoringLayers = {
    ...enhanced.layers,
    ...(muskXAdj   !== 0 ? { muskXSentiment: muskXAdj }   : {}),
    ...(trendsAdj  !== 0 ? { googleTrends: trendsAdj }     : {}),
    ...(youtubeAdj !== 0 ? { youtubeInterest: youtubeAdj } : {}),
  };

  // 4-a. 기존 세션에서 buyIndex 추세 추출 (파일 선행 로드)
  let recentBuyIndexes = [];
  try {
    if (fs.existsSync(DATA_FILE)) {
      const existing = JSON.parse(fs.readFileSync(DATA_FILE, 'utf-8'));
      recentBuyIndexes = (existing.sessions || [])
        .slice(0, 7)
        .map(s => s.buyIndex)
        .filter(b => typeof b === 'number');
    }
  } catch {}

  // 4-b. 일별 예측 생성 (D+1~D+5) — 예측 정확도 추적용
  console.log('\n🔮 일별 예측 생성 중 (D+1~D+5)...');
  const dailyForecasts = await generateDailyForecast(buyIndex, avgScore, macroCtx, dateStr, recentBuyIndexes);

  console.log('');

  // 4. 세션 객체
  const session = {
    id:          `auto-${Date.now()}`,
    date:        dateStr,
    displayDate: `${dateStr.replace(/-/g, '.')}`,
    kstTime:     timeStr,
    source:      'auto',
    newsCount:   newsItems.length,
    analyzedCount: analyzed.length,
    news:        newsItems,
    analyses,
    avgScore,
    buyIndex,
    direction,
    topRules,
    bullish,
    bearish,
    neutral:     analyzed.length - bullish - bearish,
    muskXSentiment: muskXData,
    googleTrends:   trendsData,
    youtubeInterest: youtubeData,
    newsCategories,
    macroCtx,
    scoringLayers,
    latestPrice,                 // 신규 범용 필드
    latestTslaPrice: latestPrice, // 하위 호환 alias
    dailyForecasts: (dailyForecasts || []).map(f => ({
      ...f,
      basePrice: latestPrice,
      predictedPrice: latestPrice != null && f.change_pct != null
        ? Math.round(latestPrice * (1 + f.change_pct / 100) * 100) / 100
        : null,
    })),
    modelVersion: '3.1',
    timestamp:   Date.now(),
  };

  // 5. 파일 로드 & 저장
  let db = { sessions: [] };
  if (fs.existsSync(DATA_FILE)) {
    try { db = JSON.parse(fs.readFileSync(DATA_FILE, 'utf-8')); } catch (e) {
      console.warn('   ⚠ 기존 파일 파싱 실패, 초기화:', e.message);
    }
  }
  if (!Array.isArray(db.sessions)) db.sessions = [];
  db.sessions.unshift(session);
  db.sessions = db.sessions.slice(0, MAX_SESSIONS);
  db.lastUpdated = kstStr;

  fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });
  fs.writeFileSync(DATA_FILE, JSON.stringify(db, null, 2), 'utf-8');

  // 6. 결과 요약
  console.log('\n' + '━'.repeat(60));
  const grade = buyIndex >= 81 ? 'S' : buyIndex >= 61 ? 'A' : buyIndex >= 45 ? 'B' : buyIndex >= 25 ? 'C' : 'D';
  console.log(`✅ 완료 | ${kstStr}`);
  console.log(`   매수지수: ${buyIndex} (등급 ${grade}) | avgScore: ${avgScore >= 0 ? '+' : ''}${avgScore} | ${direction}`);
  console.log(`   분석: ${analyzed.length}/${newsItems.length}건 성공 (실패: ${failCount}건)`);
  console.log(`   상위 룰: ${topRules.join(', ') || '없음'}`);
  console.log(`   저장: ${DATA_FILE}`);
}

main().catch(e => {
  console.error('\n❌ 치명적 오류:', e.message);
  process.exit(1);
});
