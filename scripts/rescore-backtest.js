/**
 * 기존 backtest-results.json 재채점 — 다층 강화 모델 v2.0
 * 매크로 컨텍스트(SPY/QQQ/VIX/RSI) 추가 후 buyIndex/direction/match 재계산
 */

const fs = require('fs');
const path = require('path');
const { loadMacroData, buildMacroContext, calculateEnhancedScore } = require('./lib/scoring');

const DATA_FILE = path.join(__dirname, '..', 'data', 'backtest-results.json');

(async () => {
  console.log('🔄 백테스트 데이터 재채점 시작 (모델 v3.0)\n');

  const db = JSON.parse(fs.readFileSync(DATA_FILE, 'utf-8'));
  console.log(`📂 ${db.weeks.length}주 데이터 로드`);

  console.log('\n📊 매크로 데이터 로드 중...');
  const macroData = await loadMacroData();
  console.log(`   ✅ SPY:${macroData.spy.length}, QQQ:${macroData.qqq.length}, VIX:${macroData.vix.length}, TSLA:${macroData.tsla.length}`);

  console.log('\n🔬 재채점 진행 중...\n');

  const rescored = db.weeks.map(week => {
    if (!week.analysis || !week.movement) return week;

    const macroCtx = buildMacroContext(macroData, week.weekStart);
    const enhanced = calculateEnhancedScore({
      avgScore: week.analysis.avgScore || 0,
      topRules: week.analysis.topRules || [],
      bullish:  week.analysis.bullish  || 0,
      bearish:  week.analysis.bearish  || 0,
      macroCtx,
    });

    const newAnalysis = {
      ...week.analysis,
      buyIndex:  enhanced.buyIndex,
      direction: enhanced.direction,
      scoringLayers: enhanced.layers,
      macroCtx,
      modelVersion: '3.0',
    };
    const newMatch = enhanced.direction === week.movement.actual;
    const strong   = Math.abs(enhanced.buyIndex - 50) > 20;

    return { ...week, analysis: newAnalysis, match: newMatch, strongSignal: strong };
  });

  // 통계 재계산
  const analyzed = rescored.filter(r => r.analysis && r.movement);
  const matched  = analyzed.filter(r => r.match).length;
  const accuracy = Math.round(matched / analyzed.length * 100);
  const strong   = analyzed.filter(r => r.strongSignal);
  const strongMatched = strong.filter(r => r.match).length;
  const strongAcc = strong.length ? Math.round(strongMatched / strong.length * 100) : 0;

  // 추가 평가 지표 — ±2% 이상 움직인 주만 (의미 있는 움직임)
  const significant = analyzed.filter(r => Math.abs(r.movement.pctChange) >= 2);
  const sigMatched  = significant.filter(r => r.match).length;
  const sigAcc      = significant.length ? Math.round(sigMatched / significant.length * 100) : 0;

  // ±1.5% 이상 (실제 neutral 제외)
  const nonNeutral  = analyzed.filter(r => Math.abs(r.movement.pctChange) >= 1.5);
  const nnMatched   = nonNeutral.filter(r => r.match).length;
  const nnAcc       = nonNeutral.length ? Math.round(nnMatched / nonNeutral.length * 100) : 0;

  const avgScore = Math.round(analyzed.reduce((s, r) => s + (r.analysis.avgScore || 0), 0) / analyzed.length * 10) / 10;

  db.weeks = rescored;
  db.stats = {
    totalWeeks:        rescored.length,
    analyzedWeeks:     analyzed.length,
    accuracy,
    strongAccuracy:    strongAcc,
    significantAccuracy:    sigAcc,        // ±2% 이상 움직인 주
    significantWeeks:       significant.length,
    nonNeutralAccuracy:     nnAcc,         // ±1.5% 이상
    nonNeutralWeeks:        nonNeutral.length,
    avgScore,
    modelVersion: '3.0',
  };
  db.lastRescored = new Date(Date.now() + 9 * 3600000).toISOString().replace('T', ' ').slice(0, 16) + ' KST';

  fs.writeFileSync(DATA_FILE, JSON.stringify(db, null, 2), 'utf-8');

  console.log('━'.repeat(56));
  console.log('         🎯 다층 강화 모델 v3.0 재채점 완료');
  console.log('━'.repeat(56));
  console.log(`전체 ${analyzed.length}주 정확도:           ${accuracy}% (${matched}/${analyzed.length})`);
  console.log(`강한신호(|bi-50|>20) 정확도:    ${strongAcc}% (${strongMatched}/${strong.length})`);
  console.log(`±2% 이상 움직인 주 정확도:      ${sigAcc}% (${sigMatched}/${significant.length}) 🎯`);
  console.log(`±1.5% 이상 움직인 주 정확도:    ${nnAcc}% (${nnMatched}/${nonNeutral.length})`);
  console.log('━'.repeat(56));
  console.log(`💾 저장: ${DATA_FILE}`);
})().catch(e => { console.error('❌ 오류:', e); process.exit(1); });
