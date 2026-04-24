/**
 * TSLA 자동 뉴스 수집 & 분석 스크립트
 * GitHub Actions에서 하루 4회 실행 (KST 03:00 / 09:00 / 15:00 / 21:00)
 * Node.js 20+ 내장 fetch 사용 (별도 패키지 불필요)
 */

const fs   = require('fs');
const path = require('path');

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
±5: Extreme event  |  ±3~4: Major event  |  ±1~2: Minor event  |  0: Neutral

CRITICAL: Return ONLY the raw JSON object. No markdown, no explanation, no extra text.`;

// ─── 유틸 ────────────────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function getTopRules(analyses) {
  const cnt = {};
  analyses.forEach(a => (a?.triggered_rules || []).forEach(r => { cnt[r] = (cnt[r] || 0) + 1; }));
  return Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([r]) => r);
}

async function geminiPost(body) {
  const res = await fetch(GEMINI_URL, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e?.error?.message || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── 뉴스 수집 (Google Search Grounding) ────────────────────────────────────

async function collectNews() {
  const today = new Date().toISOString().split('T')[0];
  const data = await geminiPost({
    tools: [{ google_search: {} }],
    contents: [{
      role: 'user',
      parts: [{ text: `Search for the latest Tesla (TSLA) and Elon Musk news from today or past 24 hours that could impact Tesla stock.\nOnly include articles from major financial/tech news outlets: Reuters, Bloomberg, CNBC, Wall Street Journal, Financial Times, Associated Press, MarketWatch, Barron's, Seeking Alpha, Electrek, The Verge, TechCrunch, Forbes, CNN Business, Fox Business.\nReturn ONLY a JSON array of exactly 15 most market-impactful items, strictly no duplicates, each from a different angle or event:\n[{"id":1,"title":"한국어로 번역된 제목","summary":"2~3문장 한국어 요약","source":"publisher name","date":"${today}","category":"Earnings|Delivery|Product|Competition|Regulatory|Musk|Macro|Energy|Market|Legal"}]\nIMPORTANT: title and summary MUST be written in Korean (한국어). category field stays in English.\nReturn ONLY the JSON array, no other text.` }],
    }],
    generationConfig: { maxOutputTokens: 8192, temperature: 0.1, thinkingConfig: { thinkingBudget: 0 } },
  });
  const parts  = data.candidates?.[0]?.content?.parts || [];
  const raw    = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
  const clean  = raw.replace(/```json\s*/gi, '').replace(/```\s*/g, '').trim();
  const s = clean.indexOf('['), e = clean.lastIndexOf(']');
  if (s === -1 || e === -1) throw new Error('뉴스 JSON 파싱 실패: ' + raw.slice(0, 200));
  const items = JSON.parse(clean.slice(s, e + 1));
  return items.slice(0, 15).map((n, i) => ({ ...n, id: Date.now() + i }));
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
  console.log(`   ✅ ${newsItems.length}건 수집 완료\n`);

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
  const buyIndex = Math.min(100, Math.max(0, Math.round((avgScore + 5) / 10 * 100)));
  const bullish  = analyzed.filter(n => analyses[n.id].direction === 'bullish').length;
  const bearish  = analyzed.filter(n => analyses[n.id].direction === 'bearish').length;
  const direction = bullish > bearish ? 'bullish' : bearish > bullish ? 'bearish' : 'neutral';
  const topRules = getTopRules(analyzed.map(n => analyses[n.id]));

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
