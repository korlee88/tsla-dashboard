/**
 * 백테스트 재채점 스크립트 v5.0 — API 호출 없이 기존 분석에 새 scoring 적용
 * 뉴스 수집/AI 분석을 재실행하지 않고, 저장된 avgScore·bullish·bearish·topRules·macroCtx를 재활용.
 *
 * 사용법:
 *   node scripts/rescore-backtest.js [2025|2026|all] [--write]
 *   --write : 재채점 결과를 JSON 파일에 저장 (대시보드에 반영)
 */

const fs   = require('fs');
const path = require('path');
const { calculateEnhancedScore } = require('./lib/scoring');

const args  = process.argv.slice(2);
const write = args.includes('--write');
const yearArg = args.find(a => a !== '--write') || 'all';
const years = yearArg === 'all' ? [2025, 2026] : [parseInt(yearArg, 10)];

function rescoreYear(year) {
  const file = path.join(__dirname, '..', 'data', `backtest-results-${year}.json`);
  if (!fs.existsSync(file)) { console.log(`⏭  ${year}: 파일 없음`); return null; }

  const db    = JSON.parse(fs.readFileSync(file, 'utf-8'));
  const weeks = (db.weeks || []).slice().sort((a, b) => a.weekStart.localeCompare(b.weekStart));

  // 저장된 macroCtx에 없는 3주 추세(tslaTrend3w)를 주가 시퀀스로 재계산해 주입.
  // 진입 직전 3주(open[i-3] → close[i-1]) 기준, 현재 주는 제외 (lookahead 없음).
  const analyzed = weeks.filter(w => w.analysis && w.movement);
  for (let i = 0; i < analyzed.length; i++) {
    const mc = analyzed[i].analysis.macroCtx;
    if (mc && (mc.tslaTrend3w === undefined || mc.tslaTrend3w === null) && i >= 3) {
      const baseOpen  = analyzed[i - 3].movement.open;
      const lastClose = analyzed[i - 1].movement.close;
      if (baseOpen > 0) {
        mc.tslaTrend3w = Math.round((lastClose - baseOpen) / baseOpen * 100 * 100) / 100;
      }
    }
  }

  let matched = 0, total = 0;
  const fixes   = [];
  const breaks  = [];
  const remains = [];

  for (const w of weeks) {
    if (!w.analysis || !w.movement) continue;

    const { avgScore, bullish = 0, bearish = 0, topRules = [], macroCtx = null } = w.analysis;
    const actual   = w.movement.actual;
    const oldDir   = w.analysis.direction;
    const oldBi    = w.analysis.buyIndex;
    const oldMatch = (oldDir === actual);

    const enh     = calculateEnhancedScore({ avgScore, topRules, bullish, bearish, macroCtx });
    const newDir  = enh.direction;
    const newBi   = enh.buyIndex;
    const newMatch = (newDir === actual);

    if (newMatch) matched++;
    total++;

    // --write: 파일에 새 채점 결과 반영
    if (write) {
      w.analysis.buyIndex      = newBi;
      w.analysis.direction     = newDir;
      w.analysis.scoringLayers = enh.layers;
      w.analysis.modelVersion  = '5.0';
      w.match        = newMatch;
      w.strongSignal = Math.abs(newBi - 50) > 20;
    }

    const line = `  ${w.weekStart}  bi:${String(oldBi).padStart(3)}→${String(newBi).padStart(3)}  ` +
                 `dir:${oldDir.padEnd(7)}→${newDir.padEnd(7)}  actual:${actual.padEnd(7)}(${w.movement.pctChange}%)`;

    if (!oldMatch && newMatch)  fixes.push(line);
    else if (oldMatch && !newMatch) breaks.push(line);
    else if (!newMatch)          remains.push(line);
  }

  const acc    = total > 0 ? Math.round(matched / total * 100) : 0;
  const oldAcc = db.stats?.accuracy ?? '?';
  const delta  = acc - (typeof oldAcc === 'number' ? oldAcc : parseInt(oldAcc));

  // --write: stats 갱신 후 파일 저장
  if (write) {
    const analyzed   = weeks.filter(r => r.analysis && r.movement);
    const strongR    = analyzed.filter(r => r.strongSignal);
    const strongAcc  = strongR.length ? Math.round(strongR.filter(r => r.match).length / strongR.length * 100) : 0;
    const avgScoreV  = analyzed.length
      ? Math.round(analyzed.reduce((s, r) => s + (r.analysis.avgScore || 0), 0) / analyzed.length * 10) / 10 : 0;
    db.weeks  = weeks;
    db.stats  = { ...db.stats, accuracy: acc, strongAccuracy: strongAcc, avgScore: avgScoreV, modelVersion: '5.0' };
    db.lastRescored = new Date(Date.now() + 9 * 3600000).toISOString().replace('T', ' ').slice(0, 16) + ' KST';
    fs.writeFileSync(file, JSON.stringify(db, null, 2), 'utf-8');
    console.log(`\n  💾 저장 완료: ${path.basename(file)}`);
  }

  console.log(`\n${'━'.repeat(72)}`);
  console.log(`📊 ${year}년  정확도: ${oldAcc}% → ${acc}%  (${delta >= 0 ? '+' : ''}${delta}pt)  [${matched}/${total}]${write ? '  ✍ 파일 저장됨' : ''}`);

  if (fixes.length) {
    console.log(`\n  ✅ 새로 맞힌 예측 +${fixes.length}건:`);
    fixes.forEach(l => console.log(l));
  }
  if (breaks.length) {
    console.log(`\n  ⚠  깨진 예측 -${breaks.length}건:`);
    breaks.forEach(l => console.log(l));
  }
  if (remains.length) {
    console.log(`\n  ❌ 여전히 틀린 예측 ${remains.length}건:`);
    remains.forEach(l => console.log(l));
  }

  return { year, oldAcc, newAcc: acc, delta, fixes: fixes.length, breaks: breaks.length };
}

const results = years.map(rescoreYear).filter(Boolean);

if (results.length > 1) {
  const totalOldCorrect = results.reduce((s, r) => s + Math.round((r.oldAcc / 100) * (r.fixes + r.breaks + /* approx */ 0)), 0);
  console.log(`\n${'━'.repeat(72)}`);
  console.log('📈 종합 요약:');
  results.forEach(r => {
    const sign = r.delta >= 0 ? '+' : '';
    console.log(`   ${r.year}: ${r.oldAcc}% → ${r.newAcc}%  (${sign}${r.delta}pt)  개선 +${r.fixes} / 손실 -${r.breaks}`);
  });
}
