const { test: base, expect } = require('@playwright/test');
const fs = require('node:fs/promises');
const { captureHydrationDiagnostics } = require('./hydration-diagnostics.cjs');

async function handleWelcomeTour(page) {
  await page.addLocatorHandler(page.getByRole('dialog', { name: 'Welcome to Kenyon', exact: true }), async () => {
    await page.getByRole('button', { name: 'Skip tour', exact: true }).click();
  });
}

// These tests run against the real local API and compiled Next frontend.
// Upstream outages and a review lifecycle are stubbed separately. No private
// data or live provider extraction is used.
const test = base.extend({
  page: async ({ page, context }, use, info) => {
    const errors = [];
    const hydration = process.env.BROWSER_HYDRATION_TRACE === '1' && process.env.BROWSER_DIAGNOSTIC !== '1' ? await captureHydrationDiagnostics(page) : [];
    page.on('pageerror', error => errors.push(error.stack || error.message));
    // React's development overlay can report recoverable hydration failures
    // through console.error instead of the production window error event.
    page.on('console', message => {
      if (message.type() === 'error' && /hydration|server rendered|cannot be a descendant/i.test(message.text())) {
        errors.push(message.text());
      }
    });
    await handleWelcomeTour(page);
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      return ['127.0.0.1', 'localhost'].includes(url.hostname) ? route.continue() : route.abort();
    });
    await use(page);
    if (hydration.length) await info.attach('hydration-fiber.json', { body: JSON.stringify(hydration, null, 2), contentType: 'application/json' });
    expect(errors, 'Uncaught browser exceptions').toEqual([]);
  },
});

async function dealPage(page, id = 1, tab) {
  await page.goto(`/deals/${id}${tab ? `?tab=${tab}` : ''}`);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
}

test('reverse-proxy redirects use the public host and preserve the sign-in destination', async ({ browser }) => {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  try {
    const proxyHeaders = { host: 'deals.example.test', 'x-forwarded-proto': 'https' };
    const publicOrigin = 'https://deals.example.test';
    for (const [path, destination] of [['/?new=1', '/login?next=%2F%3Fnew%3D1'], ['/legacy', '/']]) {
      const response = await context.request.get(`http://127.0.0.1:3000${path}`, {
        headers: proxyHeaders, maxRedirects: 0,
      });
      expect(response.status()).toBe(307);
      expect(response.headers().location).toBe(`${publicOrigin}${destination}`);
    }
  } finally {
    await context.close();
  }
});

test('real sign-in rejects bad credentials and refreshes authenticated controls', async ({ browser }) => {
  const context = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:3000/deals/1');
  await expect(page).toHaveURL(/\/login\?next=/);
  await page.getByLabel('Username', { exact: true }).fill('browser-admin');
  await page.getByLabel('Password', { exact: true }).fill('incorrect-test-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByText(/invalid username or password/i)).toBeVisible();
  await page.getByLabel('Password', { exact: true }).fill('synthetic-browser-password');
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/deals\/1$/);
  await expect(page.getByRole('dialog', { name: 'Welcome to Kenyon', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Skip tour', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Assistant', exact: true })).toBeVisible();
  await context.close();
});

