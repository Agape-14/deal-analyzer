const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');
const ts = require('typescript');
const context = vm.createContext({ exports: {} });
vm.runInContext(ts.transpileModule(readFileSync(path.join(__dirname, '../src/components/compare/comparison-context.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, context);
const { compatibleRow, rowFact, returnContext } = context.exports;
const row = { group: 'Returns', path: 'metrics._canonical_returns.cash_on_cash' };
const makeDeal = (changes = {}) => ({ analysis: { returns: { cash_on_cash_path: 'target_returns.hold_scenario.cash_on_cash_return' }, facts: { 'target_returns.hold_scenario.cash_on_cash_return': { state: 'manual', value: 8, identity: { unit: 'percent', scenario: 'hold', investor_class: 'Class A', basis: 'net', period: 'annual stabilized', currency: 'USD', debt_phase: 'permanent', ...changes } } } } });
test('same class, basis, scenario and period permit return comparison', () => assert.equal(compatibleRow([makeDeal(), makeDeal()], row), true));
for (const dimension of ['unit', 'scenario', 'investor_class', 'basis', 'period', 'currency', 'debt_phase']) {
  test('different ' + dimension + ' prevents ranking, normalization and deltas', () => assert.equal(compatibleRow([makeDeal(), makeDeal({ [dimension]: 'different' })], row), false));
}
test('unspecified return context prevents ranking', () => assert.equal(compatibleRow([makeDeal(), makeDeal({ basis: 'unspecified' })], row), false));
test('canonical missing path cannot use a raw return', () => assert.equal(rowFact({ analysis: { returns: { cash_on_cash_path: null }, facts: makeDeal().analysis.facts } }, row), undefined));
test('labels preserve class and period and expose unspecified basis', () => assert.match(returnContext(rowFact(makeDeal({ basis: 'unspecified' }), row)), /Class A · Basis unspecified · annual stabilized/));
