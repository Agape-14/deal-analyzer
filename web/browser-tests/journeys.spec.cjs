const { test: base, expect } = require('@playwright/test');
const fs = require('node:fs/promises');

async function handleWelcomeTour(page) {
  await page.addLocatorHandler(page.getByRole('dialog', { name: 'Welcome to Kenyon', exact: true }), async () => {
    await page.getByRole('button', { name: 'Skip tour', exact: true }).click();
  });
}

// These tests run against the real local API and compiled Next frontend.
// Only the optional upstream outage case is mocked. No private data is imported.
const test = base.extend({
  page: async ({ page, context }, use) => {
    const errors = [];
    page.on('pageerror', error => errors.push(error.stack || error.message));
    await handleWelcomeTour(page);
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

test('hold summary withholds unrelated exit returns and stale status claims', async ({ page }, info) => {
  await dealPage(page);
  const main = page.getByRole('main');
  const accepted = await (await page.request.get('/api/deals/1')).json();
  expect(accepted.target_irr).toBeNull();
  expect(accepted.target_equity_multiple).toBeNull();
  await expect(main.getByText('8.5%', { exact: true })).toBeVisible();
  await expect(main.getByText('27.5%', { exact: true })).toHaveCount(0);
  await expect(main.getByText(/4\.(25|3)x/)).toHaveCount(0);
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
  await page.getByRole('button', { name: 'New Deal', exact: true }).click();
  await expect(drawer.getByLabel('Deal name (optional)')).toHaveValue('');
  await expect(drawer.getByText('Browser_Offering.csv', { exact: true })).toHaveCount(0);
});

test('unsupported models show reasons and assistant works without provider credits', async ({ page }) => {
  await dealPage(page, 1, 'cashflow');
  await expect(page.getByRole('status').filter({ hasText: 'Projection needs source-supported assumptions.' })).toBeVisible();
  await expect(page.getByText(/Missing or disputed assumptions: avg rent per unit/)).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Waterfall unavailable: Refinancing distributions require' })).toBeVisible();
  await expect(page.getByText(/Multiple equity classes require/)).toBeVisible();
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  await expect(page.getByText(/Answers from the current reviewed facts/)).toBeVisible();
  await expect(page.getByText('Earlier analysis · open archived reply', { exact: true })).toBeVisible();
  await expect(page.getByText('Synthetic saved conversation. Summary holds the accepted figures.')).not.toBeVisible();
  await page.getByPlaceholder('Ask about accepted returns, terms or missing evidence…').fill('What is the accepted cash yield?');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText(/Cash on cash return: 8.5%/)).toBeVisible();
  await expect(page.getByText(/IRR: Unavailable in the current reviewed analysis/)).toBeVisible();
  await expect(page.getByPlaceholder('Ask about accepted returns, terms or missing evidence…')).toBeEnabled();
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
  await expect(page.getByText(/Synthetic location service outage/)).toBeVisible();
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
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.getByRole('tab', { name: 'Questions', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Only the questions that affect the summary', exact: true })).toBeVisible();
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
});

test('failed assistant request retains question and can be retried', async ({ page }) => {
  await dealPage(page, 1, 'chat');
  await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
  const input = page.getByPlaceholder('Ask about accepted returns, terms or missing evidence…');
  await page.route('**/api/chat', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Synthetic temporary interruption' }) }), { times: 1 });
  await input.fill('Show investment terms');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(input).toHaveValue('Show investment terms');
  await expect(page.getByText("Couldn't send message", { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText(/Minimum investment: unspecified 25,000/).last()).toBeVisible();
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
