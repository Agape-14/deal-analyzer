const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const ts = require("typescript");

const source = readFileSync(join(__dirname, "../src/components/needs-review-panel.tsx"), "utf8");
const implementation = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
}).outputText;

function renderDashboard(deals, isAnalyst = true) {
  const dependencies = {
    "next/link": ({ children, ...props }) => React.createElement("a", props, children),
    "@/components/ui/card": { Card: ({ children }) => React.createElement("section", null, children) },
    "@/lib/auth-client": { useCurrentUser: () => ({ isAnalyst, loading: false }) },
    "@/lib/utils": { cn: (...parts) => parts.join(" ") },
  };
  const context = vm.createContext({ exports: {}, require: name => dependencies[name] ?? require(name) });
  vm.runInContext(implementation, context);
  return renderToStaticMarkup(React.createElement(context.exports.NeedsReviewPanel, { deals }));
}

test("dashboard places conflicts first and routes documents and source findings directly", () => {
  const html = renderDashboard([
    { id: 1, project_name: "Read the model", analysis: {
      questions: [],
      review_coverage: { sources: { documents: [{ id: 8, filename: "Forecast.xlsx", status: "partial" }] } },
      readiness: { checks: [{ key: "sources", label: "Document reading", status: "incomplete", detail: "Check workbook warnings.", paths: [] }] },
    } },
    { id: 2, project_name: "Budget conflict", analysis: {
      questions: [{ area: "Debt", issues: [{ path: "debt_amount", state: "missing" }] }],
      readiness: { checks: [
        { key: "funding", label: "Funding", status: "incomplete", detail: "Find debt.", paths: ["debt_amount"] },
        { key: "budget", label: "Construction budget", status: "attention", detail: "Cost and sources disagree.", paths: [] },
      ] },
      findings: [
        { id: "a", title: "Mismatched unit mix", kind: "conflict", status: "current", detail: "Two sources list different unit counts." },
        { id: "b", title: "Resolved conflict", kind: "conflict", status: "resolved" },
        { id: "c", title: "Ordinary observation", kind: "source_note", status: "current" },
      ],
      return_crosscheck: { status: "needs_review" },
    } },
  ]);
  assert.ok(html.indexOf("Budget conflict") < html.indexOf("Read the model"));
  assert.match(html, /href="\/deals\/1\?tab=documents#document-8"[^]*Forecast\.xlsx/);
  assert.match(html, /href="\/deals\/2\?tab=questions"[^]*Construction budget/);
  assert.match(html, /href="\/deals\/2\?tab=questions#source-findings"[^]*Mismatched unit mix/);
  assert.match(html, /href="\/deals\/2\?tab=overview#return-crosscheck"[^]*Return cross-check/);
  assert.doesNotMatch(html, /Find debt|Resolved conflict|Ordinary observation/);
});

test("dashboard hides resolved checks and remains analyst-only", () => {
  const deals = [{ id: 1, project_name: "Ready", analysis: {
    questions: [],
    readiness: { checks: [{ key: "sources", label: "Document reading", status: "checked", detail: "Read", paths: [] }] },
    return_crosscheck: { status: "current" },
  } }];
  assert.equal(renderDashboard(deals), "");
  assert.equal(renderDashboard([{ id: 2, project_name: "Needs work", analysis: {
    questions: [{ area: "Debt", issues: [{ path: "debt_amount", state: "missing" }] }],
  } }], false), "");
});
