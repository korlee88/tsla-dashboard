/**
 * 테슬라 캘린더 자동 업데이트 스크립트
 * GitHub Actions에서 매주 월요일 KST 09:00 (UTC 00:00) 실행
 * Node.js 22 내장 fetch 사용 (별도 패키지 불필요)
 */

const fs   = require('fs');
const path = require('path');
const { loadTickerConfig } = require('./lib/prompt');

const cfg    = loadTickerConfig();
const TICKER = cfg.ticker;

const API_KEY = process.env.GEMINI_API_KEY;
if (!API_KEY) { console.error('❌ GEMINI_API_KEY 환경변수가 없습니다.'); process.exit(1); }

const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${API_KEY}`;
const DATA_FILE  = path.join(__dirname, '..', 'data', 'calendar.json');

// ─── 유틸 ────────────────────────────────────────────────────────────────────

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

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
      const delay = (attempt + 1) * 4000 + Math.random() * 1000;
      console.warn(`   ⏳ 과부하, ${Math.round(delay / 1000)}초 후 재시도 (${attempt + 1}/${retries})...`);
      await sleep(delay);
    }
  }
  throw lastError;
}

// ─── 이벤트 수집 ─────────────────────────────────────────────────────────────

async function fetchCalendarEvents() {
  const nowKST  = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const today   = nowKST.toISOString().split('T')[0];
  const endDate = new Date(nowKST);
  endDate.setMonth(endDate.getMonth() + 3);
  const endStr  = endDate.toISOString().split('T')[0];

  const categories = cfg.calendar_event_categories || ['실적발표', '제품출시', '주주총회', '컨퍼런스', '규제', '기타'];

  const prompt = `[필수 규칙] title과 description은 반드시 한국어(Korean)로 작성. titleEn과 source만 영어 유지.

Today is ${today} (KST). Search for ALL confirmed and expected ${cfg.company_en} (${TICKER}) corporate events from ${today} to ${endStr}.

Search sources: SEC EDGAR (8-K filings, DEF 14A), ${cfg.company_en} press releases, Bloomberg, Reuters, CNBC, MarketWatch.

Find events in these categories:
${categories.map(c => `- ${c}`).join('\n')}

Return ONLY a JSON array (no markdown, no explanation):
[
  {
    "date": "YYYY-MM-DD",
    "title": "한국어 이벤트 제목",
    "titleEn": "English event title",
    "category": "${categories[0]}",
    "categoryEn": "Earnings",
    "time": "HH:MM",
    "timezone": "ET",
    "confirmed": true,
    "source": "${cfg.company_en} IR",
    "sourceUrl": null,
    "description": "한국어 1문장 설명",
    "importance": "high"
  }
]

Rules:
- category must be one of: ${categories.join(', ')}
- confirmed=true ONLY if officially announced by ${cfg.company_en} or SEC filing
- confirmed=false for analyst estimates or widely expected but unconfirmed dates
- importance=high: 실적발표, 주주총회, 주요 제품출시${categories.includes('인도량발표') ? ', 인도량발표' : ''}
- importance=medium: 컨퍼런스, 규제
- importance=low: minor announcements, speculative
- time and timezone: null if unknown
- sourceUrl: null if unknown
- title and description MUST be in Korean
- titleEn and source stay in English
- Return ONLY the JSON array. No markdown. No extra text.`;

  console.log('📅 Gemini + Google Search Grounding으로 이벤트 수집 중...');

  const data = await geminiPost({
    tools: [{ google_search: {} }],
    contents: [{ role: 'user', parts: [{ text: prompt }] }],
    generationConfig: {
      maxOutputTokens: 8192,
      temperature: 0.1,
      thinkingConfig: { thinkingBudget: 0 },
    },
  });

  const parts = data.candidates?.[0]?.content?.parts || [];
  const raw   = parts.filter(p => !p.thought).map(p => p.text || '').join('') || parts[0]?.text || '';
  const clean = raw.replace(/```json\s*/gi, '').replace(/```\s*/g, '').trim();
  const s = clean.indexOf('['), e = clean.lastIndexOf(']');
  if (s === -1 || e === -1) throw new Error('캘린더 JSON 파싱 실패:\n' + raw.slice(0, 300));
  return JSON.parse(clean.slice(s, e + 1));
}

// ─── 메인 ────────────────────────────────────────────────────────────────────

async function main() {
  const nowKST  = new Date(Date.now() + 9 * 60 * 60 * 1000);
  const kstStr  = nowKST.toISOString().replace('T', ' ').slice(0, 16) + ' KST';
  const endDate = new Date(nowKST);
  endDate.setMonth(endDate.getMonth() + 3);

  console.log(`\n📅 ${TICKER} 캘린더 업데이트 시작: ${kstStr}`);
  console.log('━'.repeat(60));

  // 1. 이벤트 수집
  const rawEvents = await fetchCalendarEvents();
  console.log(`   ✅ ${rawEvents.length}건 이벤트 수집 완료\n`);

  // 2. ID 부여 & 정렬
  const events = rawEvents
    .filter(ev => ev.date && ev.title)
    .map(ev => ({
      ...ev,
      id: `cal-${ev.date}-${(ev.titleEn || ev.title).toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 40)}`,
      time:      ev.time      || null,
      timezone:  ev.timezone  || null,
      sourceUrl: ev.sourceUrl || null,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));

  // 3. 파일 저장
  const db = {
    lastUpdated:  kstStr,
    generatedFor: `${nowKST.toISOString().slice(0, 7)} ~ ${endDate.toISOString().slice(0, 7)}`,
    events,
  };

  fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });
  fs.writeFileSync(DATA_FILE, JSON.stringify(db, null, 2), 'utf-8');

  // 4. 결과 출력
  console.log('━'.repeat(60));
  console.log(`✅ 완료 | ${kstStr}`);
  console.log(`   총 ${events.length}건 저장 → ${DATA_FILE}`);
  console.log(`   대상 기간: ${db.generatedFor}\n`);

  const catCount = {};
  events.forEach(ev => { catCount[ev.category] = (catCount[ev.category] || 0) + 1; });
  Object.entries(catCount).forEach(([cat, cnt]) => console.log(`   ${cat}: ${cnt}건`));

  console.log('\n📋 이벤트 목록:');
  events.forEach(ev => {
    const conf = ev.confirmed ? '✓' : '?';
    const imp  = ev.importance === 'high' ? '🔴' : ev.importance === 'medium' ? '🟡' : '⚪';
    console.log(`   [${conf}] ${imp} ${ev.date} [${ev.category}] ${ev.title}`);
  });
}

main().catch(e => {
  console.error('\n❌ 치명적 오류:', e.message);
  process.exit(1);
});
