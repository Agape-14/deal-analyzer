const { test: base, expect } = require('@playwright/test');
const fs = require('node:fs/promises');

// These tests run against the real local API and compiled Next frontend.
// Only the optional upstream outage case is mocked. No private data is imported.
const test = base.extend({
  page: async ({ page, context }, use) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await context.route('**/*', route => {
      const url = new URL(route.request().url());
      return ['127.0.0.1', 'localhost'].includes(url.hostname) ? route.continue() : route.abort();
    });
    await use(page);
    expect(errors, 'Uncaught browser exceptions').toEqual([]);
  },
});

async function dealPage(page, id = 1, tab) {
  await page.goto(`/deals/${id}${tab ? `?tab=${tab}` : ''}`);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
}

test('real sign-in rejects bad credentials and refreshes authenticated controls', async ({ browser }) => {
  const context = await browser.newContext();
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
  await expect(page.getByRole('tab', { name: 'Analyst', exact: true })).toBeVisible();
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

test('hold summary withholds unrelated exit returns and stale status claims', async ({ page }, info) => {
  await dealPage(page);
  const main = page.getByRole('main');
  await expect(main.getByText('8.5%', { exact: true })).toBeVisible();
  await expect(main.getByText('27.5%', { exact: true })).toHaveCount(0);
  await expect(main.getByText('4.25x', { exact: true })).toHaveCount(0);
  await expect(main.getByRole('heading', { name: 'Investment considerations' })).toHaveCount(0);
  await page.getByRole('tab', { name: 'Questions', exact: true }).click();
  await expect(page.getByText(/No material questions remain/)).toBeVisible();
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
  await expect(page.getByText(/No material questions remain/)).toBeVisible();
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
  await expect(dialog.getByText(/If the preview is blank/)).toBeVisible();
  const original = await page.request.get('/api/deals/documents/1/file');
  expect(original.ok()).toBeTruthy();
  expect((await original.body()).subarray(0, 4).toString()).toBe('%PDF');
  expect(original.headers()['x-frame-options']).toBe('SAMEORIGIN');
  expect(original.headers()['content-security-policy']).toContain("frame-ancestors 'self'");
  await expect(dialog.getByRole('link', { name: 'Download', exact: true })).toHaveAttribute('href', '/api/deals/documents/1/file');
  await dialog.getByRole('button', { name: 'Close', exact: true }).click();
});

test('spreadsheet limitations are visible and duplicate upload is idempotent', async ({ page }) => {
  await dealPage(page, 2, 'documents');
  await expect(page.getByText(/Uses 2 external workbook links/)).toBeVisible();
  await expect(page.getByText(/Some spreadsheet rows or columns exceed/)).toBeVisible();
  const input = page.locator('input[type=file]');
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

test('unsupported models show reasons and chat failure remains recoverable', async ({ page }) => {
  await dealPage(page, 1, 'cashflow');
  await expect(page.getByText(/Refinancing or cash-out terms require/)).toBeVisible();
  await expect(page.getByText(/Multiple equity classes require/)).toBeVisible();
  await page.getByRole('tab', { name: 'Analyst', exact: true }).click();
  await expect(page.getByText(/AI explanations. Use Summary for accepted facts/)).toBeVisible();
  await expect(page.getByText('Synthetic saved conversation. Summary holds the accepted figures.')).toBeVisible();
  await page.getByPlaceholder('Ask about IRR, leverage, sponsor quality, red flags…').fill('What is the accepted cash yield?');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText("Couldn't send message", { exact: true })).toBeVisible();
  await expect(page.getByText(/AI chat is unavailable/)).toBeVisible();
  await expect(page.getByPlaceholder('Ask about IRR, leverage, sponsor quality, red flags…')).toBeEnabled();
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
  await expect(page.getByRole('heading', { name: 'Sample Hold', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Portfolio', exact: true }).click();
  await expect(page.getByText('Synthetic Position', { exact: true })).toBeVisible();
  await expect(page.getByText('No positions yet', { exact: true })).toHaveCount(0);
  const pdf = await page.request.get('/api/reports/portfolio/quarterly/pdf');
  expect(pdf.ok()).toBeTruthy();
  expect((await pdf.body()).subarray(0, 4).toString()).toBe('%PDF');
});

test('optional location outage leaves deal summary and navigation available', async ({ page }) => {
  await page.route('**/api/deals/1/location**', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic location service outage' }) }));
  await dealPage(page, 1, 'location');
  await expect(page.getByText(/Synthetic location service outage/)).toBeVisible();
  await page.getByRole('tab', { name: 'Summary', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'One reviewed view of the deal', exact: true })).toBeVisible();
});

test('viewer can read accepted facts but cannot mutate deal records', async ({ browser }) => {
  const context = await browser.newContext({ storageState: '.browser-auth/viewer.json', baseURL: 'http://127.0.0.1:3000' });
  const page = await context.newPage();
  await dealPage(page, 1, 'questions');
  await expect(page.getByRole('tab', { name: 'Analyst', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Resolve with an analyst decision', exact: true })).toHaveCount(0);
  const denied = await page.request.put('/api/deals/1', { data: { notes: 'Viewer must not write' } });
  expect(denied.status()).toBe(403);
  await context.close();
});

test('mobile summary keeps the main workflow reachable', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await dealPage(page);
  await expect(page.getByRole('heading', { name: 'Sample Hold', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Questions', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Only the questions that affect the summary', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Documents', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Choose files', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('mobile-documents.png'), fullPage: true });
});
