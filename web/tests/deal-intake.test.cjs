const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const script = new vm.Script(ts.transpileModule(
  readFileSync(path.join(__dirname, "../src/lib/deal-intake.ts"), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } },
).outputText);
const baseBytes = new Blob([new Uint8Array(50 * 1024 * 1024)]);

function syntheticFile(name, size) {
  return new File([baseBytes.slice(0, size)], name, { type: "text/csv" });
}

function intakeWith(fetch) {
  const context = vm.createContext({ exports: {}, FormData, fetch });
  script.runInContext(context);
  return context.exports.uploadDealDocuments;
}

function saved(count, errors = []) {
  return Response.json({ deal_id: 12, documents: Array.from({ length: count }, (_, i) => ({ id: i + 1 })), errors });
}

test("intake sends multipart bodies below the edge limit with one deal token", async () => {
  const first = syntheticFile("Offering.csv", 50 * 1024 * 1024);
  const second = syntheticFile("Budget.csv", 90_000_000 - first.size);
  const last = syntheticFile("Terms.csv", 11_000_000);
  const batches = [];
  const upload = intakeWith(async (url, init) => {
    assert.equal(url, "/document-upload/intake");
    assert.equal(init.body.get("intake_token"), "same-token");
    assert.equal(init.body.get("project_name"), "Staged deal");
    const names = init.body.getAll("files").map(file => file.name);
    const request = new Request("https://example.invalid" + url, init);
    let requestBytes = 0;
    for await (const chunk of request.body) requestBytes += chunk.length;
    const fileBytes = init.body.getAll("files").reduce((sum, file) => sum + file.size, 0);
    assert.ok(fileBytes <= 90_000_000);
    assert.ok(requestBytes > fileBytes && requestBytes < 100_000_000);
    batches.push(names);
    return saved(names.length);
  });
  const result = await upload([first, second, last], "same-token", "Staged deal", null);
  assert.deepEqual(batches, [["Offering.csv", "Budget.csv"], ["Terms.csv"]]);
  assert.equal(result.dealId, 12);
  assert.equal(result.error, null);
  assert.equal(result.remainingFiles.length, 0);
});

test("intake retry keeps only the failed same-name file and the unsent batch", async () => {
  const first = syntheticFile("Terms.csv", 35_000_000);
  const failed = syntheticFile("Terms.csv", 36_000_000);
  const unsent = syntheticFile("Budget.csv", 30_000_000);
  const batches = [];
  const upload = intakeWith(async (_url, init) => {
    assert.equal(init.body.get("intake_token"), "same-token");
    const files = init.body.getAll("files");
    batches.push(files.map(file => file.size));
    if (batches.length === 1) return saved(1, [{ file_index: 1, filename: "Terms.csv", detail: "Temporary save failure" }]);
    return saved(files.length);
  });

  const result = await upload([first, failed, unsent], "same-token", "", null);
  assert.equal(result.dealId, 12);
  assert.match(result.error, /Terms\.csv: Temporary save failure/);
  assert.deepEqual(Array.from(result.remainingFiles), [failed, unsent]);
  assert.equal(batches.length, 1);

  const retry = await upload(result.remainingFiles, "same-token", "", result.dealId);
  assert.equal(retry.dealId, result.dealId);
  assert.equal(retry.error, null);
  assert.deepEqual(batches, [[first.size, failed.size], [failed.size, unsent.size]]);
});

test("an HTML 413 preserves the unconfirmed files and explains the size limit", async () => {
  const first = syntheticFile("Offering.csv", 50_000_000);
  const rejected = syntheticFile("Budget.csv", 50_000_000);
  let calls = 0;
  const upload = intakeWith(async () => {
    calls += 1;
    if (calls === 1) return saved(1);
    return new Response("<!doctype html><p>Request too large.</p>", { status: 413 });
  });
  const result = await upload([first, rejected], "same-token", "", null);
  assert.equal(result.dealId, 12);
  assert.deepEqual(Array.from(result.remainingFiles), [rejected]);
  assert.match(result.error, /connection’s size limit/);
});

test("a non-JSON success cannot mark a small upload saved", async () => {
  const small = new File(["Metric,Value\nUnits,42\n"], "Memo.csv", { type: "text/csv" });
  const upload = intakeWith(async () => new Response("<!doctype html><p>Sign in</p>"));
  const result = await upload([small], "same-token", "", null);
  assert.equal(result.dealId, null);
  assert.deepEqual(Array.from(result.remainingFiles), [small]);
  assert.match(result.error, /did not confirm the upload/);
});
