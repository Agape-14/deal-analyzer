const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");
const source = readFileSync(path.join(__dirname, "../src/lib/return-metrics.ts"), "utf8");
const context = vm.createContext({ exports: {} });
vm.runInContext(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, context);
const { getHeadlineReturnMetrics: headline } = context.exports;

test("canonical nulls cannot resurrect rejected legacy numbers", () => {
  const result = headline({
    target_irr: 25, target_equity_multiple: 3, target_cash_on_cash: 10,
    metrics: { target_returns: { target_irr: 25, target_equity_multiple: 3 },
      _canonical_returns: { primary_strategy: "hold", target_irr: null,
        target_equity_multiple: null, cash_on_cash: 8 } },
  });
  assert.equal(result.headlineIrr, null);
  assert.equal(result.headlineMultiple, null);
  assert.equal(result.primaryReturnLabel, "Cash-on-Cash");
  assert.equal(result.primaryReturnValue, 8);
});

for (const status of ["wrong", "unverifiable", "math_failed", "stale"]) {
  test("legacy fallback withholds " + status + " values", () => {
    const result = headline({ target_irr: 21, metrics: {
      target_returns: { target_irr: 21 },
      _provenance: { "target_returns.target_irr": { status } },
    } });
    assert.equal(result.headlineIrr, null);
  });
}

test("hold cash yield is never labeled IRR", () => {
  const result = headline({ metrics: { target_returns: {
    primary_strategy: "hold", target_irr: 20, target_cash_on_cash: 9,
  } } });
  assert.equal(result.headlineIrr, null);
  assert.equal(result.primaryReturnLabel, "Cash-on-Cash");
  assert.equal(result.primaryReturnValue, 9);
});

test("zero is a valid confirmed return", () => {
  assert.equal(headline({ metrics: { _canonical_returns: {
    primary_strategy: "sale", target_irr: 0, cash_on_cash: 0,
  } } }).headlineIrr, 0);
});
