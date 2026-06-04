/**
 * 시스템 프롬프트 빌더 — config/rules.json + config/ticker.json 기반
 * Node.js 스크립트(auto-analysis, backtest-run)에서 공통 사용
 */

const fs   = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..', '..');

function loadTickerConfig(cfgPath) {
  const p = cfgPath || path.join(ROOT, 'config', 'ticker.json');
  return JSON.parse(fs.readFileSync(p, 'utf-8'));
}

function loadRulesConfig(cfgPath) {
  const p = cfgPath || path.join(ROOT, 'config', 'rules.json');
  return JSON.parse(fs.readFileSync(p, 'utf-8'));
}

/**
 * rules.json + ticker.json을 조합해 AI에 전달할 SYSTEM_PROMPT 문자열 조립.
 * {company_en}, {ticker} 플레이스홀더를 치환한다.
 */
function buildSystemPrompt(cfg, rulesData) {
  const sub = (str) => str
    .replace(/\{company_en\}/g, cfg.company_en)
    .replace(/\{ticker\}/g, cfg.ticker);

  const ruleRef = rulesData.rules
    .map(r => `${r.id}=${r.desc}`)
    .join(', ');

  return [
    sub(rulesData.system_prompt_intro),
    '',
    'Rule reference:',
    ruleRef,
    '',
    sub(rulesData.scoring_guidelines),
    '',
    rulesData.per_rule_caps,
    '',
    rulesData.direction_rule,
  ].join('\n');
}

/**
 * index.html 브라우저 측에서 fetch로 로드한 rules/ticker 객체를 받아
 * SYSTEM_PROMPT 문자열을 조립하는 함수 (Node require 없이 동작).
 * 위 buildSystemPrompt와 완전히 동일한 로직 — 브라우저 전용.
 */
function buildSystemPromptBrowser(cfg, rulesData) {
  if (!cfg || !rulesData) return null;
  return buildSystemPrompt(cfg, rulesData);
}

module.exports = { loadTickerConfig, loadRulesConfig, buildSystemPrompt, buildSystemPromptBrowser };
