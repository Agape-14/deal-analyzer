const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

function load(relative, dependencies = {}) {
  const context = vm.createContext({ exports: {}, require: (name) => dependencies[name] ?? {} });
  vm.runInContext(ts.transpileModule(readFileSync(path.join(__dirname, relative), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, context);
  return context.exports;
}
const utils = load("../src/lib/utils.ts", { clsx: require("clsx"), "tailwind-merge": require("tailwind-merge") });
const { formatValue } = load("../src/components/deal-detail/metrics-section.tsx", { "@/lib/utils": utils });
const { buildReviewItems } = load("../src/components/deal-detail/review-queue.tsx", { "@/lib/utils": utils });
const { getValueAt, getRow } = load("../src/components/compare/presets.ts");

test("comparison rows use the same accepted returns as headers", () => {
  const deal = { metrics: { target_returns: { target_irr: 6.5, target_cash_on_cash: 13 },
    _canonical_returns: { target_irr: null, cash_on_cash: 6.5, target_equity_multiple: null } } };
  assert.equal(getValueAt(deal, getRow("target_irr").path), null);
  assert.equal(getValueAt(deal, getRow("cash_on_cash").path), 6.5);
  assert.equal(getValueAt(deal, getRow("equity_multiple").path), null);
});

test("units remain meaningful in the raw metrics view", () => {
  assert.equal(formatValue("construction_loan_term_months", 28), "28 months");
  assert.equal(formatValue("investment_term_years", 2.5), "2.5 years");
  assert.equal(formatValue("dscr", 1.25), "1.25x");
  assert.equal(formatValue("dscr_requirement", 1.3), "1.30x");
  assert.equal(formatValue("operating_expense_ratio", 23.24), "23.2%");
  assert.equal(formatValue("target_cash_on_cash", 8), "8.0%");
  assert.equal(formatValue("permanent_loan_amount", 1000000), "$1.0M");
});

test("investment cautions do not become mandatory confirmation chores", () => {
  const items = buildReviewItems({ metrics: { validation_flags: [
    { category: "Leverage", severity: "yellow", message: "High leverage" },
    { category: "Underwriting", severity: "yellow", message: "Cap-rate assumption" },
  ] } });
  assert.equal(items.length, 0);
});

test("verified but conflicted critical facts remain visible", () => {
  const items = buildReviewItems({ metrics: { deal_structure: { ltv: 65 } },
    scores: { data_quality: { critical_fields: [
      { path: "deal_structure.ltv", label: "LTV", verified: true, severity: "blocker", reason: "conflicting source values" },
    ] } } });
  assert.equal(items.length, 1);
});

test("legacy unsure resolutions cannot hide questions", () => {
  const items = buildReviewItems({ metrics: {
    deal_structure: { ltv: 65 },
    _provenance: { "deal_structure.ltv": { status: "wrong" } },
    _review_resolutions: { "source:deal_structure.ltv": { resolved: true, action: "unsure" } },
  } });
  assert.equal(items.length, 1);
});

test("PDF preview frame permission is limited to document file routes", async () => {
  const { default: config } = await import(pathToFileURL(path.join(__dirname, "../next.config.mjs")).href);
  const rules = await config.headers();
  const general = rules.find((r) => r.source === "/:path*");
  const document = rules.find((r) => r.source === "/api/deals/documents/:id/file");
  assert.equal(general.headers.find((h) => h.key === "X-Frame-Options").value, "DENY");
  assert.equal(document.headers.find((h) => h.key === "X-Frame-Options").value, "SAMEORIGIN");
  assert.ok(document.headers.find((h) => h.key === "Content-Security-Policy").value.includes("frame-ancestors 'self'"));
});
