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

const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${API_KEY}`;
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
R23=recession fear intensification, R24=musk other ventures risk spillover(SpaceX/X/DOGE)

Score guidelines:
±5: Extreme event (confirmed bankruptcy risk, historic milestone)
±3~4: Major confirmed event (earnings beat/miss, delivery report, product launch)
±1~2: Minor event (analyst note, speculation, rumor, incremental news)
0: Neutral/irrelevant

IMPORTANT score caps (backtesting showed these rules cause noise when over-weighted):
- R08 (Musk SNS/DOGE controversy): MAX impact_score = ±2. Short-term sentiment noise, reverts quickly.
- R24 (Musk other ventures spillover): MAX impact_score = ±2 when appearing alone without R08.
- R23 (recession fear): MAX impact_score = -1. Macro, not Tesla-specific.
- Use "neutral" direction ONLY when evidence is truly balanced AND confidence is "low".
  Prefer "bearish" over "neutral" when avgScore is slightly negative.

CRITICAL: Return ONLY the raw JSON object. No markdown, no explanation, no extra text.`;

// ─── 유틸 ────────────────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function getTopRules(analyses) {
  const cnt = {};
  analyses.forEach(a => (a?.triggered_rules || []).forEach(r => { cnt[r] = (cnt[r] || 0) + 1; }));
  return Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([r]) => r);
}

async function geminiPost(body, retries = 4) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const res = await fetch(GEMINI_URL, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    if (res.ok) return res.json();
    const e = await res.json().catch(() => ({}));
    const msg = e?.error?.message || `HTTP ${res.status}`;
    const retryable = res.status === 503 || res.status === 429 || res.status === 500;
    if (!retryable) throw new Error(msg);
    lastError = new Error(msg);
    if (attempt < retries) {
      const delay = (attempt + 1) * 3000 + Math.random() * 1000;
      console.warn(`   ⏳ 과부하, ${Math.round(delay/1000)}초 후 재시도 (${attempt + 1}/${retries})...`);
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

  // 1-2. 머스크 X 센티먼트 수집 (Grok 제안 #1)
  console.log('\n🐦 머스크 X 센티먼트 수집 중...');
  const muskXData = await collectMuskXSentiment(dateStr);
  console.log('');

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
  try {
    console.log('   📊 매크로 컨텍스트 로드 중 (SPY/QQQ/VIX/TSLA/WTI/CNY)...');
    const macroData = await loadMacroData();
    macroCtx = buildMacroContext(macroData, dateStr);
    const wtiStr = macroCtx.wtiChg >= 0 ? '+' : '';
    const cnyStr = macroCtx.cnyChg >= 0 ? '+' : '';
    const macdStr = macroCtx.macd?.crossover ? `MACD ${macroCtx.macd.crossover}` : `MACD ${macroCtx.macd?.trend || '-'}`;
    const bbStr   = macroCtx.bb ? `BB:${Math.round(macroCtx.bb.pos*100)}%` : '';
    console.log(`   ✅ SPY:${macroCtx.spyChg >= 0 ? '+' : ''}${macroCtx.spyChg}% QQQ:${macroCtx.qqqChg >= 0 ? '+' : ''}${macroCtx.qqqChg}% VIX:${macroCtx.vixClose} WTI:${wtiStr}${macroCtx.wtiChg}% CNY:${cnyStr}${macroCtx.cnyChg}% RSI:${macroCtx.rsi} ${macdStr} ${bbStr}`);
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
  let buyIndex    = Math.max(0, Math.min(100, enhanced.buyIndex + muskXAdj));
  const direction = buyIndex >= 57 ? 'bullish' : buyIndex <= 43 ? 'bearish' : enhanced.direction;
  const scoringLayers = { ...enhanced.layers, ...(muskXAdj !== 0 ? { muskXSentiment: muskXAdj } : {}) };
  // ──────────────────────────────────────────────────────────────────────────
  // ────────────────────────────────────────────────────────────────────────

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
    muskXSentiment: muskXData,   // 머스크 X 센티먼트 (Grok 제안 #1)
    newsCategories,              // 카테고리별 뉴스 분포 (Grok 제안 #2)
    macroCtx,                    // 매크로 컨텍스트 v3.0 (SPY/QQQ/VIX/TSLA/WTI/CNY/MACD/BB)
    scoringLayers,               // 적용된 보정 레이어
    modelVersion: '3.0',
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
