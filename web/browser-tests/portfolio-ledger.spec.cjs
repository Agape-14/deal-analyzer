const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');

test.beforeEach(async ({ page, context }) => {
  await page.addLocatorHandler(page.getByRole('dialog', { name: 'Welcome to Kenyon', exact: true }), async () => {
    await page.getByRole('button', { name: 'Skip tour', exact: true }).click();
  });
  await context.route('**/*', route => ['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
});

test('portfolio payments edit, remove, persist undo, and retry without duplication', async ({ page }) => {
  const created = await page.request.post('/api/investments/', { data: {
    project_name: 'Synthetic Payment History', investment_date: '2024-01-01', amount_invested: 1000,
  } });
  expect(created.ok()).toBeTruthy();
  const { id } = await created.json();
  const base = `/api/investments/${id}`;
  try {
    await page.goto('/portfolio');
    const card = page.getByTestId(`investment-${id}`);
    await card.getByRole('button', { name: 'Position actions', exact: true }).click();
    await card.getByRole('button', { name: 'Add distribution', exact: true }).click();
    const modal = page.getByRole('dialog', { name: 'Add distribution', exact: true });
    await modal.getByLabel('Amount', { exact: true }).fill('100');
    await modal.getByLabel('Distribution date', { exact: true }).fill('2025-01-01');
    await modal.getByLabel('Distribution notes', { exact: true }).fill('Original payment');
    const sent = page.waitForRequest(request => request.url().endsWith(`${base}/distributions`) && request.method() === 'POST');
    await modal.getByRole('button', { name: 'Add distribution', exact: true }).click();
    const request = await sent;
    await expect(modal).toBeHidden();
    const retry = await page.request.post(`${base}/distributions`, { data: request.postDataJSON() });
    expect(retry.ok()).toBeTruthy();
    expect((await retry.json()).replayed).toBe(true);
    await card.getByText('Payment history (1)', { exact: true }).click();
    const row = card.getByTestId('distribution-ledger').getByTestId(/^distribution-\d+$/);
    await row.getByRole('button', { name: 'Edit payment', exact: true }).click();
    const edit = page.getByRole('dialog', { name: 'Edit distribution', exact: true });
    await edit.getByLabel('Amount', { exact: true }).fill('125');
    await edit.getByLabel('Distribution date', { exact: true }).fill('2025-01-15');
    await edit.getByRole('button', { name: 'Save distribution', exact: true }).click();
    await expect(edit).toBeHidden();
    await expect(row).toContainText('$125');
    await row.getByRole('button', { name: 'Remove payment', exact: true }).click();
    await expect(card.getByText('Payment history (0)', { exact: true })).toBeVisible();
    let stored = await (await page.request.get(base)).json();
    expect(stored.total_distributions).toBe(0);
    expect(stored.distribution_ledger).toHaveLength(1);
    expect(stored.distribution_ledger[0].deleted_at).toBeTruthy();
    await page.reload();
    await card.getByText('Payment history (0)', { exact: true }).click();
    await card.getByLabel('Show removed payments (1)', { exact: true }).check();
    await card.getByRole('button', { name: 'Restore payment', exact: true }).click();
    await expect(card.getByText('Payment history (1)', { exact: true })).toBeVisible();
    stored = await (await page.request.get(base)).json();
    expect(stored.total_distributions).toBe(125);
    expect(stored.distributions).toHaveLength(1);
    expect(stored.distribution_ledger[0].history.map(event => event.action)).toEqual(['edited', 'removed', 'restored']);
    await row.getByRole('button', { name: 'Remove payment', exact: true }).click();
    await page.getByRole('button', { name: 'Undo payment removal', exact: true }).last().click();
    await expect.poll(async () => (await (await page.request.get(base)).json()).total_distributions).toBe(125);
  } finally {
    await page.request.delete(base);
  }
});

test('linked investment keeps cited hold schedule and revision when deal terms change', async ({ page }) => {
  const pdf = execFileSync('python', ['-c', [
    'from io import BytesIO',
    'from reportlab.pdfgen.canvas import Canvas',
    'import sys',
    'out=BytesIO()',
    'pdf=Canvas(out)',
    'pdf.drawString(60,765,"Class B hold returns on remaining invested equity, years after stabilization.")',
    'pdf.drawString(60,740,"Year-1 cash-on-cash 0.0%")',
    'pdf.drawString(60,715,"Year-2 cash-on-cash 12.5%")',
    'pdf.save()',
    'sys.stdout.buffer.write(out.getvalue())',
  ].join('\n')]);
  const created = await page.request.post('/api/deals', { data: { project_name: 'Synthetic Snapshot Position' } });
  expect(created.ok()).toBeTruthy();
  const dealId = (await created.json()).id;
  const base = `/api/deals/${dealId}`;
  let investmentId;
  try {
    const upload = await page.request.post(base + '/documents/upload', { multipart: { file: { name: 'snapshot-hold.pdf', mimeType: 'application/pdf', buffer: pdf } } });
    expect(upload.ok()).toBeTruthy();
    await expect.poll(async () => (await page.request.get(base + '/review/packet')).status()).toBe(200);
    let deal = await (await page.request.get(base)).json();
    const resolved = await page.request.post(base + '/analysis/resolve', { data: {
      expected_revision: deal.revision, reason: 'Synthetic hold snapshot check.',
      fields: [{ path: 'target_returns.primary_strategy', value: 'hold' }],
    } });
    expect(resolved.ok()).toBeTruthy();
    deal = await (await page.request.get(base)).json();
    const schedule = await page.request.put(base + '/analysis/return-schedule', { data: {
      expected_revision: deal.revision, source_doc_id: deal.documents[0].id, source_page: 1,
      investor_class: 'Class B', equity_basis: 'Remaining invested equity', period_basis: 'Years after stabilization',
      rows: [{ year: 1, cash_on_cash_pct: 0, source_excerpt: 'Year-1 cash-on-cash 0.0%' },
             { year: 2, cash_on_cash_pct: 12.5, source_excerpt: 'Year-2 cash-on-cash 12.5%' }],
    } });
    expect(schedule.ok()).toBeTruthy();
    deal = await (await page.request.get(base)).json();
    await page.goto('/portfolio');
    await page.getByRole('button', { name: 'Add investment', exact: true }).first().click();
    const drawer = page.getByRole('dialog', { name: 'Add investment', exact: true });
    await drawer.getByRole('combobox', { name: 'Deal', exact: true }).selectOption(String(dealId));
    await expect(drawer.getByText(/2-year hold schedule/)).toBeVisible();
    await drawer.getByLabel('Amount invested', { exact: true }).fill('1000');
    await drawer.getByLabel('Investment date', { exact: true }).fill('2024-01-01');
    await drawer.getByRole('button', { name: 'Add investment', exact: true }).click();
    await expect(drawer).toBeHidden();
    const positions = await (await page.request.get('/api/investments/')).json();
    const position = positions.find(row => row.deal_id === dealId);
    investmentId = position.id;
    expect(position.projected_irr).toBeNull();
    expect(position.projected_cash_on_cash).toBeNull();
    expect(position.forecast_snapshot.return_schedule.rows.map(row => row.cash_on_cash_pct)).toEqual([0, 12.5]);
    const card = page.getByTestId(`investment-${investmentId}`);
    await card.getByText('Forecast & review history', { exact: true }).click();
    await expect(card.getByText('Accepted forecast at entry', { exact: true })).toBeVisible();
    await expect(card.getByRole('table', { name: 'Projected cash-on-cash by year' })).toContainText('12.5%');
    await expect(card.getByText('snapshot-hold.pdf · page 1', { exact: true })).toBeVisible();
    const changed = await page.request.post(base + '/analysis/resolve', { data: {
      expected_revision: deal.revision, reason: 'Synthetic later underwriting change.',
      fields: [{ path: 'deal_structure.hold_period_years', value: 12 }],
    } });
    expect(changed.ok()).toBeTruthy();
    await page.reload();
    await card.getByText('Forecast & review history', { exact: true }).click();
    const saved = await (await page.request.get(`/api/investments/${investmentId}`)).json();
    expect(saved.forecast_snapshot).toEqual(position.forecast_snapshot);
    expect(saved.forecast_snapshot.analysis_version).toBe(deal.analysis.version);
    expect(saved.forecast_snapshot.return_schedule.evidence[0].content_hash).toMatch(/^[a-f0-9]{64}$/);
    await expect(card.getByRole('table', { name: 'Projected cash-on-cash by year' })).toContainText('12.5%');
  } finally {
    if (investmentId) await page.request.delete(`/api/investments/${investmentId}`);
    await page.request.delete(base);
  }
});
