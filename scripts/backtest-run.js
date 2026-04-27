/**
 * TSLA 백테스트 데이터 수집 스크립트
 * 2025년 52주 뉴스 수집 + AI 분석 + 실제 주가 방향 매칭
 * GitHub Actions에서 workflow_dispatch로 실행 (1회성 야간 작업)
 * Node.js 22 내장 fetch 사용
 */

const fs            = require('fs');
const path          = require('path');
const { execSync }  = require('child_process');

const API_KEY = process.env.GEMINI_API_KEY;
if (!API_KEY) { console.error('❌ GEMINI_API_KEY 환경변수가 없습니다.'); process.exit(1); }

const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${API_KEY}`;
const DATA_FILE  = path.join(__dirname, '..', 'data', 'backtest-results.json');

// ─── 시스템 프롬프트 (auto-analysis.js 와 동일) ──────────────────────────────

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

function gitCommitProgress(label) {
  try {
    execSync('git add data/backtest-results.json', { stdio: 'pipe' });
    const diff = execSync('git diff --staged --name-only', { stdio: 'pipe' }).toString().trim();
    if (!diff) { console.log(`   ⏭  ${label} — 변경 없음, 커밋 건너뜀`); return; }
    const nowKST = new Date(Date.now() + 9 * 3600000).toISOString().replace('T',' ').slice(0,16) + ' KST';
    execSync(`git commit -m "backtest: ${label} 완료 (${nowKST})"`, { stdio: 'pipe' });
    execSync('git pull --rebase origin master', { stdio: 'pipe' });
    execSync('git push', { stdio: 'pipe' });
    console.log(`   ✅ ${label} 중간 커밋 & 푸시 완료`);
  } catch (e) {
    console.warn(`   ⚠  git 커밋 실패 (무시): ${e.message.slice(0,80)}`);
  }
}

async function geminiPost(body, retries = 4) {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const res = await fetch(GEMINI_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) return res.json();
    const e   = await res.json().catch(() => ({}));
    const msg = e?.error?.message || `HTTP ${res.status}`;
    const retryable = res.status === 503 || res.status === 429 || res.status === 500;
    if (!retryable) throw new Error(msg);
    lastError = new Error(msg);
    if (attempt < retries) {
      const delay = (attempt + 1) * 4000 + Math.random() * 1500;
      console.warn(`   ⏳ 과부하, ${Math.round(delay / 1000)}초 후 재시도 (${attempt + 1}/${retries})...`);
      await sleep(delay);
    }
  }
  throw lastError;
}

// ─── 주가 데이터 (Yahoo Finance 2년 주봉) ────────────────────────────────────

async function fetchTSLA2YearWeekly() {
  const URL1 = 'https://query1.finance.yahoo.com/v8/finance/chart/TSLA?range=2y&interval=1wk&includePrePost=false';
  const URL2 = 'https://query2.finance.yahoo.com/v8/finance/chart/TSLA?range=2y&interval=1wk&includePrePost=false';

  function parse(json) {
    const r = json?.chart?.result?.[0];
    if (!r) throw new Error('파싱 실패');
    const ts = r.timestamp || [];
    const q  = r.indicators?.quote?.[0] || {};
    return ts.map((t, i) => ({
      dateStr: new Date(t * 1000).toISOString().split('T')[0],
      ts:      t * 1000,
      open:    q.open?.[i]  || q.close?.[i] || 0,
      high:    q.high?.[i]  || q.close?.[i] || 0,
      low:     q.low?.[i]   || q.close?.[i] || 0,
      close:   q.close?.[i] || 0,
    })).filter(d => d.close > 0 && !isNaN(d.close));
  }

  for (const url of [URL1, URL2]) {
    try {
      const r = await fetch(url, { headers: { 'user-agent': 'Mozilla/5.0' } });
      if (r.ok) { const j = await r.json(); return parse(j); }
    } catch {}
  }
  // allorigins 프록시
  try {
    const r = await fetch('https://api.allorigins.win/get?url=' + encodeURIComponent(URL1));
    if (r.ok) { const w = await r.json(); return parse(JSON.parse(w.contents || '{}')); }
  } catch {}
  throw new Error('Yahoo Finance 주봉 로드 실패');
}

// weekStart 에 가장 가까운 주봉 캔들 조회
function getActualMovement(weekStart, prices) {
  const wTs = new Date(weekStart + 'T00:00:00Z').getTime();
  let closest = null, minDiff = Infinity;
  for (const p of prices) {
    const diff = Math.abs(p.ts - wTs);
    if (diff < minDiff) { minDiff = diff; closest = p; }
  }
  if (!closest || minDiff > 8 * 86400000) return null;
  const pct = closest.open > 0 ? (closest.close - closest.open) / closest.open * 100 : 0;
  const actual = pct > 1.5 ? 'bullish' : pct < -1.5 ? 'bearish' : 'neutral';
  return {
    pctChange: Math.round(pct * 100) / 100,
    actual,
    open:  Math.round(closest.open  * 100) / 100,
    close: Math.round(closest.close * 100) / 100,
  };
}

// ─── 뉴스 수집 (Google Search Grounding) ────────────────────────────────────

async function collectWeekNews(weekStart, weekEnd) {
  const prompt = `[필수 규칙] title과 summary는 반드시 한국어(Korean)로 작성.\n\nSearch for the 10 most impactful Tesla (TSLA) and Elon Musk news articles published during the week of ${weekStart} to ${weekEnd} that could have affected Tesla stock price.\nOnly include articles from major outlets: Reuters, Bloomberg, CNBC, Wall Street Journal, Financial Times, Associated Press, MarketWatch, Barron's, Electrek, The Verge, TechCrunch, Forbes, CNN Business.\nReturn ONLY a JSON array of up to 10 items:\n[{"id":1,"title":"(한국어 번역 제목)","summary":"(한국어 2~3문장 요약)","source":"Reuters","date":"${weekStart}","category":"Earnings|Delivery|Product|Competition|Regulatory|Musk|Macro|Energy|Market|Legal"}]\ntitle·summary는 반드시 한국어. Return ONLY the JSON array, no other text.`;

  const data = await geminiPost({
    tools: [{ google_search: {} }],
    contents: [{ role: 'user', parts: [{ text: prompt }] }],
    generationConfig: { maxOutputTokens: 4096, temperature: 0.1, thinkingConfig: { thinkingBudget: 0 } },
  });

  const parts = data.candidates?.[0]?.content?.parts || [];
  const raw   = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
  const clean = raw.replace(/```json\s*/gi, '').replace(/```\s*/g, '').trim();
  const s = clean.indexOf('['), e = clean.lastIndexOf(']');
  if (s === -1 || e === -1) return [];
  const items = JSON.parse(clean.slice(s, e + 1));
  return items.slice(0, 10).map((n, i) => ({ ...n, id: `${weekStart}-${i}` }));
}

