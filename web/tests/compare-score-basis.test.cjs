const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const source = readFileSync(path.join(__dirname, "../src/components/compare/comparison-context.ts"), "utf8");
const context = vm.createContext({ exports: {} });
vm.runInContext(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, context);
const { compatibleRow } = context.exports;
const row = { key: "score_risk", path: "scores.risk.score" };
const deal = (score, signature) => ({ scores: { risk: {score}, comparison_basis: {risk: {signature}} } });

test("a score is ranked only against the same known criteria", () => {
  assert.equal(compatibleRow([deal(4, "basis-a"), deal(9, "basis-a"), deal(null, null)], row), true);
  assert.equal(compatibleRow([deal(4, "basis-a"), deal(9, "basis-b")], row), false);
  assert.equal(compatibleRow([deal(4, null), deal(9, null)], row), false);
  assert.equal(compatibleRow([deal(4, "basis-a")], row), false);
});
