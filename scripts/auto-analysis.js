/**
 * TSLA 자동 뉴스 수집 & 분석 스크립트
 * GitHub Actions에서 하루 4회 실행 (KST 03:00 / 09:00 / 15:00 / 21:00)
 * Node.js 20+ 내장 fetch 사용 (별도 패키지 불필요)
 */

const fs   = require('fs');
const path = require('path');
const { loadMacroData, buildMacroContext, calculateEnhancedScore } = require('./lib/scoring');

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

// ─── 시스템 프롬프트 ─────────────────────────────────────────────────────────

const SYSTEM_PROMPT = `You are a financial analyst specializing in Tesla (TSLA) stock impact assessment.
Analyze the given news and return ONLY valid JSON in this exact format:
{
  "impact_score": <integer -5 to +5>,
  "direction": "<bullish|bearish|neutral>",
  "confidence": "<high|medium|low>",
  "triggered_rules": ["R01","R02"],
  "reasoning": "<one sentence explanation in Korean>",
  "key_factors": ["<factor1>", "<factor2>"]
}

Rule reference:
R01=delivery miss(>5%), R02=EPS miss(>10%), R03=guidance cut, R04=recall(>50K),
R05=SEC/DOJ investigation, R06=major competitor EV launch, R07=factory shutdown/fire,
R08=musk SNS controversy(DOGE/politics), R09=subsidy reduction/removal, R10=price cut(>5%),
R11=delivery beat(>5%), R12=EPS beat(>10%), R13=new product/FSD milestone,
R14=EV incentive expansion, R15=large energy storage deal, R16=new market entry(India/SEA),
R17=analyst target upgrade(>20%), R18=fed rate cut signal, R19=musk share buyback/positive statement,
R20=china sales growth/gov cooperation, R21=major lawsuit win, R22=short seller report,
R23=recession fear intensification, R24=musk other ventures risk spillover(SpaceX/X/DOGE),
R25=optimus/humanoid robot production scale-up or commercialization(B2B contract/factory ramp/shipment confirmed),
R26=vehicle production cut/pause for robot factory transition(bullish if paired with R25, bearish offset)

STRICT SCORE GUIDELINES (backtesting: previous scores were systematically too high — apply conservatively):

±5: CATASTROPHIC or HISTORIC only — bankruptcy risk, >30% delivery miss confirmed, historic fraud
    Frequency: 1–2 times per year at most. Almost never appropriate.

±3~4: REQUIRES hard confirmed numbers — NOT speculation, NOT analyst opinion, NOT rumors
    ✓ Actual quarterly delivery report published (beat/miss >5% vs consensus with official numbers)
    ✓ Actual EPS reported with verified figures
    ✓ Factory confirmed shutdown/fire with operational impact
    ✗ "Expected to beat" / "analysts expect" / "reportedly" → MAX ±2
    ✗ Analyst upgrades, price target changes → MAX ±2 (use R17, cap at ±2)
    ✗ Follow-up or repeated story about already-known event → subtract 1 or score 0
    Frequency target: 1–2 items per 10-article batch

±2: Moderate confirmed news with clear, specific Tesla impact
    ✓ Official partnership/deal announced with specific terms
    ✓ Verified monthly sales data (China CPCA, etc.)
    ✓ Regulatory decision directly affecting Tesla products
    Frequency target: 3–4 items per 10-article batch

±1: Minor, indirect, or speculative news
    ✓ Analyst commentary/speculation without hard data
    ✓ Industry trend with TSLA mention
    ✓ Incremental product/software update
    Frequency target: 3–4 items per 10-article batch

0: Irrelevant, fully priced-in, or pure noise
    ✓ Repeated/rehashed known information (same story >3 days old)
    ✓ General market commentary without TSLA catalyst
    Frequency target: 1–2 items per 10-article batch

CONSERVATIVE SCORING RULES (mandatory):
1. DEFAULT: When uncertain between two scores, ALWAYS choose the LOWER magnitude.
2. SPECULATION: Any rumor, forecast, analyst view, or "reportedly" = MAX ±2.
3. ALREADY KNOWN: Event/trend in news >3 days → subtract 1 from initial score.
4. SELF-CHECK: Before assigning ±3 or higher, confirm: "Does this article contain officially published, quantified data?" If NO → reduce to ±2.

Per-rule CAPS (hard limits regardless of context):
- R08 (Musk SNS/DOGE): MAX ±2
- R09 (subsidy reduction): MAX ±2 unless specific law confirmed
- R13 (FSD/new product): MAX ±3; ±4 only if hardware shipping with date confirmed
- R17 (analyst upgrade/downgrade): MAX ±2
- R18 (fed rate signal): MAX ±1
- R19 (Musk positive statement): MAX ±2
- R20 (China sales): MAX ±2 unless official quarterly data published
- R22 (short seller report): MAX ±2
- R23 (recession fear): MAX -1
- R24 (Musk ventures spillover): MAX ±2
- R25 (Optimus/robot scale-up): MAX +4; +3 if confirmed ramp plan, +4 only if shipment/B2B contract confirmed
  NOTE: R25 is BULLISH even when co-occurring with R07 (factory shutdown for robot pivot).
        When R25+R07 together: score R25 as +3~+4, score R07 as -1 only (pivot context overrides shutdown penalty)
- R26 (vehicle production cut for robot transition): score -1 to -2 standalone; score 0 if R25 present (pivot rationale neutralizes)

DIRECTION: bullish if score>0, bearish if score<0, neutral ONLY if score=0.
CRITICAL: Return ONLY the raw JSON object. No markdown, no explanation, no extra text.`;

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
  const data = await geminiPost({
    tools: [{ google_search: {} }],
    contents: [{
      role: 'user',
      parts: [{ text: `[필수 규칙] title과 summary는 반드시 한국어(Korean)로 작성. 영어 원문은 한국어로 번역할 것. source·category만 영어 유지.\n\nSearch for the latest Tesla (TSLA) and Elon Musk news from today or past 24 hours that could impact Tesla stock.\nOnly include articles from major financial/tech news outlets: Reuters, Bloomberg, CNBC, Wall Street Journal, Financial Times, Associated Press, MarketWatch, Barron's, Seeking Alpha, Electrek, The Verge, TechCrunch, Forbes, CNN Business, Fox Business.\nReturn ONLY a JSON array of exactly 10 most market-impactful items, strictly no duplicates, each from a different angle or event:\n[{"id":1,"title":"(한국어 번역 제목 예: 테슬라, 1분기 인도량 예상치 하회)","summary":"(한국어 2~3문장 요약 예: 테슬라가 2026년 1분기...)","source":"Reuters","date":"${today}","category":"Earnings|Delivery|Product|Competition|Regulatory|Musk|Macro|Energy|Market|Legal"}]\n⚠️ title·summary에 영어 사용 절대 금지. 반드시 한국어로만 작성.\nReturn ONLY the JSON array, no other text.` }],
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
  const userContent = `Analyze this Tesla-related news for TSLA stock impact:\n\nTitle: ${newsItem.title}\n\nSummary: ${newsItem.summary}\n\nSource: ${newsItem.source} | Date: ${newsItem.date} | Category: ${newsItem.category}`;
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

// ─── 머스크 X 센티먼트 수집 (Gemini Search Grounding) ────────────────────────
// Grok 제안 #1: 머스크 X 포스트 센티먼트를 별도 신호로 활용

async function collectMuskXSentiment(dateStr) {
  try {
    const data = await geminiPost({
      tools: [{ google_search: {} }],
      contents: [{
        role: 'user',
        parts: [{ text: `Search X (Twitter) and web for @elonmusk posts from the past 7 days (around ${dateStr}) related to Tesla, TSLA, electric vehicles, Robotaxi, FSD, Optimus, energy storage, or Tesla business strategy.\nAnalyze the overall tone and sentiment of Elon Musk's recent public communications about Tesla.\nReturn ONLY JSON:\n{"posts":[{"date":"YYYY-MM-DD","content":"(한국어 내용 요약)","sentiment":"bullish|bearish|neutral","engagement":"high|medium|low"}],"overall_sentiment":"bullish|bearish|neutral","sentiment_score":<integer -3 to +3>,"post_count":<number of found posts>,"reasoning":"(한국어 한 문장 설명)"}\nCRITICAL: Return ONLY the JSON object.` }],
      }],
      generationConfig: { maxOutputTokens: 1024, temperature: 0.1, thinkingConfig: { thinkingBudget: 0 } },
    });
    const parts = data.candidates?.[0]?.content?.parts || [];
    const raw   = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
    const clean = raw.replace(/```json\s*/gi, '').replace(/```\s*/g, '').trim();
    const m = clean.match(/\{[\s\S]*\}/);
    if (!m) return null;
    const result = JSON.parse(m[0]);
    console.log(`   🐦 머스크 X: 센티먼트 ${result.overall_sentiment} (${result.sentiment_score >= 0 ? '+' : ''}${result.sentiment_score}) | 포스트 ${result.post_count || '?'}건`);
    return result;
  } catch (e) {
    console.warn(`   ⚠ 머스크 X 센티먼트 수집 실패: ${e.message}`);
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
      system_instruction: { parts: [{ text: 'You are a TSLA stock prediction AI. Return ONLY valid JSON with no explanation.' }] },
      contents: [{ role: 'user', parts: [{ text: `TSLA Analysis (${dateStr}):
- buyIndex: ${buyIndex}/100 (≥65=bullish, 45-64=neutral, ≤44=bearish)
- avgNewsScore: ${avgScore >= 0 ? '+' : ''}${avgScore} (range -5 to +5)
- Macro: ${macroSummary}
${trendRule}

Predict TSLA daily closing price change % for the next 5 trading days (skip weekends).
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

  console.log(`\n🚀 TSLA 자동 분석 시작: ${kstStr}`);
  console.log('━'.repeat(60));

  // 1. 뉴스 수집
  console.log('\n📰 뉴스 수집 중 (Google Search Grounding)...');
  const newsItems = await collectNews();
  console.log(`   ✅ ${newsItems.length}건 수집 완료`);

  // 1-2. 머스크 X 센티먼트 수집
  console.log('\n🐦 머스크 X 센티먼트 수집 중...');
  const muskXData = await collectMuskXSentiment(dateStr);
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
  let latestTslaPrice = null;   // dailyForecasts basePrice 계산용
  try {
    console.log('   📊 매크로 컨텍스트 로드 중 (SPY/QQQ/VIX/TSLA/WTI/CNY)...');
    const macroData = await loadMacroData();
    macroCtx = buildMacroContext(macroData, dateStr);
    // TSLA 최신 주봉 종가 → 일별 예측 기준가로 사용
    if (macroData.tsla?.length) {
      latestTslaPrice = Math.round(macroData.tsla[macroData.tsla.length - 1].close * 100) / 100;
    }
    const wtiStr = macroCtx.wtiChg >= 0 ? '+' : '';
    const cnyStr = macroCtx.cnyChg >= 0 ? '+' : '';
    const macdStr = macroCtx.macd?.crossover ? `MACD ${macroCtx.macd.crossover}` : `MACD ${macroCtx.macd?.trend || '-'}`;
    const bbStr   = macroCtx.bb ? `BB:${Math.round(macroCtx.bb.pos*100)}%` : '';
    console.log(`   ✅ SPY:${macroCtx.spyChg >= 0 ? '+' : ''}${macroCtx.spyChg}% QQQ:${macroCtx.qqqChg >= 0 ? '+' : ''}${macroCtx.qqqChg}% VIX:${macroCtx.vixClose} WTI:${wtiStr}${macroCtx.wtiChg}% CNY:${cnyStr}${macroCtx.cnyChg}% RSI:${macroCtx.rsi} ${macdStr} ${bbStr}${latestTslaPrice ? ` TSLA:$${latestTslaPrice}` : ''}`);
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

  const enhanced = calculateEnhancedScore({ avgScore, topRules, bullish, bearish, macroCtx, newsCategories });

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
    latestTslaPrice,
    dailyForecasts: (dailyForecasts || []).map(f => ({
      ...f,
      basePrice: latestTslaPrice,
      predictedPrice: latestTslaPrice != null && f.change_pct != null
        ? Math.round(latestTslaPrice * (1 + f.change_pct / 100) * 100) / 100
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