// ─── 개별 뉴스 분석 ──────────────────────────────────────────────────────────

async function analyzeNewsItem(newsItem) {
  const userContent = `Analyze this Tesla-related news for TSLA stock impact:\n\nTitle: ${newsItem.title}\n\nSummary: ${newsItem.summary}\n\nSource: ${newsItem.source} | Date: ${newsItem.date} | Category: ${newsItem.category}`;
  const data = await geminiPost({
    system_instruction: { parts: [{ text: SYSTEM_PROMPT }] },
    contents: [{ role: 'user', parts: [{ text: userContent }] }],
    generationConfig: { responseMimeType: 'application/json', maxOutputTokens: 600, temperature: 0.2, thinkingConfig: { thinkingBudget: 0 } },
  });
  const parts = data.candidates?.[0]?.content?.parts || [];
  const raw   = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
  const clean = raw.replace(/```json\s*/g, '').replace(/```\s*/g, '').trim();
  const m = clean.match(/\{[\s\S]*\}/);
  if (!m) throw new Error('JSON 파싱 실패: ' + raw.slice(0, 80));
  return JSON.parse(m[0]);
}

// ─── 주간 일괄 분석 ──────────────────────────────────────────────────────────

async function analyzeWeekBatch(newsItems) {
  const analyses = [];
  let failCount  = 0;
  for (let i = 0; i < newsItems.length; i++) {
    try {
      const r = await analyzeNewsItem(newsItems[i]);
      analyses.push(r);
      const dir = r.direction === 'bullish' ? '📈' : r.direction === 'bearish' ? '📉' : '➡';
      const sc  = r.impact_score;
      console.log(`      [${String(i+1).padStart(2,'0')}/${newsItems.length}] ${dir} ${sc >= 0 ? '+' : ''}${sc}  ${newsItems[i].title.slice(0, 50)}`);
    } catch (e) {
      failCount++;
      console.warn(`      [${String(i+1).padStart(2,'0')}/${newsItems.length}] ⚠ 분석 실패: ${e.message.slice(0, 60)}`);
    }
    if (i < newsItems.length - 1) await sleep(800);
  }
  if (analyses.length === 0) return null;

  const scores   = analyses.map(a => a.impact_score || 0);
  const avgScore = Math.round(scores.reduce((a, b) => a + b, 0) / scores.length * 10) / 10;
  const buyIndex = Math.min(100, Math.max(0, Math.round((avgScore + 5) / 10 * 100)));
  const bullish  = analyses.filter(a => a.direction === 'bullish').length;
  const bearish  = analyses.filter(a => a.direction === 'bearish').length;
  const direction = bullish > bearish ? 'bullish' : bearish > bullish ? 'bearish' : 'neutral';
  const ruleCnt  = {};
  analyses.forEach(a => (a.triggered_rules || []).forEach(r => { ruleCnt[r] = (ruleCnt[r] || 0) + 1; }));
  const topRules = Object.entries(ruleCnt).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([r]) => r);
  return { avgScore, buyIndex, direction, bullish, bearish, neutral: analyses.length - bullish - bearish, topRules, failCount };
}

