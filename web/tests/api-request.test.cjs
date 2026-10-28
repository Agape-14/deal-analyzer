const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { createServer } = require("node:http");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

// Exercise the real fetch wrapper against HTTP responses, including responses
// whose headers arrive immediately but whose body never finishes.
const source = readFileSync(path.join(__dirname, "../src/lib/api.ts"), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
});
const context = vm.createContext({
  exports: {}, process, window: {}, fetch, AbortController, setTimeout, clearTimeout,
});
vm.runInContext(outputText, context);
const { api } = context.exports;

async function serve(t, handler) {
  const server = createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => {
    server.closeAllConnections();
    server.close(resolve);
  }));
  return `http://127.0.0.1:${server.address().port}/api/deals/compare`;
}

for (const scenario of [
  { name: "before response headers", status: null },
  { name: "while reading JSON", status: 200, type: "application/json", body: "{" },
  { name: "while reading an error body", status: 503, type: "application/json", body: "{" },
  { name: "while reading a download", status: 200, type: "application/octet-stream", body: "partial" },
]) {
  test(`comparison POST times out ${scenario.name}`, { timeout: 3000 }, async (t) => {
    const url = await serve(t, (_req, res) => {
      if (scenario.status !== null) {
        res.writeHead(scenario.status, { "Content-Type": scenario.type });
        res.write(scenario.body);
      }
    });
    await assert.rejects(
      api.post(url, { deal_ids: [1, 2] }, { timeoutMs: 100, signal: t.signal }),
      (error) => error.status === 408 && /too long/.test(error.detail),
    );
  });
}

test("the deal list GET also times out with a caller signal", { timeout: 3000 }, async (t) => {
  const url = await serve(t, () => {});
  await assert.rejects(api.get(url, { timeoutMs: 100, signal: t.signal }), { status: 408 });
});

test("changing selections cancels a pending body without reporting a timeout", { timeout: 3000 }, async (t) => {
  const controller = new AbortController();
  const url = await serve(t, (_req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.write("{");
    setTimeout(() => controller.abort(), 20);
  });
  await assert.rejects(
    api.post(url, { deal_ids: [1, 2] }, { timeoutMs: 1000, signal: controller.signal }),
    (error) => error.name === "AbortError" && error.status !== 408,
  );
});

test("successful comparisons retain normalization and request data", { timeout: 3000 }, async (t) => {
  const url = await serve(t, (req, res) => {
    assert.equal(req.method, "POST");
    let body = "";
    req.on("data", (chunk) => { body += chunk; });
    req.on("end", () => {
      assert.deepEqual(JSON.parse(body), { deal_ids: [1, 2] });
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ deals: [{ id: 1, metrics: { target_returns: { target_irr: 12 } } }] }));
    });
  });
  const result = await api.post(url, { deal_ids: [1, 2] }, { timeoutMs: 1000 });
  assert.equal(result.deals[0].id, 1);
  assert.equal(result.deals[0].target_irr, 12);
});

test("requests without a timeout keep existing error handling", { timeout: 3000 }, async (t) => {
  const url = await serve(t, (_req, res) => {
    res.writeHead(422, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ detail: "Select at least two deals" }));
  });
  await assert.rejects(api.post(url, { deal_ids: [1] }), {
    status: 422, detail: "Select at least two deals",
  });
});

test("empty successful responses remain supported", { timeout: 3000 }, async (t) => {
  const url = await serve(t, (_req, res) => { res.writeHead(204); res.end(); });
  assert.equal(await api.delete(url), undefined);
});

test("API normalization preserves canonical nulls and cash yield", async (t) => {
  const url = await serve(t, (_req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ target_irr: 25, metrics: {
      target_returns: { target_irr: 25, target_equity_multiple: 3 },
      _canonical_returns: { target_irr: null, target_equity_multiple: null, cash_on_cash: 8 },
    } }));
  });
  const deal = await api.get(url);
  assert.equal(deal.target_irr, null);
  assert.equal(deal.target_equity_multiple, null);
  assert.equal(deal.target_cash_on_cash, 8);
});