test('dashboard filters and separates IRR from cash yield without fake exposure', async ({ page }, info) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Sample Hold', exact: true })).toBeVisible();
  await expect(page.getByText(/Visible exposure/)).toHaveCount(0);
  await page.getByPlaceholder('Filter by project, sponsor, city...').fill('Sample Hold');
  await expect(page.getByRole('heading', { name: 'Sample Sale', exact: true })).toHaveCount(0);
  await page.getByPlaceholder('Filter by project, sponsor, city...').fill('');
  await page.getByRole('button', { name: /Sort:/ }).click();
  await expect(page.getByRole('button', { name: 'IRR', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Cash-on-cash', exact: true }).click();
  await expect(page.getByRole('button', { name: /Sort:.*Cash-on-cash/ })).toBeVisible();
  await page.screenshot({ path: info.outputPath('dashboard.png'), fullPage: true });
});

test('hold summary keeps primary returns distinct from the accepted optional sale scenario', async ({ page }, info) => {
  await dealPage(page);
  const main = page.getByRole('main');
  const accepted = await (await page.request.get('/api/deals/1')).json();
  expect(accepted.target_irr).toBeNull();
  expect(accepted.target_equity_multiple).toBeNull();
  const summary = main.getByRole('tabpanel', { name: 'Summary', exact: true });
  const headline = main.getByRole('heading', { level: 1 }).locator('..');
  const published = summary.getByRole('heading', { name: 'Published returns', exact: true }).locator('..');
  await expect(published.getByText('8.5%', { exact: true })).toBeVisible();
  for (const primary of [headline, published]) {
    await expect(primary.getByText(/27\.5%|4\.(25|3)x/)).toHaveCount(0);
  }
  const optional = summary.getByRole('heading', { name: 'Optional sale scenario', exact: true }).locator('..');
  for (const [path, value] of [
    ['target_returns.sale_scenario.sale_irr', /27\.5%/],
    ['target_returns.sale_scenario.sale_equity_multiple', /4\.(25|3)x/],
  ]) {
    expect(accepted.analysis.facts[path].state).toBe('manual');
    expect(accepted.analysis.facts[path].identity.scenario).toBe('sale');
    const alternate = optional.getByRole('listitem').filter({ hasText: value });
    await expect(alternate).toBeVisible();
    await expect(alternate.getByText(/^sale ·/)).toBeVisible();
  }
  await expect(main.getByRole('heading', { name: 'Investment considerations' })).toHaveCount(0);
  await page.getByRole('tab', { name: 'Questions', exact: true }).click();
  await expect(page.getByText('No field decisions remain', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await page.getByRole('tab', { name: 'Evidence and history', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Analysis history', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Document review status', exact: true })).toHaveCount(0);
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await page.screenshot({ path: info.outputPath('summary.png'), fullPage: true });
});

test('material decision persists as a manual lock and a new revision', async ({ page }) => {
  await dealPage(page, 2, 'questions');
  await page.getByRole('button', { name: 'Resolve with an analyst decision', exact: true }).click();
  await page.getByLabel(/minimum investment/i).fill('30000');
  await page.getByLabel('Reason or source for your decision').fill('Synthetic test decision for minimum investment');
  const saved = page.waitForResponse(r => r.url().endsWith('/analysis/resolve') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Save these decisions', exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  await expect(page.getByText('No field decisions remain', { exact: true })).toBeVisible();
  await expect(page.getByText('$30K', { exact: true })).toBeVisible();
  await page.reload();
  const response = await page.request.get('/api/deals/2');
  const deal = await response.json();
  expect(deal.metrics._locks['deal_structure.minimum_investment']).toBe(true);
  expect(deal.metrics.deal_structure.minimum_investment).toBe(30000);
  expect(deal.analysis.version).toBeGreaterThan(0);
});

test('documents disclose duplicate contents and preserve original PDF access', async ({ page }) => {
  await dealPage(page, 1, 'documents');
  await expect(page.getByText(/Identical copy of document #1; counted once/)).toBeVisible();
  await page.getByRole('button', { name: 'Preview sample-hold.pdf', exact: true }).first().click();
  const dialog = page.getByRole('dialog');
  const firstPage = dialog.getByRole('img', { name: 'PDF page 1', exact: true });
  await expect(firstPage).toBeVisible();
  expect(await firstPage.evaluate(img => img.naturalWidth)).toBeGreaterThan(500);
  await expect(dialog.getByRole('button', { name: 'Previous page' })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Next page' }).click();
  await expect(dialog.getByText('Page 2 of 2')).toBeVisible();
  const nextPage = dialog.getByRole('img', { name: 'PDF page 2', exact: true });
  await expect(nextPage).toBeVisible();
  expect(await nextPage.evaluate(img => img.naturalWidth)).toBeGreaterThan(500);
  await expect(dialog.getByRole('button', { name: 'Next page' })).toBeDisabled();
  const neverExists = await page.request.get('/api/deals/documents/1/preview/3');
  expect(neverExists.status()).toBe(404);
  const original = await page.request.get('/api/deals/documents/1/file');
  expect(original.ok()).toBeTruthy();
  expect((await original.body()).subarray(0, 4).toString()).toBe('%PDF');
  expect(original.headers()['x-frame-options']).toBe('SAMEORIGIN');
  expect(original.headers()['content-security-policy']).toContain("frame-ancestors 'self'");
  await expect(dialog.getByRole('link', { name: 'Download', exact: true })).toHaveAttribute('href', '/api/deals/documents/1/file');
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
});

test('Codex review comes first with API credits available under review options', async ({ page }) => {
  await page.route('**/api/healthz', route => route.fulfill({ json: { status: 'ok', environment: { openai: { configured: true } } } }));
  const created = await page.request.post('/api/deals', { data: { project_name: 'Browser Codex Review' } });
  expect(created.ok()).toBeTruthy();
  const { id } = await created.json();
  const uploaded = await page.request.post(`/api/deals/${id}/documents/upload`, { multipart: {
    file: { name: 'review-terms.csv', mimeType: 'text/csv', buffer: Buffer.from('Term,Value\nMinimum investment,40000\n') },
  } });
  expect(uploaded.ok()).toBeTruthy();
  const base = `/api/deals/${id}/review`;
  await expect.poll(async () => (await page.request.get(base + '/packet')).status()).toBe(200);
  await dealPage(page, id, 'documents');

  await expect(page.getByRole('link', { name: 'Review with Codex', exact: true })).toBeVisible();
  await expect(page.getByText('GPT-6 Astra', { exact: true })).toBeVisible();
  const apiReview = page.getByRole('button', { name: 'Review with API credits', exact: true });
  await expect(apiReview).toBeHidden();
  await page.getByText('Review options', { exact: true }).click();
  await expect(apiReview).toBeEnabled();

  const codex = page.getByRole('link', { name: 'Open Codex', exact: true });
  await expect(codex).toHaveAttribute('href', /^codex:\/\/new\?prompt=/);
  const [download] = await Promise.all([
    page.waitForEvent('download'), page.getByRole('link', { name: 'Download packet', exact: true }).click(),
  ]);
  expect(download.suggestedFilename()).toBe(`deal-${id}-review-packet.json`);
  const { packet } = JSON.parse(await fs.readFile(await download.path(), 'utf8'));
  const source = packet.sources[0];
  const excerpt = source.text.split('\n').find(line => line.includes('B2=40000'));
  expect(excerpt).toBeTruthy();
  const result = { package_id: packet.package_id, facts: [{
    path: 'deal_structure.minimum_investment', value: 40000, currency: 'USD',
    source_doc_id: source.id, source_sheet: 'CSV', source_cell: 'B2', source_excerpt: excerpt,
  }] };
  await page.getByLabel('Import Codex review result').setInputFiles({
    name: 'deal-review-result.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(result)),
  });
  await expect(page.getByRole('heading', { name: 'Codex review draft' })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Minimum investment · 40,000' })).toBeChecked();
  await expect(page.getByText(excerpt, { exact: true })).toBeVisible();

  await page.getByRole('button', { name: 'Paste JSON', exact: true }).click();
  const reviewJson = page.getByRole('textbox', { name: 'Codex review JSON', exact: true });
  const checkPaste = page.getByRole('button', { name: 'Check pasted result', exact: true });
  await expect(reviewJson).toBeFocused();
  await expect(checkPaste).toBeDisabled();
  await reviewJson.fill('not a JSON result');
  await checkPaste.click();
  await expect(page.getByText('Use the JSON object that Codex produced.', { exact: true })).toBeVisible();

  await reviewJson.fill(JSON.stringify({ ...result, package_id: '0'.repeat(64) }));
  await checkPaste.click();
  await expect(page.getByText('This result is for a different or older source package. Download a new packet.', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'Minimum investment · 40,000' })).toBeChecked();

  await reviewJson.fill('```json\n' + JSON.stringify(result) + '\n```');
  await checkPaste.click();
  await expect(reviewJson).toBeHidden();
  await expect(page.getByText(excerpt, { exact: true })).toBeVisible();
  const pending = await (await page.request.get(`/api/deals/${id}`)).json();
  expect(pending.analysis.accepted_metrics.deal_structure?.minimum_investment ?? null).toBeNull();

  await page.getByRole('button', { name: 'Apply 1 value', exact: true }).click();
  await expect(page.getByText(/1 value applied/)).toBeVisible();
  const deal = await (await page.request.get(`/api/deals/${id}`)).json();
  expect(deal.analysis.facts['deal_structure.minimum_investment']).toMatchObject({ value: 40000, state: 'checked' });
  expect((await page.request.delete(`/api/deals/${id}`)).ok()).toBeTruthy();
});

test('spreadsheet limitations are visible and duplicate upload is idempotent', async ({ page }) => {
  await dealPage(page, 2, 'documents');
  await expect(page.getByText(/Uses 2 external workbook links/)).toBeVisible();
  await expect(page.getByText(/Some spreadsheet rows or columns exceed/)).toBeVisible();
  const input = page.getByLabel('Upload deal documents');
  const file = { name: 'browser-upload.csv', mimeType: 'text/csv', buffer: Buffer.from('Metric,Value\nUnits,42\n') };
  await input.setInputFiles(file);
  await expect(page.getByText('Document uploaded', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'browser-upload.csv', exact: true })).toBeVisible();
  await input.setInputFiles(file);
  await expect(page.getByText('File already saved', { exact: true })).toBeVisible();
  expect((await (await page.request.get('/api/deals/2/documents')).json()).filter(d => d.filename === file.name)).toHaveLength(1);
});

test('source role changes persist and can be reversed through the UI', async ({ page }) => {
  await dealPage(page, 1, 'documents');
  for (const role of ['alternative', 'active']) {
    await page.getByRole('button', { name: 'Change document use', exact: true }).first().click();
    await page.getByLabel('Use for this deal').selectOption(role);
    await page.getByLabel('Reason', { exact: true }).fill(`Synthetic ${role} version choice`);
    const saved = page.waitForResponse(r => /\/documents\/1\/version$/.test(r.url()) && r.request().method() === 'PUT');
    await page.getByRole('button', { name: 'Save document use', exact: true }).click();
    expect((await saved).ok()).toBeTruthy();
    await page.reload();
    const docs = await (await page.request.get('/api/deals/1/documents')).json();
    expect(docs.every(d => d.source_role === role)).toBe(true);
  }
});

test('preview and adoption update history without losing manual values', async ({ page }) => {
  await dealPage(page, 1, 'audit');
  await page.getByRole('button', { name: 'Preview current inputs', exact: true }).click();
  await expect(page.getByText(/No source values are rewritten/)).toBeVisible();
  const saved = page.waitForResponse(r => r.url().endsWith('/analysis/adopt') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Save reviewed preview', exact: true }).click();
  expect((await saved).ok()).toBeTruthy();
  await expect(page.getByRole('button', { name: 'Save reviewed preview', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText(/Revision \d+ ·/).first()).toBeVisible();
  const deal = await (await page.request.get('/api/deals/1')).json();
  expect(deal.target_cash_on_cash).toBe(8.5);
  expect(deal.target_irr).toBeNull();
});

test('unsupported models show reasons and assistant works without provider credits', async ({ page }) => {
  await dealPage(page, 1, 'cashflow');
  await expect(page.getByRole('status').filter({ hasText: 'Projection needs source-supported assumptions.' })).toBeVisible();
  await expect(page.getByText(/Missing or disputed assumptions: avg rent per unit/)).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Waterfall unavailable: Refinancing distributions require' })).toBeVisible();
  await expect(page.getByText(/Multiple equity classes require/)).toBeVisible();
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await expect(page.getByText(/Reviewed facts and labeled source excerpts/)).toBeVisible();
  await expect(page.getByText('Earlier analysis · open archived reply', { exact: true })).toBeVisible();
  await expect(page.getByText('Synthetic saved conversation. Summary holds the accepted figures.')).not.toBeVisible();
  await page.getByPlaceholder('Ask about accepted returns, terms or missing evidence…').fill('What is the accepted cash yield?');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText(/Cash on cash return: 8.5%/)).toBeVisible();
  await expect(page.getByText(/IRR: Unavailable in the current reviewed analysis/)).toBeVisible();
  await expect(page.getByPlaceholder('Ask about accepted returns, terms or missing evidence…')).toBeEnabled();
});
test('new deal reviews PDF and workbook through Codex paste, Summary, Compare, and exports', async ({ page }) => {
  const { execFileSync } = require('node:child_process');
  const artifacts = JSON.parse(execFileSync('python', ['-c', [
    'from base64 import b64encode',
    'from io import BytesIO',
    'import json',
    'from openpyxl import Workbook',
    'from reportlab.pdfgen.canvas import Canvas',
    'pdf = BytesIO()',
    'memo = Canvas(pdf)',
    'for y, line in enumerate(("Juniper Station Apartments | Offering Memorandum",',
    '    "148 apartments planned in one phase.",',
    '    "Minimum LP commitment: $125,000.",',
    '    "Investment strategy: hold.",',
    '    "Total project cost: $32,000,000.",',
    '    "Project equity requirement: $12,200,000.",',
    '    "Construction loan commitment: $19,800,000.",',
    '    "Base case FY2030 stabilized annual NOI: $2,040,000.")):',
    '    memo.drawString(60, 740 - y * 24, line)',
    'memo.showPage()',
    'for y, line in enumerate(("Juniper Station Apartments | Illustrative LP Returns",',
    '    "Year 1 after stabilization: 3.2% projected annual net LP cash-on-cash.",',
    '    "Annual net LP hold cash-on-cash target, Year 2 after stabilization: 8.9%.",',
    '    "Year 3 after stabilization: 9.1% projected annual net LP cash-on-cash.",',
    '    "Illustrative sale after 5 years: 17.4% projected net LP IRR.",',
    '    "Class A net LP sale cash flows (USD).",',
    '    "Cash flows by period | Year 0 | Year 1 | Year 2",',
    '    "Class A cash flows | ($100,000) | $20,000 | $120,000",',
    '    "Year 1 includes refinance proceeds.",',
    '    "Year 2 includes sale proceeds.")):',
    '    memo.drawString(60, 740 - y * 24, line)',
    'memo.save()',
    'workbook = BytesIO()',
    'model = Workbook()',
    'model.active.title = "Funding and Operations"',
    'for row in (["Metric", "Value", "Basis"], ["Apartment units", 148],',
    '    ["Minimum LP commitment", 125000, "USD"], ["Total project equity", 12200000, "USD"],',
    '    ["Construction loan commitment", 19800000, "USD"], ["Total project cost", 32000000, "USD"],',
    '    ["Stabilized annual NOI", 2160000, "Base case FY2030, USD"]):',
    '    model.active.append(row)',
    'returns = model.create_sheet("Returns")',
    'for row in (["Scenario", "Net LP return", "Basis"],',
    '    ["Year 1 after stabilization", 0.032, "Annual hold cash-on-cash"],',
    '    ["Year 2 after stabilization", 0.089, "Annual hold cash-on-cash target"],',
    '    ["Year 3 after stabilization", 0.091, "Annual hold cash-on-cash"],',
    '    ["Illustrative sale after 5 years", 0.174, "Net LP IRR"]):',
    '    returns.append(row)',
    'for row in range(2, 6):',
    '    returns[f"B{row}"].number_format = "0.0%"',
    'model.save(workbook)',
    'print(json.dumps({"pdf": b64encode(pdf.getvalue()).decode(), "xlsx": b64encode(workbook.getvalue()).decode()}))',
  ].join('\n')], { encoding: 'utf8' }));

  const created = await page.request.post('/api/deals', { data: { project_name: 'Juniper Station Apartments Synthetic Pilot' } });
  expect(created.ok()).toBeTruthy();
  const { id } = await created.json();
  const base = '/api/deals/' + id;
  try {
    for (const [name, mimeType, encoded] of [
      ['pilot-offering.pdf', 'application/pdf', artifacts.pdf],
      ['pilot-underwriting.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', artifacts.xlsx],
    ]) {
      const upload = await page.request.post(base + '/documents/upload', {
        multipart: { file: {name, mimeType, buffer: Buffer.from(encoded, 'base64')} },
      });
      expect(upload.ok()).toBeTruthy();
    }

    await expect.poll(async () => (await page.request.get(base + '/review/packet')).status()).toBe(200);
    const { packet } = await (await page.request.get(base + '/review/packet')).json();
    const memo = packet.sources.find(source => source.filename === 'pilot-offering.pdf');
    const model = packet.sources.find(source => source.filename === 'pilot-underwriting.xlsx');
    const holdPath = 'target_returns.hold_scenario.target_cash_on_cash';
    const salePath = 'target_returns.sale_scenario.net_irr';
    const noiPath = 'financial_projections.stabilized_noi';
    const holdContext = {scenario: 'hold', investor_class: 'lp', basis: 'net', period: 'Year 2 after stabilization'};
    const holdQuote = 'Annual net LP hold cash-on-cash target, Year 2 after stabilization: 8.9%.';
    const memoNoiQuote = 'Base case FY2030 stabilized annual NOI: $2,040,000.';
    const modelNoiQuote = 'A7=Stabilized annual NOI | B7=2160000 | C7=Base case FY2030, USD';
    const unitQuote = 'A2=Apartment units | B2=148';
    const contextText = 'hold · lp · net · Year 2 after stabilization';
    const exportContext = 'Scenario: hold · Investor class: lp · Calculation basis: net · Period: Year 2 after stabilization';
    const returnSource = {document_name: 'pilot-offering.pdf', page: 2, excerpt: holdQuote};

    expect(memo.text).toContain(holdQuote);
    expect(memo.text).toContain(memoNoiQuote);
    expect(model.text).toContain(unitQuote);
    expect(model.text).toContain(modelNoiQuote);
    expect(model.text).toContain('A3=Year 2 after stabilization | B3=0.089 | C3=Annual hold cash-on-cash target');
    expect(model.text).toContain('A5=Illustrative sale after 5 years | B5=0.174 | C5=Net LP IRR');

    // Codex review of the synthetic packet, with only package and document IDs assigned at runtime.
    // Both funding sources cover the $32m cost. The sale IRR has its own scope, and neither
    // FY2030 NOI value can be preferred because the same base case is cited in both sources.
    const facts = [
      {path: 'deal_structure.minimum_investment', value: 125000, currency: 'USD',
        source_doc_id: memo.id, source_page: 1, source_excerpt: 'Minimum LP commitment: $125,000.'},
      {path: 'project_details.unit_count', value: 148,
        source_doc_id: model.id, source_sheet: 'Funding and Operations', source_cell: 'B2', source_excerpt: unitQuote},
      {path: 'deal_structure.total_equity_required', value: 12200000, currency: 'USD',
        source_doc_id: memo.id, source_page: 1, source_excerpt: 'Project equity requirement: $12,200,000.'},
      {path: 'deal_structure.debt_amount', value: 19800000, currency: 'USD', debt_phase: 'construction',
        source_doc_id: memo.id, source_page: 1, source_excerpt: 'Construction loan commitment: $19,800,000.'},
      {path: 'deal_structure.total_project_cost', value: 32000000, currency: 'USD',
        source_doc_id: memo.id, source_page: 1, source_excerpt: 'Total project cost: $32,000,000.'},
      {path: 'construction_costs.total_project_cost', value: 32000000, currency: 'USD',
        source_doc_id: memo.id, source_page: 1, source_excerpt: 'Total project cost: $32,000,000.'},
      {path: 'target_returns.primary_strategy', value: 'hold',
        source_doc_id: memo.id, source_page: 1, source_excerpt: 'Investment strategy: hold.'},
      {path: holdPath, value: 8.9, ...holdContext, source_doc_id: memo.id, source_page: 2, source_excerpt: holdQuote},
      {path: salePath, value: 17.4, scenario: 'sale', investor_class: 'lp', basis: 'net', period: 'After 5 years',
        source_doc_id: memo.id, source_page: 2, source_excerpt: 'Illustrative sale after 5 years: 17.4% projected net LP IRR.'},
      {path: noiPath, value: 2040000, period: 'FY2030', currency: 'USD',
        source_doc_id: memo.id, source_page: 1, source_excerpt: memoNoiQuote},
      {path: noiPath, value: 2160000, period: 'FY2030', currency: 'USD',
        source_doc_id: model.id, source_sheet: 'Funding and Operations', source_cell: 'B7', source_excerpt: modelNoiQuote},
    ].map(fact => ({
      source_page: null, source_sheet: null, source_cell: null,
      scenario: null, investor_class: null, basis: null, period: null, debt_phase: null, currency: null,
      ...fact,
    }));
    const scopeQuote = 'Class A net LP sale cash flows (USD).';
    const yearHeader = 'Cash flows by period | Year 0 | Year 1 | Year 2';
    const cashFlowRow = 'Class A cash flows | ($100,000) | $20,000 | $120,000';
    const pdfCitation = (quote, sourcePage = 2) => ({
      source_doc_id: memo.id, source_page: sourcePage, source_excerpt: quote,
    });
    const result = { package_id: packet.package_id, facts, findings: [{
      kind: 'conflict', title: 'Stabilized NOI differs',
      detail: 'The memo and the workbook report different stabilized NOI for the same fiscal year.',
      citations: [pdfCitation(memoNoiQuote, 1), {
        source_doc_id: model.id, source_sheet: 'Funding and Operations', source_cell: 'B7', source_excerpt: modelNoiQuote,
      }],
    }], return_crosscheck: {
      investor_class: 'Class A', basis: 'net', currency: 'USD', scenario: 'sale', scope_citation: pdfCitation(scopeQuote),
      table: { citation: pdfCitation([scopeQuote, yearHeader, cashFlowRow].join('\n')), year_header: yearHeader, cash_flow_row: cashFlowRow },
      rows: [
        { year: 0, amount: -100000, citation: pdfCitation(cashFlowRow) },
        { year: 1, amount: 20000, citation: pdfCitation(cashFlowRow), flow_scope: 'refinance',
          event_citation: pdfCitation('Year 1 includes refinance proceeds.') },
        { year: 2, amount: 120000, citation: pdfCitation(cashFlowRow), flow_scope: 'sale',
          event_citation: pdfCitation('Year 2 includes sale proceeds.') },
      ],
    }};

    const wrongPage = await page.request.post(base + '/review/draft', {
      data: { package_id: packet.package_id, facts: [{...facts.find(fact => fact.path === holdPath), source_page: 1}] },
    });
    expect(wrongPage.ok()).toBeTruthy();
    expect((await wrongPage.json()).draft.rows[0].issue).toBe('The supporting quote was not found in the cited source. Recheck the page or cell.');

    await dealPage(page, id, 'documents');
    await page.getByRole('button', { name: 'Paste JSON', exact: true }).click();
    await page.getByRole('textbox', { name: 'Codex review JSON' }).fill(['```json', JSON.stringify(result), '```'].join('\n'));
    await page.getByRole('button', { name: 'Check pasted result', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Codex review draft' })).toBeVisible();
    const apply = page.getByRole('button', { name: 'Apply 9 values and save review', exact: true });
    await expect(apply).toBeEnabled();
    await expect(page.getByRole('checkbox', { name: 'Stabilized NOI differs', exact: true })).toBeChecked();
    await expect(page.getByRole('checkbox', { name: 'Save cash-flow check', exact: true })).toBeChecked();
    await expect(page.getByText('9 of 9 cited values selected', { exact: true })).toBeVisible();
    const exceptionList = page.getByRole('region', { name: 'Review exceptions', exact: true });
    const conflict = exceptionList.getByText('Multiple values were proposed for this field. Compare the sources before resolving it.', { exact: true });
    await expect(conflict).toHaveCount(2);
    const conflictChoices = exceptionList.getByRole('checkbox', { name: /stabilized noi/i });
    await expect(conflictChoices).toHaveCount(2);
    for (const choice of await conflictChoices.all()) {
      await expect(choice).toBeDisabled();
      await expect(choice).not.toBeChecked();
    }
    const { draft } = await (await page.request.get(base + '/review/draft')).json();
    expect(draft.rows.filter(row => !row.issue)).toHaveLength(9);
    expect(draft.rows.find(row => row.path === holdPath)).toMatchObject({
      value: 8.9, issue: '', context: holdContext,
      evidence: {source_doc_id: memo.id, source_page: 2, source_excerpt: holdQuote},
    });
    const before = await (await page.request.get(base)).json();
    expect(before.analysis.facts['project_details.unit_count'].value).toBeNull();
    expect(before.analysis.returns.cash_on_cash).toBeNull();
    await apply.click();
    await expect(page.getByText(/9 values applied/)).toBeVisible();
    await expect(conflict).toHaveCount(2);

    const approved = await (await page.request.get(base)).json();
    const scoped = await page.request.put(base + '/analysis/return-context', { data: {
      expected_revision: approved.revision, action: 'scope', path: holdPath, ...holdContext,
      source_doc_id: memo.id, source_page: 2, source_excerpt: holdQuote,
    } });
    expect(scoped.ok()).toBeTruthy();

    await page.getByRole('tab', { name: 'Summary', exact: true }).click();
    const summary = page.getByRole('tabpanel', { name: 'Summary', exact: true });
    await expect(summary.getByText('$125K', { exact: true })).toBeVisible();
    await expect(summary.getByText('148', { exact: true })).toBeVisible();
    await expect(summary.getByRole('heading', { name: 'Construction costs', exact: true })).toBeVisible();
    await expect(summary.getByRole('heading', { name: 'Score breakdown', exact: true })).toBeVisible();
    const coverage = summary.getByRole('region', { name: 'Review coverage', exact: true });
    await expect(coverage.getByText('Sources read', { exact: true })).toBeVisible();
    await expect(coverage.getByRole('listitem').filter({ hasText: 'Construction budget' })).toContainText('Partial coverage');
    await expect(coverage.getByRole('listitem').filter({ hasText: 'Primary return' })).toContainText('Available');
    const checks = summary.getByRole('region', { name: 'Readiness checks', exact: true });
    await expect(checks.getByRole('listitem').filter({ hasText: 'Funding' })).toContainText('Checked');
    await expect(checks.getByRole('listitem').filter({ hasText: 'Construction budget' })).toContainText('Needs evidence');
    await expect(checks.getByRole('listitem').filter({ hasText: 'Return context' })).toContainText('Checked');
    await expect(summary.getByRole('heading', { name: 'Published returns' })).toBeVisible();
    const publishedReturn = summary.getByRole('listitem').filter({hasText: 'Cash-on-cash'});
    await expect(publishedReturn.getByText('8.9%', { exact: true })).toBeVisible();
    await expect(publishedReturn.getByText(contextText, { exact: true })).toBeVisible();
    await publishedReturn.getByRole('button', { name: 'pilot-offering.pdf · page 2', exact: true }).click();
    const evidenceDialog = page.getByRole('dialog', { name: 'pilot-offering.pdf · page 2', exact: true });
    await expect(evidenceDialog.locator('mark')).toHaveText(holdQuote);
    await page.keyboard.press('Escape');
    await expect(summary.getByRole('heading', { name: 'Optional sale scenario', exact: true })).toBeVisible();
    await expect(summary.getByText('Net irr · 17.4%', { exact: true })).toBeVisible();
    const deal = await (await page.request.get(base)).json();
    const cashFlowCheck = deal.analysis.return_crosscheck;
    expect(cashFlowCheck).toMatchObject({status: 'current', annual_irr_pct: 20, cash_flow_multiple: 1.4});
    expect(deal.analysis.findings[0]).toMatchObject({kind: 'conflict', title: 'Stabilized NOI differs', status: 'current'});
    await expect(summary.getByRole('heading', { name: 'PDF cash-flow check', exact: true })).toBeVisible();
    await summary.getByText('Cited cash flows', { exact: true }).click();
    await expect(summary.getByRole('row', { name: /Year 1.*Includes refinance proceeds/ })).toBeVisible();
    await expect(summary.getByRole('row', { name: /Year 2.*Includes sale proceeds/ })).toBeVisible();
    expect(deal.analysis.facts['deal_structure.minimum_investment']).toMatchObject({value: 125000, state: 'checked'});
    expect(deal.analysis.facts['project_details.unit_count'].evidence[0]).toMatchObject({
      document_name: 'pilot-underwriting.xlsx', sheet: 'Funding and Operations', cell: 'B2', excerpt: unitQuote,
    });
    expect(deal.analysis.facts[holdPath]).toMatchObject({value: 8.9, state: 'checked', identity: holdContext, evidence: [returnSource]});
    expect(deal.analysis.facts[salePath]).toMatchObject({value: 17.4, state: 'checked'});
    expect(deal.analysis.returns).toMatchObject({cash_on_cash: 8.9, cash_on_cash_path: holdPath, target_irr: null});
    expect(deal.analysis.facts[noiPath]?.value ?? null).toBeNull();
    const report = await page.request.get('/api/reports/deal/' + id + '/pdf');
    expect(report.ok()).toBeTruthy();
    const reportText = execFileSync('pdftotext', ['-', '-'], {input: await report.body(), encoding: 'utf8'});
    expect(reportText).toContain('$125,000');
    expect(reportText).toMatch(/Unit Count\s+148/);
    expect(reportText).toContain('Cash-on-Cash');
    expect(reportText).toContain('Construction Costs');
    expect(reportText).toContain('8.90%');
    expect(reportText.replace(/\s+/g, ' ')).toContain(exportContext);
    expect(reportText).toContain('pilot-offering.pdf, p. 2');
    expect(reportText).toContain('Optional Sale Scenario');
    expect(reportText).toContain('17.40%');
    expect(reportText).toContain('PDF Cash-Flow Check');
    expect(reportText).toContain('20.00%');
    expect(reportText).not.toMatch(/2,040,000|2,160,000/);

    await page.goto('/compare?ids=' + id + ',1');
    const minRow = page.getByTestId('compare-row-min_investment');
    await expect(minRow.getByText('$125K', { exact: true })).toBeVisible();
    const cashRow = page.getByTestId('compare-row-cash_on_cash');
    await expect(cashRow.getByText('8.9%', { exact: true })).toBeVisible();
    await expect(cashRow.getByText(contextText, { exact: true })).toBeVisible();
    await expect(cashRow.getByText('Different or unspecified context · values only')).toBeVisible();
    const compare = await page.request.post('/api/deals/compare', {data: {deal_ids: [id, 1]}});
    expect(compare.ok()).toBeTruthy();
    const compared = (await compare.json()).deals.find(deal => deal.id === id).analysis;
    expect(compared.readiness).toEqual(deal.analysis.readiness);
    expect(compared.return_crosscheck).toEqual(cashFlowCheck);
    await expect(page.getByRole('region', {name: 'PDF cash-flow checks'})).toContainText('Annual-period IRR');
    expect(compared.facts['project_details.unit_count'].value).toBe(148);
    expect(compared.facts[holdPath]).toMatchObject({value: 8.9, identity: holdContext, evidence: [returnSource]});
    expect(compared.returns.target_irr).toBeNull();
    expect(compared.facts[noiPath]?.value ?? null).toBeNull();
    const exported = await page.request.post('/api/deals/compare/export', {data: {deal_ids: [id, 1]}});
    expect(exported.ok()).toBeTruthy();
    const readWorkbook = input => JSON.parse(execFileSync('python', ['-c', [
      'from io import BytesIO',
      'from openpyxl import load_workbook',
      'import json, sys',
      'book = load_workbook(BytesIO(sys.stdin.buffer.read()), data_only=True)',
      'print(json.dumps({"comparison": {row[0]: row[1] for row in book.active.values if row[0]}, "projections": list(book["Return Projections"].values)[1:] if "Return Projections" in book else [], "sales": list(book["Optional Sale Scenarios"].values)[1:], "checks": list(book["PDF Cash Flow Checks"].values)[1:]}))',
    ].join('\n')], {input, encoding: 'utf8'}));
    const rows = readWorkbook(await exported.body());
    expect(rows.comparison).toMatchObject({
      'Minimum Investment': 125000,
      'Unit Count': 148,
      'Cash-on-Cash': 8.9,
      'Cash-on-Cash Context': exportContext,
      'Cash-on-Cash Evidence': 'pilot-offering.pdf, p. 2',
      'Target IRR': null,
      'Stabilized NOI': null,
    });
    const pilotName = 'Juniper Station Apartments Synthetic Pilot';
    expect(rows.sales.find(row => row[0] === pilotName)).toEqual(expect.arrayContaining([17.4, 'percent', 'pilot-offering.pdf, p. 2']));
    expect(rows.checks).toHaveLength(3);
    expect(rows.checks[1]).toEqual(expect.arrayContaining([pilotName, 20, 1.4, 'Includes refinance proceeds', 'pilot-offering.pdf, p. 2']));

    const schedule = await page.request.put(base + '/analysis/return-schedule', { data: {
      expected_revision: deal.revision, investor_class: 'lp', equity_basis: 'Net LP invested equity',
      period_basis: 'After stabilization', source_doc_id: memo.id, source_page: 2,
      rows: [
        { year: 1, cash_on_cash_pct: 3.2, source_excerpt: 'Year 1 after stabilization: 3.2% projected annual net LP cash-on-cash.' },
        { year: 2, cash_on_cash_pct: 8.9, source_excerpt: holdQuote },
        { year: 3, cash_on_cash_pct: 9.1, source_excerpt: 'Year 3 after stabilization: 9.1% projected annual net LP cash-on-cash.' },
      ],
    } });
    expect(schedule.ok()).toBeTruthy();
    const savedSchedule = (await schedule.json()).analysis.return_schedule;
    await dealPage(page, id, 'documents');
    const refreshes = [memo, model].map(source => page.waitForResponse(response =>
      response.url().endsWith('/api/deals/documents/' + source.id + '/reprocess') && response.request().method() === 'POST'));
    await page.getByRole('button', { name: 'Refresh document text', exact: true }).click();
    for (const response of await Promise.all(refreshes)) expect(response.ok()).toBeTruthy();
    await expect(page.getByRole('status').filter({ hasText: 'Document text refreshed.' })).toBeVisible();

    await page.getByRole('tab', { name: 'Summary', exact: true }).click();
    const projectionTable = summary.getByRole('table', { name: 'Projected cash-on-cash by year' });
    await expect(projectionTable.getByRole('row', { name: /Year 3/ })).toContainText('9.1%');
    await expect(summary.getByRole('heading', { name: 'Published returns' })).toHaveCount(0);
    await expect(summary.getByText('Net irr · 17.4%', { exact: true })).toBeVisible();
    const refreshed = await (await page.request.get(base)).json();
    expect(refreshed.analysis.return_schedule).toEqual(savedSchedule);
    expect(refreshed.analysis.return_crosscheck).toEqual(cashFlowCheck);
    expect(refreshed.analysis.readiness).toEqual(deal.analysis.readiness);
    expect(refreshed.analysis.returns.cash_on_cash).toBeNull();
    expect(refreshed.analysis.facts[holdPath]).toEqual(deal.analysis.facts[holdPath]);
    expect(refreshed.metrics._return_reviews[holdPath]).toEqual(deal.metrics._return_reviews[holdPath]);

    await page.goto('/compare?ids=' + id + ',1');
    await expect(page.getByRole('region', { name: 'Year-by-year return projections' })
      .getByRole('row', { name: /Year 3/ })).toContainText('9.1%');
    const refreshedReport = await page.request.get('/api/reports/deal/' + id + '/pdf');
    expect(refreshedReport.ok()).toBeTruthy();
    const refreshedText = execFileSync('pdftotext', ['-', '-'], {input: await refreshedReport.body(), encoding: 'utf8'});
    expect(refreshedText).toContain('Projected Cash-on-Cash by Year');
    expect(refreshedText).toMatch(/Year 3\s+9\.10%/);
    expect(refreshedText).toContain('Net LP invested equity');
    const refreshedExport = await page.request.post('/api/deals/compare/export', {data: {deal_ids: [id, 1]}});
    expect(refreshedExport.ok()).toBeTruthy();
    const refreshedRows = readWorkbook(await refreshedExport.body());
    expect(refreshedRows.comparison['Cash-on-Cash']).toBeNull();
    expect(refreshedRows.projections.filter(row => row[0] === pilotName).map(row => row.slice(1, 3))).toEqual([[1, 3.2], [2, 8.9], [3, 9.1]]);
    expect(refreshedRows.sales).toEqual(rows.sales);

    const refreshedPacket = (await (await page.request.get(base + '/review/packet')).json()).packet;
    const incompleteReturn = await page.request.post(base + '/review/draft', {
      data: {package_id: refreshedPacket.package_id, facts: [{...facts.find(fact => fact.path === holdPath), period: null}]},
    });
    expect(incompleteReturn.ok()).toBeTruthy();
    expect((await incompleteReturn.json()).draft.rows[0]).toMatchObject({
      context_changed: true, missing_context: ['return period'],
    });
    await dealPage(page, id, 'documents');
    const unchecked = page.getByRole('region', {name: 'Review exceptions'}).getByRole('checkbox', {name: /cash.on.cash/i});
    await expect(unchecked).not.toBeChecked();
    await expect(page.getByRole('button', {name: 'Apply selected values'})).toBeDisabled();

    await page.getByRole('tab', {name: 'Questions', exact: true}).click();
    const findings = page.getByRole('region', {name: 'Source findings', exact: true});
    await findings.getByRole('button', {name: 'Record decision', exact: true}).click();
    await findings.getByRole('textbox', {name: 'Decision and basis'}).fill('Retain both source quotes and leave this figure open.');
    await findings.getByRole('button', {name: 'Save decision', exact: true}).click();
    await expect(findings.getByText('Decision recorded', {exact: true})).toBeVisible();
    const replacement = await page.request.post(base + '/documents/upload', {
      multipart: {file: {name: 'pilot-offering.pdf', mimeType: 'application/pdf',
        buffer: Buffer.concat([Buffer.from(artifacts.pdf, 'base64'), Buffer.from('\n% replacement edition\n')])}},
    });
    expect(replacement.ok()).toBeTruthy();
    const stale = (await (await page.request.get(base)).json()).analysis;
    expect(stale.findings[0]).toMatchObject({status: 'needs_review', decision: {text: 'Retain both source quotes and leave this figure open.'}});
    expect(stale.return_crosscheck).toMatchObject({status: 'needs_review', annual_irr_pct: null, cash_flow_multiple: null});
  } finally {
    expect((await page.request.delete(base)).ok()).toBeTruthy();
  }
});

test('all three deals compare with matching accepted returns and export', async ({ page }, info) => {
  await page.goto('/compare');
  await page.getByRole('button', { name: 'Pick deals', exact: true }).click();
  const picker = page.getByRole('dialog');
  for (const name of ['Sample Hold', 'Sample Questions', 'Sample Sale'])
    await picker.getByRole('button', { name: new RegExp(`^${name}`) }).click();
  await picker.getByRole('button', { name: 'Compare (3)', exact: true }).click();
  await expect(page.getByText(/3 deals ·/)).toBeVisible();
  await expect(page.getByRole('main').getByText('8.5%', { exact: true })).toBeVisible();
  await expect(page.getByRole('main').getByText('27.5%', { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Best overall/)).toHaveCount(0);
  await expect(page.getByLabel('Leading value for this metric')).toHaveCount(0);
  await page.getByText(/Comparison options ·/).click();
  await page.getByRole('button', { name: 'Winners', exact: true }).click();
  await expect(page).toHaveURL(/mode=winners/);
  await expect(page.getByText(/Best overall/)).toHaveCount(0);
  await expect(page.getByLabel('Leading value for this metric').first()).toBeVisible();
  await expect(page.getByText('Different or unspecified context · values only').first()).toBeVisible();
  await page.getByRole('button', { name: 'Values', exact: true }).click();
  await expect(page).not.toHaveURL(/mode=/);
  await expect(page.getByLabel('Leading value for this metric')).toHaveCount(0);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export Excel', exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toMatch(/\.xlsx$/);
  const bytes = await fs.readFile(await file.path());
  expect(bytes.subarray(0, 2).toString()).toBe('PK');
  await page.screenshot({ path: info.outputPath('comparison.png'), fullPage: true });
});

test('developer detail and populated portfolio load through real routes', async ({ page }) => {
  await page.goto('/developers');
  await page.getByRole('link', { name: /^Synthetic Sponsor/ }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic Sponsor', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sample Hold', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Portfolio', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Synthetic Position', exact: true })).toBeVisible();
  await expect(page.getByText('No positions yet', { exact: true })).toHaveCount(0);
  const pdf = await page.request.get('/api/reports/portfolio/quarterly/pdf');
  expect(pdf.ok()).toBeTruthy();
  expect((await pdf.body()).subarray(0, 4).toString()).toBe('%PDF');
});

test('optional location outage leaves deal summary and navigation available', async ({ page }) => {
  await page.route('**/api/deals/1/location**', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic location service outage' }) }));
  await dealPage(page, 1, 'location');
  await expect(page.getByText(/Synthetic location service outage/).first()).toBeVisible();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'One reviewed view of the deal', exact: true })).toBeVisible();
});

test('viewer can read accepted facts but cannot mutate deal records', async ({ browser }) => {
  const context = await browser.newContext({ storageState: '.browser-auth/viewer.json', baseURL: 'http://127.0.0.1:3000' });
  const page = await context.newPage();
  await handleWelcomeTour(page);
  await dealPage(page, 1, 'questions');
  await expect(page.getByRole('tab', { name: 'Assistant', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Resolve with an analyst decision', exact: true })).toHaveCount(0);
  const denied = await page.request.put('/api/deals/1', { data: { notes: 'Viewer must not write' } });
  expect(denied.status()).toBe(403);
  await context.close();
});

test('mobile summary keeps the main workflow reachable', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await dealPage(page);
  await expect(page.getByRole('heading', { name: 'Sample Hold', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'New Deal', exact: true })).toBeInViewport();
  await expect(page.getByRole('link', { name: /Resolve next question|Inspect reviewed evidence/ }).first()).toBeInViewport();
  await page.screenshot({ path: info.outputPath('mobile-brief.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole('tab', { name: 'Questions', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Review exceptions', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Documents', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Choose files', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath('mobile-documents.png'), fullPage: true });
});

test('legacy entry opens the current application', async ({ page }) => {
  await page.goto('/legacy');
  await expect(page).toHaveURL('http://127.0.0.1:3000/');
  await expect(page.getByRole('heading', { name: 'Deal Pipeline', exact: true })).toBeVisible();
  await expect(page.getByText('Switch to legacy UI →')).toHaveCount(0);
});

test('upload-first intake creates a deal from two documents without manual details', async ({ page }, info) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'New Deal', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'New deal', exact: true });
  await expect(drawer.getByText('Drop the deal documents here')).toBeVisible();
  await drawer.getByLabel('Choose deal documents').setInputFiles([
    { name: 'Browser_Offering.csv', mimeType: 'text/csv', buffer: Buffer.from('Metric,Value\nUnits,12\n') },
    { name: 'Browser_Terms.csv', mimeType: 'text/csv', buffer: Buffer.from('Metric,Value\nMinimum investment,50000\n') },
  ]);
  await page.screenshot({ path: info.outputPath('upload-first.png'), fullPage: true });
  await drawer.getByRole('button', { name: 'Upload and review', exact: true }).click();
  await expect(page).toHaveURL(/\/deals\/\d+\?tab=documents$/);
  await expect(page.getByRole('heading', { name: 'Browser Offering', exact: true })).toBeVisible();
  const id = Number(new URL(page.url()).pathname.split('/').pop());
  const deal = await (await page.request.get(`/api/deals/${id}`)).json();
  expect(deal.developer_id).toBeNull();
  expect(deal.documents).toHaveLength(2);
  expect(deal.target_irr).toBeNull();
  await page.getByRole('button', { name: 'New Deal', exact: true }).click();
  await expect(drawer.getByLabel('Deal name (optional)')).toHaveValue('');
  await expect(drawer.getByText('Browser_Offering.csv', { exact: true })).toHaveCount(0);
});

test('failed assistant request retains question and can be retried', async ({ page }) => {
  await dealPage(page, 1, 'chat');
  await expect(page).toHaveURL(/tab=chat$/);
  const input = page.getByPlaceholder('Ask about accepted returns, terms or missing evidence…');
  await expect(input).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/tab=chat$/);
  await expect(input).toBeVisible();
  await page.route('**/api/chat', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic temporary interruption' }) }), { times: 1 });
  await input.fill('Show investment terms');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(input).toHaveValue('Show investment terms');
  await expect(page.getByText("Couldn't send message", { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText(/Minimum investment: unspecified 25,000/).last()).toBeVisible();
});

test('paid review pause is visible while saved documents and free source lookup work', async ({ page }) => {
  const message = 'Paid AI review is paused until extraction validation is complete. Document reading, saved analyses, calculations, exports and source lookup remain available.';
  await page.route('**/api/healthz', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'degraded', environment: { anthropic: { configured: false, paused: true, message } } }) }));
  await dealPage(page, 1, 'documents');
  await expect(page.getByRole('link', { name: 'Review with Codex', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Review documents', exact: true })).toHaveCount(0);
  await page.getByText('Some automatic checks are unavailable. Saved evidence still works.', { exact: true }).click();
  await expect(page.getByText(message, { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Choose files', exact: true })).toBeEnabled();
  await page.getByRole('tab', { name: /Assistant/ }).click();
  await expect(page.getByPlaceholder('Ask about accepted returns, terms or missing evidence…')).toBeVisible();
});

test('completed document review restores controls after Strict Mode setup', async ({ page }) => {
  await page.route('**/api/healthz', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok', environment: { anthropic: { configured: true } } }) }));
  // Test the browser lifecycle only. The provider/review worker is disabled
  // in this harness; no extraction request leaves the disposable test app.
  await page.route('**/api/deals/1/review', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'queued' }) }));
  await page.route('**/api/deals/1/quality', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ pipeline: { status: 'complete', step: 'score' } }) }));
  await dealPage(page);
  const tools = page.locator('details#analyst-tools');
  await tools.locator('summary').click();
  const button = tools.getByRole('button', { name: 'Review documents again', exact: true });
  if (!(await button.isVisible())) await tools.locator('summary').click();
  await button.click();
  await expect(page.getByText('Document review complete', { exact: true }).last()).toBeVisible();
  if (!(await button.isVisible())) await tools.locator('summary').click();
  await expect(button).toBeEnabled();
});

test('manual deal details persist and financial locks remain unchanged', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'New Deal', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'New deal', exact: true });
  await drawer.getByRole('button', { name: 'Enter details', exact: true }).click();
  await drawer.getByLabel('Project name').fill('Manual browser draft');
  await drawer.getByRole('button', { name: 'Create deal', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Manual browser draft', exact: true })).toBeVisible();
  const id = Number(new URL(page.url()).pathname.split('/').pop());
  await page.request.post(`/api/deals/${id}/fields/edit`, { data: { path: 'deal_structure.minimum_investment', value: 25000, lock: true } });
  await page.reload();
  await page.getByRole('tab', { name: 'Analysis', exact: true }).click();
  await page.getByText('Edit deal details', { exact: true }).click();
  await page.getByLabel('Deal name', { exact: true }).fill('Updated browser draft');
  await page.getByLabel('Decision status', { exact: true }).selectOption('interested');
  await page.getByLabel('Deal notes', { exact: true }).fill('Browser evidence follow-up');
  await page.getByRole('button', { name: 'Save deal details', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Updated browser draft', exact: true })).toBeVisible();
  const detail = await (await page.request.get(`/api/deals/${id}`)).json();
  expect(detail.notes).toBe('Browser evidence follow-up');
  expect(detail.status).toBe('interested');
  expect(detail.minimum_investment).toBe(25000);
  expect(detail.metrics._locks['deal_structure.minimum_investment']).toBe(true);
});

test('sponsor notes can be edited and remain saved', async ({ page }) => {
  await page.goto('/developers/1');
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'Edit developer', exact: true });
  await drawer.getByLabel('Sponsor notes', { exact: true }).fill('Browser-reviewed sponsor note');
  await drawer.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(drawer).not.toBeVisible();
  expect((await (await page.request.get('/api/developers/1')).json()).notes).toBe('Browser-reviewed sponsor note');
  await page.reload();
  await page.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(page.getByLabel('Sponsor notes', { exact: true })).toHaveValue('Browser-reviewed sponsor note');
});

test('portfolio creation, editing, distribution, exit and undo work together', async ({ page }) => {
  await page.goto('/portfolio');
  await page.getByRole('button', { name: 'Add investment', exact: true }).first().click();
  let drawer = page.getByRole('dialog', { name: 'Add investment', exact: true });
  await drawer.getByRole('button', { name: 'Manual entry', exact: true }).click();
  await drawer.getByLabel('Project name').fill('Browser Position');
  await drawer.getByLabel('Amount invested').fill('1000');
  await drawer.getByLabel('Investment date').fill('2025-01-01');
  await drawer.getByRole('button', { name: 'Add investment', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Browser Position', exact: true })).toBeVisible();
  const investments = await (await page.request.get('/api/investments/')).json();
  const id = investments.find(position => position.project_name === 'Browser Position').id;
  const card = page.getByTestId(`investment-${id}`);
  await card.getByRole('button', { name: 'Position actions', exact: true }).click();
  await card.getByRole('button', { name: 'Edit investment', exact: true }).click();
  drawer = page.getByRole('dialog', { name: 'Edit investment', exact: true });
  await drawer.getByLabel('Amount invested').fill('2000');
  await drawer.getByRole('button', { name: 'Save investment', exact: true }).click();
  await expect(drawer).not.toBeVisible();
  await card.getByRole('button', { name: 'Position actions', exact: true }).click();
  await card.getByRole('button', { name: 'Add distribution', exact: true }).click();
  const distribution = page.getByRole('dialog', { name: 'Add distribution', exact: true });
  await distribution.getByLabel('Amount', { exact: true }).fill('100');
  await distribution.getByRole('button', { name: 'Add distribution', exact: true }).click();
  await expect(distribution).not.toBeVisible();
  await card.getByRole('button', { name: 'Position actions', exact: true }).click();
  await card.getByRole('button', { name: 'Mark exited…', exact: true }).click();
  const exit = page.getByRole('dialog', { name: 'Mark as exited', exact: true });
  await exit.getByLabel('Exit amount', { exact: true }).fill('3000');
  await exit.getByRole('button', { name: 'Mark exited', exact: true }).click();
  await expect(exit).not.toBeVisible();
  const actual = await (await page.request.get(`/api/investments/${id}`)).json();
  expect(actual.amount_invested).toBe(2000);
  expect(actual.total_distributions).toBe(100);
  expect(actual.exit_amount).toBe(3000);
  expect(actual.actual_multiple).toBe(1.55);
  page.once('dialog', dialog => dialog.accept());
  await card.getByRole('button', { name: 'Position actions', exact: true }).click();
  await card.getByRole('button', { name: 'Delete', exact: true }).click();
  await expect(card).not.toBeVisible();
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(card).toBeVisible();
  expect((await page.request.get(`/api/investments/${id}`)).status()).toBe(200);
});

test('comparison presets, custom rows and incompatible modes remain usable', async ({ page }) => {
  await page.goto('/compare?ids=1,2,3');
  await page.getByText(/Comparison options ·/).click();
  await expect(page.getByText(/3 deals ·/)).toBeVisible();
  for (const [label, preset] of [['Returns', 'returns'], ['Leverage & structure', 'structure'], ['Risk profile', 'risk'], ['Market & location', 'market'], ['Sponsor quality', 'sponsor'], ['Underwriting conservatism', 'underwriting'], ['All', 'all']]) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`preset=${preset}`));
  }
  await page.getByRole('button', { name: 'Build your own', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: 'Build your own preset', exact: true });
  await drawer.getByRole('button', { name: 'Clear', exact: true }).click();
  await drawer.getByRole('button', { name: /^Cash-on-Cash/ }).click();
  await drawer.getByRole('button', { name: 'Save preset', exact: true }).click();
  const row = page.getByTestId('compare-row-cash_on_cash');
  await expect(row).toBeVisible();
  await page.getByRole('button', { name: 'Normalized', exact: true }).click();
  await expect(row.getByRole('progressbar')).toHaveCount(0);
  await expect(row.getByText('Different or unspecified context · values only')).toBeVisible();
  await page.getByRole('button', { name: 'Deltas', exact: true }).click();
  await page.getByRole('button', { name: /^Baseline:/ }).click();
  await page.getByRole('button', { name: 'Sample Questions', exact: true }).click();
  await expect(page).toHaveURL(/baseline=2/);
  await page.reload();
  await expect(page.getByTestId('compare-row-cash_on_cash')).toBeVisible();
});

test('sign-out and an expired session return to sign-in', async ({ browser }) => {
  const context = await browser.newContext({ storageState: '.browser-auth/admin.json', baseURL: 'http://127.0.0.1:3000' });
  const page = await context.newPage();
  await handleWelcomeTour(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto('/deals/1');
  await expect(page).toHaveURL(/\/login\?next=/);
  await context.addCookies([{ name: 'kenyon_session', value: 'synthetic-expired-session', domain: '127.0.0.1', path: '/' }]);
  await page.goto('/deals/1');
  await expect(page).toHaveURL(/\/login\?next=/);
  await expect(page.getByLabel('Username', { exact: true })).toBeVisible();
  await context.close();
});

test('source search opens the current excerpt without leaving the deal', async ({ page }, info) => {
  await dealPage(page);
  await page.keyboard.press('Control+k');
  await page.getByPlaceholder('Search deals, sponsors or source evidence…').fill('hold cash');
  await page.getByRole('option', { name: /Sample Hold · sample-hold.pdf p1/ }).first().click();
  const viewer = page.getByRole('dialog');
  await expect(viewer.getByRole('heading', { name: 'sample-hold.pdf · page 1' })).toBeVisible();
  await expect(viewer.getByText(/Current active source/)).toBeVisible();
  await expect(viewer.locator('mark')).toContainText('Hold cash-on-cash return: 8.5%');
  await expect(viewer.getByRole('link', { name: 'Open / download original' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('source-excerpt.png'), fullPage: true });
});

test('linked investment previews the accepted revision and records a dated valuation', async ({ page }) => {
  await page.goto('/portfolio');
  await page.getByRole('button', { name: 'Add investment', exact: true }).first().click();
  const drawer = page.getByRole('dialog');
  await drawer.getByRole('combobox', { name: 'Deal', exact: true }).selectOption('1');
  await drawer.getByRole('button', { name: 'Manual entry', exact: true }).click();
  await drawer.getByLabel('Proj IRR (%)', { exact: true }).fill('99');
  await drawer.getByRole('button', { name: 'Link existing deal', exact: true }).click();
  await expect(drawer.getByText(/Analysis revision/)).toBeVisible();
  await drawer.getByRole('spinbutton', { name: 'Amount invested', exact: true }).fill('4321');
  await drawer.getByLabel('Investment date', { exact: true }).fill('2024-01-01');
  await drawer.getByText('Optional current valuation', { exact: true }).click();
  await drawer.getByLabel('Residual value', { exact: true }).fill('4500');
  await drawer.getByLabel('Valuation date', { exact: true }).fill('2025-01-01');
  await drawer.getByRole('button', { name: 'Add investment', exact: true }).click();
  await expect(drawer).toBeHidden();
  const rows = await (await page.request.get('/api/investments/')).json();
  const row = rows.find(inv => inv.amount_invested === 4321);
  expect(row.developer_id).toBe(1);
  expect(row.source_analysis_version).toBeGreaterThan(0);
  expect(row.residual_value).toBe(4500);
  expect(row.projected_irr).toBeNull();
  const performance = await (await page.request.get(`/api/investments/${row.id}/performance`)).json();
  expect(performance.tvpi).toBeGreaterThan(1);
  expect(performance.dpi).toBe(0);
  await page.request.delete(`/api/investments/${row.id}`);
});

test('failed history is unavailable rather than an empty conversation and can retry', async ({ page }) => {
  // Keep the outage active through development Strict Mode's extra setup.
  let historyOutage = true;
  await page.route('**/api/chat/history/1', route => historyOutage ? route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic history outage' }) }) : route.continue());
  await dealPage(page, 1, 'chat');
  await expect(page.getByText(/History is unavailable/)).toBeVisible();
  await expect(page.getByText('Understand the reviewed deal', { exact: true })).toHaveCount(0);
  historyOutage = false;
  await page.getByRole('button', { name: 'Retry history', exact: true }).click();
  await expect(page.getByText(/History is unavailable/)).toHaveCount(0);
  await expect(page.getByText('Loading history…', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Earlier analysis · open archived reply', { exact: true }).first()).toBeVisible();
});

test('map rendering and sourced public statistics remain separate from rent judgments', async ({ page }, info) => {
  await page.route('**/api/deals/1/location**', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ lat: 37.7749, lng: -122.4194, radius_m: 1609, categories: {}, fmr: { zip: '94103', year: 2026, metro: 'Synthetic metro', rents: { studio: 1000, br1: 1200, br2: 1500, br3: 1800 } }, fetched_at: Date.now() / 1000 }) }));
  await page.route('**/api/deals/1/public-context', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'available', message: 'Synthetic Census test estimate.', asset_guidance: 'Apartment rent evidence still needed', research_url: 'https://www.census.gov/', profile_supported: true, observations: [{ metric: 'population', label: 'Population', value: 123456, margin_of_error: 300, confidence_level: '90%', unit: 'people', observed_period: '2020–2024', geography_name: 'Synthetic city', geography_level: 'place', geography_id: '1600000US0612345', retrieved_at: '2026-10-28', publication_date: null, source_url: 'https://api.census.gov/data/2024/acs/acs5' }] }) }));
  await dealPage(page, 1, 'location');
  await expect(page.locator('.maplibregl-canvas')).toBeVisible();
  await expect(page.getByText('123,456', { exact: true })).toBeVisible();
  await expect(page.getByText('$1,500', { exact: true })).toBeVisible();
  await page.getByText('Source, uncertainty and freshness', { exact: true }).click();
  await expect(page.getByText(/Margin of error: 300 at 90% confidence/)).toBeVisible();
  await expect(page.getByRole('link', { name: 'Census source query', exact: true })).toHaveAttribute('href', 'https://api.census.gov/data/2024/acs/acs5');
  await expect(page.getByText(/above market — aggressive|within market range/)).toHaveCount(0);
  await page.getByRole('button', { name: 'Streets', exact: true }).click();
  await page.screenshot({ path: info.outputPath('map-public-context.png'), fullPage: true });
});

test('saved deal routes hydrate consistently after repeated reloads', async ({ page }) => {
  test.setTimeout(180000);
  const created = await page.request.post('/api/deals', { data: { project_name: 'Repeated route check' } });
  expect(created.ok()).toBeTruthy();
  const id = (await created.json()).id;
  for (let cycle = 0; cycle < (process.env.BROWSER_DIAGNOSTIC === '1' ? 1 : 5); cycle++) {
    for (const dealId of [1, 2, 3, id]) {
      for (const tab of ['overview', 'questions', 'documents']) {
        await dealPage(page, dealId, tab);
        await page.reload();
        await expect(page.getByRole('tab', { name: 'Assistant', exact: true })).toBeVisible();
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      }
    }
  }
});