// ─── 2025 주 목록 생성 ───────────────────────────────────────────────────────

function get2025Weeks() {
  const weeks = [];
  let d = new Date('2025-01-06T00:00:00Z');
  const end = new Date('2025-12-29T00:00:00Z');
  while (d <= end) {
    const ws = d.toISOString().split('T')[0];
    const we = new Date(d.getTime() + 6 * 86400000).toISOString().split('T')[0];
    const mo = d.getUTCMonth() + 1;
    const q  = mo <= 3 ? 'q1' : mo <= 6 ? 'q2' : mo <= 9 ? 'q3' : 'q4';
    weeks.push({ weekStart: ws, weekEnd: we, quarter: q });
    d = new Date(d.getTime() + 7 * 86400000);
  }
  return weeks;
}

// ─── 메인 ────────────────────────────────────────────────────────────────────

async function main() {
  const nowKST = new Date(Date.now() + 9 * 3600000);
  const kstStr = nowKST.toISOString().replace('T', ' ').slice(0, 16) + ' KST';

  console.log(`\n🔬 TSLA 백테스트 시작: ${kstStr}`);
  console.log('━'.repeat(60));

  // ── 1. 기존 데이터 로드 (중단 후 재시작 지원) ──
  let db = { weeks: [], generatedAt: null };
  if (fs.existsSync(DATA_FILE)) {
    try {
      db = JSON.parse(fs.readFileSync(DATA_FILE, 'utf-8'));
      console.log(`   ♻  기존 데이터 ${db.weeks?.length || 0}주 로드 (이어서 진행)`);
    } catch {}
  }
  const doneSet = new Set((db.weeks || []).map(w => w.weekStart));

  // ── 2. 주가 데이터 로드 ──
  console.log('\n📈 Yahoo Finance 2년 주봉 로드 중...');
  const prices = await fetchTSLA2YearWeekly();
  console.log(`   ✅ ${prices.length}개 주봉 로드 완료`);

  // ── 3. 주간 루프 ──
  const allWeeks = get2025Weeks();
  const pending  = allWeeks.filter(w => !doneSet.has(w.weekStart));
  console.log(`\n📅 처리 예정: ${pending.length}주 (완료: ${doneSet.size}주 / 전체: ${allWeeks.length}주)\n`);

  const results = [...(db.weeks || [])];
  let lastCommittedQuarter = null;

  for (let i = 0; i < pending.length; i++) {
    const { weekStart, weekEnd, quarter } = pending[i];
    const label = `[${String(i + 1).padStart(2, '0')}/${pending.length}] ${weekStart} (${quarter.toUpperCase()})`;
    console.log(`\n${label}`);
    console.log(`   📰 뉴스 수집 중...`);

    let newsItems = [], analysis = null, error = null;
    try {
      newsItems = await collectWeekNews(weekStart, weekEnd);
      console.log(`   ✅ ${newsItems.length}건 수집`);
    } catch (e) {
      error = '뉴스 수집 실패: ' + e.message;
      console.error(`   ❌ ${error}`);
    }

    if (newsItems.length > 0) {
      console.log(`   🔍 AI 분석 중...`);
      try {
        analysis = await analyzeWeekBatch(newsItems);
      } catch (e) {
        error = 'AI 분석 실패: ' + e.message;
        console.error(`   ❌ ${error}`);
      }
    }

    const movement = getActualMovement(weekStart, prices);
    const match    = (analysis && movement) ? (analysis.direction === movement.actual) : null;
    const strong   = analysis ? Math.abs(analysis.buyIndex - 50) > 20 : false;

    const mvStr = movement ? `${movement.pctChange > 0 ? '+' : ''}${movement.pctChange}% ($${movement.open}→$${movement.close})` : '데이터없음';
    const aiStr = analysis ? `매수지수 ${analysis.buyIndex} (${analysis.direction})` : '분석없음';
    const matchStr = match === true ? '✅ 일치' : match === false ? '❌ 불일치' : '—';
    console.log(`   주가: ${mvStr}  AI: ${aiStr}  ${matchStr}`);

    results.push({
      weekStart, weekEnd, quarter,
      news: newsItems.map(n => ({ title: n.title, source: n.source, category: n.category })),
      newsCount: newsItems.length,
      analysis,
      movement,
      match,
      strongSignal: strong,
      error: error || null,
    });

    // 중간 저장 (재시작 대비)
    db.weeks       = results.sort((a, b) => a.weekStart.localeCompare(b.weekStart));
    db.generatedAt = kstStr;
    fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });
    fs.writeFileSync(DATA_FILE, JSON.stringify(db, null, 2), 'utf-8');

    // 분기가 바뀌는 시점 또는 마지막 주에 중간 커밋 (앱에서 진행상황 확인 가능)
    const nextQuarter = pending[i + 1]?.quarter;
    const isLastWeek  = (i === pending.length - 1);
    if (isLastWeek || (nextQuarter && nextQuarter !== quarter && lastCommittedQuarter !== quarter)) {
      console.log(`\n📤 ${quarter.toUpperCase()} 완료 — 중간 커밋 중...`);
      gitCommitProgress(`2025 ${quarter.toUpperCase()}`);
      lastCommittedQuarter = quarter;
    }

    if (i < pending.length - 1) await sleep(2000); // 요청 간격 2초
  }

  // ── 4. 통계 요약 ──
  const analyzed  = results.filter(r => r.analysis && r.movement);
  const matched   = analyzed.filter(r => r.match).length;
  const accuracy  = analyzed.length ? Math.round(matched / analyzed.length * 100) : 0;
  const strongR   = analyzed.filter(r => r.strongSignal);
  const strongAcc = strongR.length ? Math.round(strongR.filter(r => r.match).length / strongR.length * 100) : 0;
  const avgScore  = analyzed.length
    ? Math.round(analyzed.reduce((s, r) => s + (r.analysis?.avgScore || 0), 0) / analyzed.length * 10) / 10
    : 0;

  // 상위 룰
  const ruleCnt = {};
  results.forEach(r => (r.analysis?.topRules || []).forEach(rule => { ruleCnt[rule] = (ruleCnt[rule] || 0) + 1; }));
  const topRules = Object.entries(ruleCnt).sort((a, b) => b[1] - a[1]).slice(0, 5);

  // 최종 저장
  db.weeks       = results.sort((a, b) => a.weekStart.localeCompare(b.weekStart));
  db.generatedAt = kstStr;
  db.stats = { totalWeeks: results.length, analyzedWeeks: analyzed.length, accuracy, strongAccuracy: strongAcc, avgScore };
  fs.writeFileSync(DATA_FILE, JSON.stringify(db, null, 2), 'utf-8');

  console.log('\n' + '━'.repeat(60));
  console.log(`✅ 백테스트 완료 | ${kstStr}`);
  console.log(`   총 ${results.length}주 처리 (분석 ${analyzed.length}주)`);
  console.log(`   방향 정확도: ${accuracy}%  (${matched}/${analyzed.length}건)`);
  console.log(`   강한신호 정확도: ${strongAcc}%  (${strongR.length}건)`);
  console.log(`   평균 AI 점수: ${avgScore >= 0 ? '+' : ''}${avgScore}`);
  console.log(`   상위 룰: ${topRules.map(([r, c]) => `${r}(${c})`).join(', ')}`);
  console.log(`   저장: ${DATA_FILE}\n`);
}

main().catch(e => {
  console.error('\n❌ 치명적 오류:', e.message);
  process.exit(1);
});
