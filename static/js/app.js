// ===== Kenyon Investment Dashboard — Frontend =====

const API = {
  deals: '/api/deals',
  developers: '/api/developers',
  chat: '/api/chat',
  investments: '/api/investments',
};

let allDeals = [];
let allDevelopers = [];
let allInvestments = [];
let currentDealId = null;
let currentInvestmentId = null;
let currentDeveloperId = null;
let selectedCompareIds = new Set();

// ===== Init =====
document.addEventListener('DOMContentLoaded', () => {
  setupNavigation();
  setupTabs();
  loadDashboard();
  loadDevelopers();
});

// ===== Navigation =====
function setupNavigation() {
  document.querySelectorAll('.nav-item[data-page]').forEach(item => {
    item.addEventListener('click', () => {
      const page = item.dataset.page;
      showPage(page);
    });
  });
}

function showPage(page) {
  document.querySelectorAll('.view-page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) pageEl.classList.add('active');

  const navEl = document.querySelector(`.nav-item[data-page="${page}"]`);
  if (navEl) navEl.classList.add('active');

  if (page === 'dashboard') loadDashboard();
  if (page === 'developers') loadDevelopers();
  if (page === 'compare') loadCompareList();
  if (page === 'portfolio') loadPortfolio();
}

// ===== Tabs =====
function setupTabs() {
  document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const tabName = tab.dataset.tab;
      document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById(`tab-${tabName}`).classList.add('active');
    });
  });
}

// ===== Toast =====
function toast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = `toast toast-${type}`;
  t.textContent = message;
  container.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

// ===== Modal =====
function openModal(id) {
  document.getElementById(id).classList.add('active');
}

function closeModal(id) {
  document.getElementById(id).classList.remove('active');
}

// ===== Formatting =====
function fmt$(val) {
  if (val == null) return '—';
  const num = Number(val);
  if (isNaN(num)) return String(val);
  if (num >= 1e9) return '$' + (num / 1e9).toFixed(1) + 'B';
  if (num >= 1e6) return '$' + (num / 1e6).toFixed(1) + 'M';
  if (num >= 1e3) return '$' + (num / 1e3).toFixed(0) + 'K';
  return '$' + num.toLocaleString();
}

function fmtPct(val) {
  if (val == null) return '—';
  return Number(val).toFixed(1) + '%';
}

function fmtNum(val) {
  if (val == null) return '—';
  return Number(val).toLocaleString();
}

function fmtX(val) {
  if (val == null) return '—';
  return Number(val).toFixed(2) + 'x';
}

function fmtVal(val) {
  if (val == null) return '—';
  return String(val);
}

function scoreClass(score) {
  if (score == null) return 'score-none';
  if (score >= 8) return 'score-high';
  if (score >= 6) return 'score-mid';
  return 'score-low';
}

function scoreColor(score) {
  if (score == null) return '#9ca3af';
  if (score >= 8) return '#16a34a';
  if (score >= 6) return '#d97706';
  return '#dc2626';
}

function statusClass(status) {
  return `badge badge-status status-${status || 'reviewing'}`;
}

// ===== API Helpers =====
async function api(url, methodOrOptions = {}, bodyData = null) {
  let options = {};
  if (typeof methodOrOptions === 'string') {
    options = { method: methodOrOptions };
    if (bodyData) options.body = JSON.stringify(bodyData);
  } else {
    options = methodOrOptions;
  }
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Request failed');
    }
    if (res.headers.get('content-type')?.includes('application/json')) {
      return await res.json();
    }
    return res;
  } catch (e) {
    toast(e.message, 'error');
    throw e;
  }
}

// ===== Dashboard =====
async function loadDashboard() {
  try {
    allDeals = await api(API.deals);
    allDevelopers = await api(API.developers);
    document.getElementById('deal-count').textContent = allDeals.length;
    renderStats();
    renderDeals(allDeals);
  } catch (e) {
    console.error(e);
  }
}

function renderStats() {
  const deals = allDeals;
  const scored = deals.filter(d => d.overall_score != null);
  const avgScore = scored.length ? (scored.reduce((a, d) => a + d.overall_score, 0) / scored.length).toFixed(1) : '—';
  const reviewing = deals.filter(d => d.status === 'reviewing').length;
  const interested = deals.filter(d => d.status === 'interested').length;
  const committed = deals.filter(d => d.status === 'committed').length;

  document.getElementById('dashboard-stats').innerHTML = `
    <div class="stat-card">
      <div class="stat-label">Total Deals</div>
      <div class="stat-value">${deals.length}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Avg Score</div>
      <div class="stat-value">${avgScore}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Reviewing</div>
      <div class="stat-value">${reviewing}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Interested</div>
      <div class="stat-value">${interested}</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">Committed</div>
      <div class="stat-value">${committed}</div>
    </div>
  `;
}

function renderDeals(deals) {
  const grid = document.getElementById('deals-grid');
  const empty = document.getElementById('deals-empty');

  if (!deals.length) {
    grid.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  grid.innerHTML = deals.map(d => {
    const score = d.overall_score;
    const tr = d.metrics?.target_returns || {};
    const hs = tr.hold_scenario || {};
    const ss = tr.sale_scenario || {};
    const strategy = tr.primary_strategy || '';
    const isHold = strategy === 'hold' || strategy === 'hold_with_sale_option';
    
    // Show most relevant metric: CoC for hold deals, IRR for sale deals
    const primaryReturn = isHold ? (hs.cash_on_cash_return || tr.target_cash_on_cash || d.target_irr) : (d.target_irr || ss.sale_irr);
    const primaryLabel = isHold ? 'Cash-on-Cash' : 'IRR';
    const em = isHold ? null : (d.target_equity_multiple || ss.sale_equity_multiple);
    const minInv = d.minimum_investment;
    const strategyTag = isHold ? '🏠 Hold' : strategy === 'sale' ? '💰 Sale' : '';

    return `
      <div class="deal-card" onclick="openDeal(${d.id})">
        <div class="deal-card-top">
          <div>
            <div class="deal-card-title">${esc(d.project_name)}</div>
            <div class="deal-card-developer">${esc(d.developer_name || 'No developer')}</div>
            <div class="deal-card-location">${esc([d.city, d.state].filter(Boolean).join(', ') || d.location || '')}</div>
          </div>
          <div class="deal-card-score ${scoreClass(score)}">${score != null ? score.toFixed(1) : '—'}</div>
        </div>
        <div class="deal-card-metrics">
          <div class="deal-metric">
            <div class="deal-metric-value">${primaryReturn != null ? fmtPct(primaryReturn) : '—'}</div>
            <div class="deal-metric-label">${primaryLabel}</div>
          </div>
          <div class="deal-metric">
            <div class="deal-metric-value">${em != null ? fmtX(em) : (hs.priority_return ? fmtPct(hs.priority_return) : '—')}</div>
            <div class="deal-metric-label">${em != null ? 'Multiple' : (hs.priority_return ? 'Pref Return' : 'Multiple')}</div>
          </div>
          <div class="deal-metric">
            <div class="deal-metric-value">${minInv != null ? fmt$(minInv) : '—'}</div>
            <div class="deal-metric-label">Min Invest</div>
          </div>
        </div>
        <div class="deal-card-footer">
          <div class="deal-card-tags">
            <span class="badge badge-type">${esc(d.property_type || '')}</span>
            <span class="${statusClass(d.status)}">${esc(d.status || 'reviewing')}</span>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function filterDeals() {
  const search = document.getElementById('deal-search').value.toLowerCase();
  const type = document.getElementById('filter-type').value;
  const status = document.getElementById('filter-status').value;

  let filtered = allDeals.filter(d => {
    if (search && !d.project_name.toLowerCase().includes(search) && !(d.developer_name || '').toLowerCase().includes(search)) return false;
    if (type && d.property_type !== type) return false;
    if (status && d.status !== status) return false;
    return true;
  });

  sortDealsArray(filtered);
  renderDeals(filtered);
}

function sortDeals() { filterDeals(); }

function sortDealsArray(deals) {
  const sortBy = document.getElementById('sort-by').value;
  deals.sort((a, b) => {
    switch (sortBy) {
      case 'score': return (b.overall_score || 0) - (a.overall_score || 0);
      case 'irr': return (b.target_irr || 0) - (a.target_irr || 0);
      case 'name': return (a.project_name || '').localeCompare(b.project_name || '');
      default: return new Date(b.created_at || 0) - new Date(a.created_at || 0);
    }
  });
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

// ===== Create Deal =====
function openAddDealModal() {
  // Populate developer dropdown
  const sel = document.getElementById('new-deal-developer');
  sel.innerHTML = '<option value="">— Select —</option>' +
    allDevelopers.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('');
  // Show inline "add developer" if none exist or always show the quick-add
  document.getElementById('quick-add-dev-row').style.display = 'none';
  openModal('modal-add-deal');
}

function toggleQuickAddDev() {
  const row = document.getElementById('quick-add-dev-row');
  row.style.display = row.style.display === 'none' ? 'block' : 'none';
  if (row.style.display !== 'none') document.getElementById('quick-dev-name').focus();
}

async function quickAddDeveloper() {
  const name = document.getElementById('quick-dev-name').value.trim();
  if (!name) { toast('Enter a developer name', 'error'); return; }
  const dev = await api(API.developers, { method: 'POST', body: JSON.stringify({ name }) });
  allDevelopers.push(dev);
  const sel = document.getElementById('new-deal-developer');
  sel.innerHTML = '<option value="">— Select —</option>' +
    allDevelopers.map(d => `<option value="${d.id}">${esc(d.name)}</option>`).join('');
  sel.value = dev.id;
  document.getElementById('quick-add-dev-row').style.display = 'none';
  document.getElementById('quick-dev-name').value = '';
  toast(`Developer "${name}" added`, 'success');
}

async function createDeal() {
  const name = document.getElementById('new-deal-name').value.trim();
  if (!name) { toast('Project name required', 'error'); return; }

  const data = {
    project_name: name,
    developer_id: document.getElementById('new-deal-developer').value || null,
    property_type: document.getElementById('new-deal-type').value,
    location: document.getElementById('new-deal-location').value,
    city: document.getElementById('new-deal-city').value,
    state: document.getElementById('new-deal-state').value,
    notes: document.getElementById('new-deal-notes').value,
  };
  if (data.developer_id) data.developer_id = parseInt(data.developer_id);

  await api(API.deals, { method: 'POST', body: JSON.stringify(data) });
  closeModal('modal-add-deal');
  toast('Deal created', 'success');
  // Clear form
  document.getElementById('new-deal-name').value = '';
  document.getElementById('new-deal-location').value = '';
  document.getElementById('new-deal-city').value = '';
  document.getElementById('new-deal-state').value = '';
  document.getElementById('new-deal-notes').value = '';
  loadDashboard();
}

async function deleteDeal() {
  if (!currentDealId) return;
  if (!confirm('Delete this deal and all its documents?')) return;
  await api(`${API.deals}/${currentDealId}`, { method: 'DELETE' });
  toast('Deal deleted', 'success');
  showPage('dashboard');
}

// ===== Deal Detail =====
async function openDeal(id) {
  currentDealId = id;
  try {
    const deal = await api(`${API.deals}/${id}`);
    renderDealDetail(deal);
    showPage('deal-detail');
    // Reset to overview tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelector('.tab[data-tab="overview"]').classList.add('active');
    document.getElementById('tab-overview').classList.add('active');
    // Load chat
    loadChatHistory(id);
  } catch (e) { console.error(e); }
}

function renderDealDetail(deal) {
  const m = deal.metrics || {};
  const s = deal.scores || {};
  const ds = m.deal_structure || {};
  const tr = m.target_returns || {};
  const pd = m.project_details || {};
  const fp = m.financial_projections || {};
  const ml = m.market_location || {};
  const ra = m.risk_assessment || {};
  const uc = m.underwriting_checks || {};
  const se = m.sponsor_evaluation || {};
  const vf = m.validation_flags || [];

  document.getElementById('detail-title').textContent = deal.project_name;
  document.getElementById('detail-project-name').textContent = deal.project_name;
  document.getElementById('detail-subtitle').textContent =
    [deal.developer_name, deal.city, deal.state].filter(Boolean).join(' · ') || 'No details';
  document.getElementById('detail-status').value = deal.status || 'reviewing';

  // Score badge
  const overall = s.overall;
  document.getElementById('detail-score-badge').innerHTML = overall != null
    ? `<div class="deal-card-score ${scoreClass(overall)}" style="width:50px;height:50px;font-size:20px;">${overall.toFixed(1)}</div>`
    : '';

  // Overview tab
  renderOverviewTab(deal, s, m);
  renderFinancialsTab(ds, tr, fp, pd, uc);
  renderMarketTab(ml);
  renderCashFlowTab(m);
  renderRiskTab(ra, s);
  renderWaterfallTab(m);
  renderDueDiligenceTab(vf, uc);
  renderSponsorTab(se, ds);
  renderDocumentsTab(deal);
}

function renderOverviewTab(deal, scores, metrics) {
  const s = scores;
  const cats = ['returns', 'market', 'structure', 'risk', 'financials', 'underwriting', 'sponsor'];

  let scoreHTML = '';
  if (s.overall != null) {
    scoreHTML = `
      <div class="score-overview">
        <div>
          <div class="score-big ${scoreClass(s.overall)}">
            <div class="score-big-value">${s.overall.toFixed(1)}</div>
            <div class="score-big-label">Overall</div>
          </div>
        </div>
        <div class="score-categories">
          ${cats.map(c => {
            const cat = s[c] || {};
            const sc = cat.score || 0;
            return `
              <div class="score-cat-row">
                <div class="score-cat-label">${c}</div>
                <div class="score-cat-bar"><div class="score-cat-fill" style="width:${sc * 10}%;background:${scoreColor(sc)};"></div></div>
                <div class="score-cat-value" style="color:${scoreColor(sc)}">${sc}</div>
                <div class="score-cat-weight">${cat.weight || ''}%</div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
      <div class="card mb-3">
        <div class="card-header"><h3>Score Notes</h3></div>
        <div class="card-body">
          ${cats.map(c => {
            const cat = s[c] || {};
            return cat.notes ? `<div style="margin-bottom:6px;"><strong style="text-transform:capitalize;font-size:11px;color:var(--text-muted);">${c}:</strong> <span style="font-size:12px;">${esc(cat.notes)}</span></div>` : '';
          }).join('')}
        </div>
      </div>
    `;
  } else {
    scoreHTML = `<div class="card mb-3"><div class="card-body"><p class="text-muted text-sm">No scores yet. Upload documents, extract metrics, then score the deal.</p></div></div>`;
  }

  // Key metrics summary
  const tr = metrics.target_returns || {};
  const ds = metrics.deal_structure || {};
  const fp = metrics.financial_projections || {};

  // Build scenario-aware return cards
  const hs = tr.hold_scenario || {};
  const ss = tr.sale_scenario || {};
  const strategy = tr.primary_strategy || '';
  const hasHold = hs.cash_on_cash_return || hs.priority_return || hs.distribution_yield;
  const hasSale = ss.sale_irr || ss.sale_equity_multiple;

  let scenarioHTML = '';
  if (hasHold || hasSale) {
    // Strategy badge
    const stratBadge = strategy === 'hold' ? '🏠 Hold for Cash Flow'
      : strategy === 'sale' ? '💰 Sale/Exit Strategy'
      : strategy === 'hold_with_sale_option' ? '🏠 Hold + 💰 Sale Option'
      : 'Returns';

    let holdCards = '';
    if (hasHold) {
      holdCards = `
        <div style="margin-bottom:12px;">
          <div style="font-weight:600;font-size:13px;color:var(--green);margin-bottom:8px;">🏠 HOLD SCENARIO — Primary Strategy</div>
          ${hs.description ? `<div style="font-size:11px;color:var(--muted);margin-bottom:8px;padding:6px 10px;background:var(--bg);border-radius:6px;">${esc(hs.description)}</div>` : ''}
          <div class="stats-grid">
            ${hs.priority_return ? `<div class="stat-card"><div class="stat-label">Priority Return</div><div class="stat-value">${fmtPct(hs.priority_return)}</div></div>` : ''}
            ${hs.cash_on_cash_return ? `<div class="stat-card"><div class="stat-label">Projected Cash-on-Cash</div><div class="stat-value" style="color:var(--green)">${fmtPct(hs.cash_on_cash_return)}</div></div>` : ''}
            ${hs.annual_cash_flow_per_share ? `<div class="stat-card"><div class="stat-label">Annual CF / Share</div><div class="stat-value">${fmt$(hs.annual_cash_flow_per_share)}</div></div>` : ''}
            ${hs.distribution_yield ? `<div class="stat-card"><div class="stat-label">Distribution Yield</div><div class="stat-value">${fmtPct(hs.distribution_yield)}</div></div>` : ''}
          </div>
        </div>`;
    }

    let saleCards = '';
    if (hasSale) {
      const hypoTag = ss.is_hypothetical ? ' <span style="background:#f59e0b22;color:#f59e0b;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:600;">⚠️ HYPOTHETICAL</span>' : '';
      saleCards = `
        <div style="margin-bottom:12px;">
          <div style="font-weight:600;font-size:13px;color:var(--accent);margin-bottom:8px;">💰 SALE SCENARIO${hypoTag}</div>
          ${ss.description ? `<div style="font-size:11px;color:var(--muted);margin-bottom:8px;padding:6px 10px;background:var(--bg);border-radius:6px;">${esc(ss.description)}</div>` : ''}
          <div class="stats-grid">
            ${ss.sale_irr ? `<div class="stat-card"><div class="stat-label">IRR (if sold)</div><div class="stat-value">${fmtPct(ss.sale_irr)}</div></div>` : ''}
            ${ss.sale_equity_multiple ? `<div class="stat-card"><div class="stat-label">Equity Multiple (if sold)</div><div class="stat-value">${fmtX(ss.sale_equity_multiple)}</div></div>` : ''}
            ${ss.projected_profit_on_sale ? `<div class="stat-card"><div class="stat-label">Profit / Share (if sold)</div><div class="stat-value">${fmt$(ss.projected_profit_on_sale)}</div></div>` : ''}
            ${ss.assumed_sale_year ? `<div class="stat-card"><div class="stat-label">Assumed Sale</div><div class="stat-value">${ss.assumed_sale_year}${ss.assumed_hold_years ? ` (${ss.assumed_hold_years}yr)` : ''}</div></div>` : ''}
          </div>
        </div>`;
    }

    scenarioHTML = `
      <div class="card mb-3">
        <div class="card-header"><h3>${stratBadge}</h3></div>
        <div class="card-body">
          ${holdCards}
          ${saleCards}
        </div>
      </div>`;
  }

  // Fallback key metrics if no scenario data
  const keyMetrics = scenarioHTML || `
    <div class="stats-grid mb-3">
      <div class="stat-card"><div class="stat-label">Target IRR</div><div class="stat-value">${tr.target_irr != null ? fmtPct(tr.target_irr) : '—'}</div></div>
      <div class="stat-card"><div class="stat-label">Equity Multiple</div><div class="stat-value">${tr.target_equity_multiple != null ? fmtX(tr.target_equity_multiple) : '—'}</div></div>
      <div class="stat-card"><div class="stat-label">Cash-on-Cash</div><div class="stat-value">${tr.target_cash_on_cash != null ? fmtPct(tr.target_cash_on_cash) : '—'}</div></div>
    </div>`;

  // Deal info cards (always shown)
  const dealInfoCards = `
    <div class="stats-grid mb-3">
      <div class="stat-card"><div class="stat-label">Min Investment</div><div class="stat-value">${ds.minimum_investment != null ? fmt$(ds.minimum_investment) : '—'}</div></div>
      <div class="stat-card"><div class="stat-label">Total Project Cost</div><div class="stat-value">${ds.total_project_cost != null ? fmt$(ds.total_project_cost) : '—'}</div></div>
      <div class="stat-card"><div class="stat-label">Pref Return</div><div class="stat-value">${ds.preferred_return != null ? fmtPct(ds.preferred_return) : '—'}</div></div>
    </div>
  `;

  // Notes
  const notes = `
    <div class="card">
      <div class="card-header"><h3>Notes</h3></div>
      <div class="card-body">
        <textarea class="form-input" id="deal-notes" rows="3" onblur="saveDealNotes()">${esc(deal.notes || '')}</textarea>
      </div>
    </div>
  `;

  document.getElementById('tab-overview').innerHTML = scoreHTML + keyMetrics + dealInfoCards + notes;
}

function renderFinancialsTab(ds, tr, fp, pd, uc) {
  function row(label, val) {
    return `<div class="metric-row"><span class="metric-label">${label}</span><span class="metric-value">${val}</span></div>`;
  }
  function longRow(label, val) {
    return `<div class="metric-row metric-row-long"><span class="metric-label">${label}</span><span class="metric-value metric-value-long">${val}</span></div>`;
  }
  uc = uc || {};

  document.getElementById('tab-financials').innerHTML = `
    <div class="metrics-section">
      <div class="metrics-section-title">Deal Structure</div>
      <div class="metrics-grid">
        ${row('Investment Class', fmtVal(ds.investment_class))}
        ${row('Minimum Investment', fmt$(ds.minimum_investment))}
        ${row('Total Equity Required', fmt$(ds.total_equity_required))}
        ${row('Total Project Cost', fmt$(ds.total_project_cost))}
        ${row('Construction Loan', fmt$(ds.construction_loan_amount))}
        ${row('LTV', fmtPct(ds.ltv))}
        ${row('Loan Type', fmtVal(ds.loan_type))}
        ${ds.permanent_loan_amount ? `<div class="metric-row" style="opacity:0.5;font-size:12px;"><span class="metric-label">Perm Loan (future)</span><span class="metric-value">${fmt$(ds.permanent_loan_amount)}${ds.ltv_at_stabilization ? ' · ' + fmtPct(ds.ltv_at_stabilization) + ' LTV' : ''}</span></div>` : ''}
        ${row('Interest Rate', fmtPct(ds.interest_rate))}
        ${row('Hold Period', ds.hold_period_years != null ? ds.hold_period_years + ' years' : '—')}
        ${row('Investment Term', fmtVal(ds.investment_term_years))}
        ${row('Preferred Return', fmtPct(ds.preferred_return))}
        ${row('GP Co-Invest', fmtVal(ds.gp_coinvest))}
        ${row('GP Co-Invest %', ds.gp_equity_coinvest_pct != null ? fmtPct(ds.gp_equity_coinvest_pct) : '—')}
        ${row('Distribution Freq', fmtVal(ds.distribution_frequency))}
        ${row('Asset Mgmt Fee', fmtPct(ds.fees_asset_mgmt))}
        ${row('Acquisition Fee', fmtPct(ds.fees_acquisition))}
        ${row('Dev Fee', fmtVal(ds.fees_dev_fee))}
        ${row('Disposition Fee', fmtPct(ds.fees_disposition))}
        ${row('Construction Mgmt Fee', fmtPct(ds.fees_construction_mgmt))}
      </div>
      ${ds.capital_stack ? longRow('Capital Stack', fmtVal(ds.capital_stack)) : ''}
      ${ds.sources_and_uses ? longRow('Sources & Uses', fmtVal(ds.sources_and_uses)) : ''}
      ${ds.exit_strategies ? longRow('Exit Strategies', fmtVal(ds.exit_strategies)) : ''}
      ${ds.capital_call_provisions ? longRow('Capital Call Provisions', fmtVal(ds.capital_call_provisions)) : ''}
      ${ds.redemption_rights ? longRow('Redemption Rights', fmtVal(ds.redemption_rights)) : ''}
    </div>
    <div class="metrics-section">
      <div class="metrics-section-title">Strategy: ${(() => { const s = tr.primary_strategy; return s === 'hold' ? '🏠 Hold for Cash Flow' : s === 'sale' ? '💰 Sale/Exit' : s === 'hold_with_sale_option' ? '🏠 Hold + 💰 Sale Option' : 'Target Returns'; })()}</div>
      ${(() => {
        const hs = tr.hold_scenario || {};
        const ss = tr.sale_scenario || {};
        let html = '<div class="metrics-grid">';
        // Hold scenario
        if (hs.priority_return || hs.cash_on_cash_return || hs.distribution_yield) {
          html += '<div style="grid-column:1/-1;font-weight:600;font-size:12px;color:var(--green);border-bottom:1px solid var(--border);padding-bottom:4px;margin-bottom:4px;">🏠 Hold Returns (Primary)</div>';
          if (hs.description) html += '<div style="grid-column:1/-1;font-size:11px;color:var(--muted);margin-bottom:4px;">' + hs.description + '</div>';
          html += row('Priority Return', fmtPct(hs.priority_return));
          html += row('Projected Cash-on-Cash', fmtPct(hs.cash_on_cash_return));
          html += row('Annual CF / Share', fmt$(hs.annual_cash_flow_per_share));
          html += row('Distribution Yield', fmtPct(hs.distribution_yield));
        }
        // Sale scenario
        if (ss.sale_irr || ss.sale_equity_multiple) {
          const hypo = ss.is_hypothetical ? ' ⚠️ Hypothetical' : '';
          html += '<div style="grid-column:1/-1;font-weight:600;font-size:12px;color:var(--accent);border-bottom:1px solid var(--border);padding-bottom:4px;margin:8px 0 4px;">💰 Sale Returns' + hypo + '</div>';
          if (ss.description) html += '<div style="grid-column:1/-1;font-size:11px;color:var(--muted);margin-bottom:4px;">' + ss.description + '</div>';
          html += row('IRR (if sold)', fmtPct(ss.sale_irr));
          html += row('Equity Multiple (if sold)', ss.sale_equity_multiple != null ? fmtX(ss.sale_equity_multiple) : '—');
          html += row('Profit / Share (if sold)', fmt$(ss.projected_profit_on_sale));
          html += row('Assumed Sale Year', ss.assumed_sale_year || '—');
          html += row('Exit Cap Rate', fmtPct(ss.exit_cap_rate));
        }
        // General returns
        html += '<div style="grid-column:1/-1;font-weight:600;font-size:12px;border-bottom:1px solid var(--border);padding-bottom:4px;margin:8px 0 4px;">General</div>';
        html += row('Target IRR', fmtPct(tr.target_irr));
        html += row('Target Cash-on-Cash', fmtPct(tr.target_cash_on_cash));
        html += row('Distribution Yield', fmtPct(tr.distribution_yield));
        html += row('Avg Annual Return', fmtPct(tr.target_avg_annual_return));
        html += row('Projected Profit', fmt$(tr.projected_profit));
        html += row('Total Fee Drag', tr.total_fee_drag != null ? fmtPct(tr.total_fee_drag) : '—');
        html += row('Profit Split (above pref)', fmtVal(tr.profit_split_above_pref));
        html += row('Profit Split (Tier 2)', fmtVal(tr.profit_split_above_tier2));
        html += '</div>';
        return html;
      })()}
    </div>
    <div class="metrics-section">
      <div class="metrics-section-title">Project Details</div>
      <div class="metrics-grid">
        ${row('Unit Count', fmtNum(pd.unit_count))}
        ${row('Unit Mix', fmtVal(pd.unit_mix))}
        ${row('Total SqFt', fmtNum(pd.total_sqft))}
        ${row('Price/Unit', fmt$(pd.price_per_unit))}
        ${row('Price/SqFt', fmt$(pd.price_per_sqft))}
        ${row('Lot Size', fmtVal(pd.lot_size))}
        ${row('Construction Type', fmtVal(pd.construction_type))}
        ${row('Construction Start', fmtVal(pd.construction_start))}
        ${row('Duration (months)', fmtVal(pd.construction_duration_months))}
        ${row('Stabilization', fmtVal(pd.stabilization_date))}
        ${row('Entitlement Status', fmtVal(pd.entitlement_status))}
        ${row('Zoning', fmtVal(pd.zoning))}
        ${row('Current Occupancy', fmtPct(pd.current_occupancy))}
        ${row('Current Avg Rent', fmt$(pd.current_avg_rent))}
        ${row('Proforma Avg Rent', fmt$(pd.proforma_avg_rent))}
        ${row('Rent Premium', fmtVal(pd.rent_premium))}
        ${row('Renovation Timeline', pd.renovation_timeline_months != null ? pd.renovation_timeline_months + ' months' : '—')}
      </div>
      ${pd.renovation_scope ? longRow('Renovation Scope', fmtVal(pd.renovation_scope)) : ''}
      ${pd.comparable_properties ? longRow('Comparable Properties', fmtVal(pd.comparable_properties)) : ''}
    </div>
    <div class="metrics-section">
      <div class="metrics-section-title">Financial Projections</div>
      <div class="metrics-grid">
        ${row('Stabilized NOI', fmt$(fp.stabilized_noi))}
        ${row('Entry Cap Rate', fmtPct(fp.entry_cap_rate))}
        ${row('Exit Cap Rate', fmtPct(fp.exit_cap_rate))}
        ${row('Avg Rent/Unit', fmt$(fp.avg_rent_per_unit))}
        ${row('Avg Rent/SqFt', fmt$(fp.avg_rent_per_sqft))}
        ${row('Rent Growth', fmtPct(fp.rent_growth_assumption))}
        ${row('Occupancy', fmtPct(fp.occupancy_assumption))}
        ${row('OpEx Ratio', fmtPct(fp.operating_expense_ratio))}
        ${row('Construction Budget', fmt$(fp.construction_budget))}
        ${row('Land Cost', fmt$(fp.land_cost))}
        ${row('Soft Costs', fmt$(fp.soft_costs))}
        ${row('Hard Costs', fmt$(fp.hard_costs))}
        ${row('Contingency', fmtVal(fp.contingency))}
      </div>
    </div>
    <div class="metrics-section">
      <div class="metrics-section-title">Underwriting Metrics</div>
      <div class="metrics-grid">
        ${row('Break-Even Occupancy', fmtPct(uc.break_even_occupancy))}
        ${row('DSCR', uc.dscr != null ? uc.dscr + 'x' : '—')}
        ${row('Yield on Cost', fmtPct(uc.yield_on_cost))}
        ${row('Revenue/Unit', fmt$(uc.revenue_per_unit))}
        ${row('OpEx/Unit', fmt$(uc.operating_expense_per_unit))}
        ${row('Management Fee', fmtPct(uc.management_fee_pct))}
        ${row('Reserves/Unit', fmt$(uc.reserves_per_unit))}
        ${row('Replacement Cost/Unit', fmt$(uc.replacement_cost_per_unit))}
        ${row('Expense Growth', fmtPct(uc.expense_growth_assumption))}
      </div>
      ${uc.tax_benefits ? longRow('Tax Benefits', fmtVal(uc.tax_benefits)) : ''}
      ${uc.interest_rate_sensitivity ? longRow('Interest Rate Sensitivity', fmtVal(uc.interest_rate_sensitivity)) : ''}
      ${uc.exit_cap_sensitivity ? longRow('Exit Cap Sensitivity', fmtVal(uc.exit_cap_sensitivity)) : ''}
      ${uc.rent_growth_sensitivity ? longRow('Rent Growth Sensitivity', fmtVal(uc.rent_growth_sensitivity)) : ''}
      ${uc.rent_growth_vs_market ? longRow('Rent Growth vs Market', fmtVal(uc.rent_growth_vs_market)) : ''}
    </div>
  `;
}

function renderMarketTab(ml) {
  function row(label, val) {
    return `<div class="metric-row"><span class="metric-label">${label}</span><span class="metric-value">${val}</span></div>`;
  }

  // Get market research data if available
  const deal = allDeals.find(d => d.id === currentDealId);
  const mr = (deal?.metrics?.market_research) || ((deal?.metrics || {}).market_research) || null;

  // Basic market location info
  let basicSection = `
    <div class="metrics-section">
      <div class="metrics-section-title">Market & Location (from Deal Docs)</div>
      <div class="metrics-grid">
        ${row('City', fmtVal(ml.city))}
        ${row('State', fmtVal(ml.state))}
        ${row('Submarket', fmtVal(ml.submarket))}
        ${row('Population', fmtNum(ml.market_population))}
        ${row('Job Growth', fmtPct(ml.market_job_growth))}
        ${row('Rent Growth', fmtPct(ml.market_rent_growth))}
        ${row('Vacancy Rate', fmtPct(ml.market_vacancy_rate))}
        ${row('Walk Score', fmtVal(ml.walk_score))}
        ${row('Nearby Employers', fmtVal(ml.nearby_employers))}
        ${row('Nearby Amenities', fmtVal(ml.nearby_amenities))}
      </div>
    </div>
  `;

  let researchSection = '';
  if (mr) {
    // Market data cards
    researchSection += `
      <div class="metrics-section">
        <div class="metrics-section-title" style="display:flex;justify-content:space-between;align-items:center;">
          Live Market Data — ${esc(mr.city || '')} ${esc(mr.state || '')}
          <button class="btn btn-secondary btn-sm" onclick="refreshMarketData()">🔄 Refresh Market Data</button>
        </div>
        ${mr.market_summary ? `<p style="font-size:12px;margin-bottom:12px;color:var(--text-secondary);line-height:1.6;">${esc(mr.market_summary)}</p>` : ''}
        <div class="market-grid">
          <div class="market-card"><div class="market-card-value">${mr.population ? fmtNum(mr.population) : '—'}</div><div class="market-card-label">Population</div></div>
          <div class="market-card"><div class="market-card-value">${mr.population_growth_pct != null ? fmtPct(mr.population_growth_pct) : '—'}</div><div class="market-card-label">Pop Growth</div></div>
          <div class="market-card"><div class="market-card-value">${mr.median_household_income ? fmt$(mr.median_household_income) : '—'}</div><div class="market-card-label">Median Income</div></div>
          <div class="market-card"><div class="market-card-value">${mr.unemployment_rate != null ? fmtPct(mr.unemployment_rate) : '—'}</div><div class="market-card-label">Unemployment</div></div>
          <div class="market-card"><div class="market-card-value">${mr.job_growth_pct != null ? fmtPct(mr.job_growth_pct) : '—'}</div><div class="market-card-label">Job Growth</div></div>
          <div class="market-card"><div class="market-card-value">${mr.avg_market_rent_1br ? fmt$(mr.avg_market_rent_1br) : '—'}</div><div class="market-card-label">Avg Rent (1BR)</div></div>
          <div class="market-card"><div class="market-card-value">${mr.avg_market_rent_2br ? fmt$(mr.avg_market_rent_2br) : '—'}</div><div class="market-card-label">Avg Rent (2BR)</div></div>
          <div class="market-card"><div class="market-card-value">${mr.rent_growth_yoy != null ? fmtPct(mr.rent_growth_yoy) : '—'}</div><div class="market-card-label">Rent Growth YoY</div></div>
          <div class="market-card"><div class="market-card-value">${mr.vacancy_rate != null ? fmtPct(mr.vacancy_rate) : '—'}</div><div class="market-card-label">Vacancy Rate</div></div>
          <div class="market-card"><div class="market-card-value">${mr.new_supply_units != null ? fmtNum(mr.new_supply_units) : '—'}</div><div class="market-card-label">New Supply (units)</div></div>
          <div class="market-card"><div class="market-card-value">${mr.median_home_price ? fmt$(mr.median_home_price) : '—'}</div><div class="market-card-label">Med Home Price</div></div>
          <div class="market-card"><div class="market-card-value">${mr.crime_rate_trend || '—'}</div><div class="market-card-label">Crime Trend</div></div>
        </div>
      </div>
    `;

    // Sponsor Assumptions vs Market Reality
    const fp = deal?.metrics?.financial_projections || {};
    let comparisons = [];
    if (fp.rent_growth_assumption != null && mr.rent_growth_yoy != null) {
      const sponsorRG = Number(fp.rent_growth_assumption);
      const marketRG = Number(mr.rent_growth_yoy);
      const verdict = sponsorRG <= marketRG ? '✅ Conservative' : '⚠️ Aggressive';
      const verdictColor = sponsorRG <= marketRG ? 'var(--green)' : 'var(--red)';
      comparisons.push(`<div class="market-compare-row">
        <span class="market-compare-label">Rent Growth</span>
        <span class="market-compare-sponsor">Sponsor: ${fmtPct(sponsorRG)}</span>
        <span style="color:var(--text-muted);">→</span>
        <span class="market-compare-market">Market: ${fmtPct(marketRG)}</span>
        <span class="market-compare-verdict" style="color:${verdictColor};">${verdict}</span>
      </div>`);
    }
    if (fp.occupancy_assumption != null && mr.vacancy_rate != null) {
      const sponsorOcc = Number(fp.occupancy_assumption);
      const marketOcc = 100 - Number(mr.vacancy_rate);
      const verdict = sponsorOcc <= marketOcc ? '✅ Aligned' : '⚠️ Above Market';
      const verdictColor = sponsorOcc <= marketOcc ? 'var(--green)' : 'var(--red)';
      comparisons.push(`<div class="market-compare-row">
        <span class="market-compare-label">Occupancy</span>
        <span class="market-compare-sponsor">Sponsor: ${fmtPct(sponsorOcc)}</span>
        <span style="color:var(--text-muted);">→</span>
        <span class="market-compare-market">Market: ${fmtPct(marketOcc)} (vac ${fmtPct(mr.vacancy_rate)})</span>
        <span class="market-compare-verdict" style="color:${verdictColor};">${verdict}</span>
      </div>`);
    }

    if (comparisons.length) {
      researchSection += `
        <div class="metrics-section">
          <div class="metrics-section-title">Sponsor Assumptions vs Market Reality</div>
          <div class="market-comparison">${comparisons.join('')}</div>
        </div>
      `;
    }

    // Major employers
    if (mr.major_employers && mr.major_employers.length) {
      researchSection += `
        <div class="metrics-section">
          <div class="metrics-section-title">Major Employers</div>
          <div class="market-pills">${mr.major_employers.map(e => `<span class="market-pill" style="background:var(--blue-bg);color:var(--accent);border:1px solid var(--accent);">${esc(e)}</span>`).join('')}</div>
        </div>
      `;
    }

    // Risks & Strengths
    let riskStrength = '';
    if (mr.top_3_strengths && mr.top_3_strengths.length) {
      riskStrength += `<div class="market-pills">${mr.top_3_strengths.map(s => `<span class="market-pill market-pill-strength">💪 ${esc(s)}</span>`).join('')}</div>`;
    }
    if (mr.top_3_risks && mr.top_3_risks.length) {
      riskStrength += `<div class="market-pills" style="margin-top:6px;">${mr.top_3_risks.map(r => `<span class="market-pill market-pill-risk">⚠️ ${esc(r)}</span>`).join('')}</div>`;
    }
    if (riskStrength) {
      researchSection += `<div class="metrics-section"><div class="metrics-section-title">Market Strengths & Risks</div>${riskStrength}</div>`;
    }

    // Sources
    if (mr.data_sources && mr.data_sources.length) {
      researchSection += `<div class="market-sources"><strong>Sources:</strong> ${mr.data_sources.map(s => `<a href="${esc(s)}" target="_blank">${esc(new URL(s).hostname)}</a>`).join(' · ')} · Researched: ${mr.research_date || '—'}</div>`;
    }
  } else {
    researchSection = `
      <div class="card mt-3">
        <div class="card-body" style="text-align:center;padding:24px;">
          <p style="font-size:14px;margin-bottom:12px;">Pull live market data for this deal's location.</p>
          <button class="btn btn-primary" onclick="refreshMarketData()">🔍 Fetch Market Data</button>
          <p class="text-muted" style="margin-top:8px;font-size:11px;">Uses Brave Search + AI to find real market stats for the deal's city/state.</p>
        </div>
      </div>
    `;
  }

  document.getElementById('tab-market').innerHTML = researchSection + basicSection;
}

async function refreshMarketData() {
  if (!currentDealId) return;
  toast('Fetching market data... (this takes ~15s)', 'info');
  try {
    const data = await api(`${API.deals}/${currentDealId}/market-research`, { method: 'POST' });
    toast('Market data updated!', 'success');
    // Refresh deal data and re-render
    const deal = await api(`${API.deals}/${currentDealId}`);
    // Update allDeals cache
    const idx = allDeals.findIndex(d => d.id === currentDealId);
    if (idx >= 0) allDeals[idx] = deal;
    renderDealDetail(deal);
    // Switch back to market tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    document.querySelector('.tab[data-tab="market"]').classList.add('active');
    document.getElementById('tab-market').classList.add('active');
  } catch (e) {
    console.error(e);
  }
}

// ===== Cash Flow Tab =====
function renderCashFlowTab(metrics) {
  const el = document.getElementById('tab-cashflow');
  if (!metrics || !Object.keys(metrics).length) {
    el.innerHTML = '<div class="card"><div class="card-body"><p class="text-muted text-sm">Extract metrics first to see cash flow projections.</p></div></div>';
    return;
  }

  el.innerHTML = `
    <div class="investment-input-row">
      <label>Your investment amount:</label>
      <input type="number" class="form-input" id="cf-investment-input" placeholder="250000" step="1000">
      <button class="btn btn-primary btn-sm" onclick="loadCashFlow()">Calculate</button>
    </div>
    <div id="cf-results"><p class="text-muted text-sm" style="padding:12px;">Click Calculate to generate projections, or enter an investment amount for personalized returns.</p></div>
  `;

  // Auto-load with no investment
  loadCashFlow();
}

async function loadCashFlow() {
  if (!currentDealId) return;
  const investInput = document.getElementById('cf-investment-input');
  const investment = investInput?.value ? parseFloat(investInput.value) : null;
  const resultsDiv = document.getElementById('cf-results');

  try {
    let url = `${API.deals}/${currentDealId}/cashflow`;
    if (investment) url += `?investment=${investment}`;
    const data = await api(url);
    renderCashFlowResults(data, investment);
  } catch (e) {
    resultsDiv.innerHTML = `<div style="color:var(--red);padding:12px;">Error: ${esc(e.message)}</div>`;
  }
}

function renderCashFlowResults(data, investment) {
  const resultsDiv = document.getElementById('cf-results');
  const pl = data.project_level || [];
  const lp = data.lp_level || [];
  const summary = data.summary || {};
  const assumptions = data.assumptions || {};

  let html = '';

  // Assumptions summary
  html += `<div class="metrics-section"><div class="metrics-section-title">Assumptions Used</div>
    <div style="display:flex;flex-wrap:wrap;gap:12px;font-size:11px;color:var(--text-muted);">
      <span><strong>${assumptions.unit_count}</strong> units</span>
      <span><strong>${fmt$(assumptions.avg_rent)}</strong>/unit/mo</span>
      <span><strong>${assumptions.occupancy}%</strong> occupancy</span>
      <span><strong>${assumptions.expense_ratio}%</strong> expense ratio</span>
      <span><strong>${assumptions.rent_growth}%</strong> rent growth</span>
      <span><strong>${assumptions.hold_period}</strong> yr hold</span>
    </div>
  </div>`;

  // Project-level table
  html += `<div class="metrics-section"><div class="metrics-section-title">Project-Level Cash Flows</div>
    <div style="overflow-x:auto;">
    <table class="cf-table">
      <thead><tr><th>Year</th><th>Revenue</th><th>Expenses</th><th>NOI</th><th>Debt Service</th><th>Cash Flow</th></tr></thead>
      <tbody>`;

  pl.forEach(y => {
    html += `<tr>
      <td>${y.year}</td>
      <td>${fmt$(y.gross_revenue)}</td>
      <td>${fmt$(y.expenses)}</td>
      <td>${fmt$(y.noi)}</td>
      <td>${fmt$(y.debt_service)}</td>
      <td style="color:${y.cash_flow >= 0 ? 'var(--green)' : 'var(--red)'};">${fmt$(y.cash_flow)}</td>
    </tr>`;
  });
  html += '</tbody></table></div></div>';

  // LP Timeline visualization
  if (lp.length > 0 && investment) {
    const maxAbs = Math.max(...lp.map(e => Math.abs(e.amount)));

    html += `<div class="metrics-section"><div class="metrics-section-title">Your Investment Timeline</div>
      <div class="cf-timeline">`;

    lp.forEach((entry, i) => {
      const pct = maxAbs > 0 ? Math.abs(entry.amount) / maxAbs * 100 : 0;
      const barClass = entry.type === 'investment' ? 'cf-bar-negative' :
                       entry.type === 'exit' ? 'cf-bar-exit' : 'cf-bar-positive';
      const label = entry.type === 'investment' ? 'Invested' :
                    entry.type === 'exit' ? 'Exit + Dist' : 'Distribution';

      html += `<div class="cf-timeline-row">
        <span class="cf-timeline-year">Yr ${entry.year}</span>
        <div class="cf-timeline-bar-container">
          <div class="cf-timeline-bar ${barClass}" style="width:${Math.max(pct, 8)}%;">${label}</div>
        </div>
        <span class="cf-timeline-amount" style="color:${entry.amount >= 0 ? 'var(--green)' : 'var(--red)'};">${fmt$(entry.amount)}</span>
      </div>`;

      // Payback line
      if (summary.payback_year && entry.year === summary.payback_year && entry.cumulative >= 0) {
        html += `<div class="cf-payback-line"><span class="cf-payback-label">💰 Payback Year ${summary.payback_year}</span></div>`;
      }
    });
    html += '</div></div>';

    // Summary cards
    html += `<div class="metrics-section"><div class="metrics-section-title">Investment Summary</div>
      <div class="cf-summary-grid">
        <div class="market-card"><div class="market-card-value">${fmt$(summary.total_distributions)}</div><div class="market-card-label">Total Distributions</div></div>
        <div class="market-card"><div class="market-card-value">${fmt$(summary.exit_proceeds)}</div><div class="market-card-label">Exit Proceeds</div></div>
        <div class="market-card"><div class="market-card-value" style="color:${summary.net_profit >= 0 ? 'var(--green)' : 'var(--red)'};">${fmt$(summary.net_profit)}</div><div class="market-card-label">Net Profit</div></div>
        <div class="market-card"><div class="market-card-value">${summary.equity_multiple}x</div><div class="market-card-label">Equity Multiple</div></div>
        <div class="market-card"><div class="market-card-value">${summary.irr_estimate}%</div><div class="market-card-label">Est. IRR</div></div>
        <div class="market-card"><div class="market-card-value">${summary.payback_year ? 'Year ' + summary.payback_year : '—'}</div><div class="market-card-label">Payback Year</div></div>
      </div>
    </div>`;
  } else {
    // Project-only summary
    html += `<div class="metrics-section"><div class="metrics-section-title">Project Summary</div>
      <div class="cf-summary-grid">
        <div class="market-card"><div class="market-card-value">${fmt$(summary.total_operating_cashflow)}</div><div class="market-card-label">Operating Cash Flow</div></div>
        <div class="market-card"><div class="market-card-value">${fmt$(summary.exit_value)}</div><div class="market-card-label">Exit Value</div></div>
        <div class="market-card"><div class="market-card-value">${fmt$(summary.exit_equity)}</div><div class="market-card-label">Exit Equity</div></div>
        <div class="market-card"><div class="market-card-value">${summary.equity_multiple}x</div><div class="market-card-label">Equity Multiple</div></div>
      </div>
    </div>`;
  }

  resultsDiv.innerHTML = html;
}

// ===== Waterfall Tab =====
function renderWaterfallTab(metrics) {
  const el = document.getElementById('tab-waterfall');
  if (!metrics || !Object.keys(metrics).length) {
    el.innerHTML = '<div class="card"><div class="card-body"><p class="text-muted text-sm">Extract metrics first to see waterfall distributions.</p></div></div>';
    return;
  }

  el.innerHTML = `
    <div class="investment-input-row">
      <label>Your investment:</label>
      <input type="number" class="form-input" id="wf-investment-input" placeholder="250000" step="1000">
      <button class="btn btn-primary btn-sm" onclick="loadWaterfall()">Calculate</button>
    </div>
    <div id="wf-results"><p class="text-muted text-sm" style="padding:12px;">Click Calculate to see the waterfall distribution breakdown.</p></div>
  `;

  loadWaterfall();
}

async function loadWaterfall() {
  if (!currentDealId) return;
  const investInput = document.getElementById('wf-investment-input');
  const investment = investInput?.value ? parseFloat(investInput.value) : null;

  try {
    let url = `${API.deals}/${currentDealId}/waterfall`;
    if (investment) url += `?investment=${investment}`;
    const data = await api(url);
    renderWaterfallResults(data, investment);
  } catch (e) {
    document.getElementById('wf-results').innerHTML = `<div style="color:var(--red);padding:12px;">Error: ${esc(e.message)}</div>`;
  }
}

function renderWaterfallResults(data, investment) {
  const resultsDiv = document.getElementById('wf-results');
  const tiers = data.tiers || [];
  const totals = data.totals || {};

  if (!tiers.length) {
    resultsDiv.innerHTML = '<p class="text-muted text-sm">No waterfall data available.</p>';
    return;
  }

  const maxAmount = Math.max(...tiers.map(t => t.total));
  let html = '';

  // Visual waterfall
  html += '<div class="metrics-section"><div class="metrics-section-title">Waterfall Distribution</div>';

  tiers.forEach(tier => {
    const totalPct = maxAmount > 0 ? (tier.total / maxAmount * 100) : 0;
    const lpPct = tier.total > 0 ? (tier.lp_amount / tier.total * totalPct) : 0;
    const gpPct = tier.total > 0 ? (tier.gp_amount / tier.total * totalPct) : 0;

    html += `<div class="wf-tier">
      <div class="wf-tier-label">${esc(tier.name)}</div>
      <div class="wf-tier-bars">
        <div class="wf-bar-lp" style="width:${Math.max(lpPct, 0)}%;" title="LP: ${fmt$(tier.lp_amount)} (${tier.lp_pct}%)">${tier.total > 0 ? fmt$(tier.lp_amount) : ''}</div>
        <div class="wf-bar-gp" style="width:${Math.max(gpPct, 0)}%;" title="GP: ${fmt$(tier.gp_amount)} (${tier.gp_pct}%)">${tier.gp_amount > 0 ? fmt$(tier.gp_amount) : ''}</div>
      </div>
      ${investment ? `<div class="wf-tier-your">${tier.your_amount != null ? fmt$(tier.your_amount) : '—'}</div>` : ''}
    </div>`;
  });

  // Totals row
  html += `<div class="wf-totals">
    <div class="wf-tier-label">TOTAL</div>
    <div class="wf-tier-bars">
      <div class="wf-bar-lp" style="width:${totals.lp_pct || 0}%;">${fmt$(totals.lp_total)} (${totals.lp_pct}%)</div>
      <div class="wf-bar-gp" style="width:${totals.gp_pct || 0}%;">${fmt$(totals.gp_total)} (${totals.gp_pct}%)</div>
    </div>
    ${investment ? `<div class="wf-tier-your">${fmt$(totals.your_total)}</div>` : ''}
  </div>`;

  // Legend
  html += `<div style="display:flex;gap:16px;margin-top:8px;font-size:11px;">
    <span><span style="display:inline-block;width:12px;height:12px;background:var(--accent);border-radius:2px;vertical-align:middle;margin-right:4px;"></span> LP Share</span>
    <span><span style="display:inline-block;width:12px;height:12px;background:#f59e0b;border-radius:2px;vertical-align:middle;margin-right:4px;"></span> GP / Promote</span>
    ${investment ? `<span><span style="display:inline-block;width:12px;height:12px;background:var(--green);border-radius:2px;vertical-align:middle;margin-right:4px;"></span> Your Share</span>` : ''}
  </div>`;
  html += '</div>';

  // Fee Impact Summary (only if investment provided)
  if (investment && totals.your_irr_estimate != null) {
    html += `<div class="metrics-section"><div class="metrics-section-title">Fee Impact Summary</div>
      <div class="wf-fee-impact">
        <div class="wf-fee-card">
          <div class="wf-fee-value" style="color:var(--accent);">${totals.project_irr_estimate || 0}%</div>
          <div class="wf-fee-label">Project-Level IRR</div>
        </div>
        <div class="wf-fee-card">
          <div class="wf-fee-value" style="color:var(--green);">${totals.your_irr_estimate || 0}%</div>
          <div class="wf-fee-label">Your Net IRR</div>
        </div>
        <div class="wf-fee-card">
          <div class="wf-fee-value" style="color:var(--red);">${totals.fee_drag_pct || 0}%</div>
          <div class="wf-fee-label">Fee Drag</div>
        </div>
        <div class="wf-fee-card">
          <div class="wf-fee-value">${totals.your_multiple || 0}x</div>
          <div class="wf-fee-label">Your Multiple</div>
        </div>
        <div class="wf-fee-card">
          <div class="wf-fee-value" style="color:${totals.your_profit >= 0 ? 'var(--green)' : 'var(--red)'};">${fmt$(totals.your_profit)}</div>
          <div class="wf-fee-label">Your Net Profit</div>
        </div>
      </div>
      <div style="margin-top:12px;">
        <div style="font-size:11px;font-weight:600;margin-bottom:6px;color:var(--text-muted);">LP vs GP Share of Total Returns</div>
        <div class="wf-lp-gp-bar">
          <div style="width:${totals.lp_pct}%;background:var(--accent);display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:700;">LP ${totals.lp_pct}%</div>
          <div style="width:${totals.gp_pct}%;background:#f59e0b;display:flex;align-items:center;justify-content:center;color:#fff;font-size:10px;font-weight:700;">${totals.gp_pct > 5 ? 'GP ' + totals.gp_pct + '%' : ''}</div>
        </div>
      </div>
    </div>`;
  }

  resultsDiv.innerHTML = html;
}

function renderRiskTab(ra, scores) {
  function row(label, val) {
    return `<div class="metric-row"><span class="metric-label">${label}</span><span class="metric-value" style="color:${scoreColor(val)}">${val != null ? val + '/10' : '—'}</span></div>`;
  }

  const riskNotes = ra.risk_notes || (scores.risk || {}).notes || '';

  document.getElementById('tab-risk').innerHTML = `
    <div class="metrics-section">
      <div class="metrics-section-title">Risk Scores (10 = Lowest Risk)</div>
      <div class="metrics-grid">
        ${row('Market Risk', ra.market_risk_score)}
        ${row('Execution Risk', ra.execution_risk_score)}
        ${row('Financial Risk', ra.financial_risk_score)}
        ${row('Entitlement Risk', ra.entitlement_risk_score)}
        ${row('Developer Risk', ra.developer_risk_score)}
        ${row('Overall Risk', ra.overall_risk_score)}
      </div>
    </div>
    <div class="card mt-3">
      <div class="card-header"><h3>Risk Notes</h3></div>
      <div class="card-body"><p style="font-size:12px;white-space:pre-wrap;">${esc(riskNotes || 'No risk notes yet')}</p></div>
    </div>
  `;
}

function renderDueDiligenceTab(flags, uc) {
  flags = flags || [];
  uc = uc || {};

  const redFlags = flags.filter(f => f.severity === 'red');
  const yellowFlags = flags.filter(f => f.severity === 'yellow');
  const greenFlags = flags.filter(f => f.severity === 'green');

  // Group by category
  const categories = ['Returns', 'Structure', 'Alignment', 'Fees', 'Leverage', 'Underwriting', 'Sponsor'];
  const grouped = {};
  categories.forEach(c => grouped[c] = []);
  flags.forEach(f => {
    if (!grouped[f.category]) grouped[f.category] = [];
    grouped[f.category].push(f);
  });

  const severityIcon = (s) => {
    if (s === 'red') return '<span class="flag-icon flag-red">⛔</span>';
    if (s === 'yellow') return '<span class="flag-icon flag-yellow">⚠️</span>';
    return '<span class="flag-icon flag-green">✅</span>';
  };

  let flagsHTML = '';
  if (flags.length === 0) {
    flagsHTML = '<div class="card mb-3"><div class="card-body"><p class="text-muted text-sm">No validation flags yet. Extract metrics first, then validation checks will run automatically.</p></div></div>';
  } else {
    // Summary bar
    flagsHTML = `
      <div class="dd-summary mb-3">
        <div class="dd-summary-item dd-red">
          <span class="dd-count">${redFlags.length}</span>
          <span class="dd-label">Red Flags</span>
        </div>
        <div class="dd-summary-item dd-yellow">
          <span class="dd-count">${yellowFlags.length}</span>
          <span class="dd-label">Warnings</span>
        </div>
        <div class="dd-summary-item dd-green">
          <span class="dd-count">${greenFlags.length}</span>
          <span class="dd-label">Positive</span>
        </div>
      </div>
    `;

    // Flags by category
    categories.forEach(cat => {
      const catFlags = grouped[cat];
      if (!catFlags || catFlags.length === 0) return;
      flagsHTML += `
        <div class="dd-category mb-3">
          <div class="dd-category-title">${cat}</div>
          <div class="dd-flags">
            ${catFlags.map(f => `
              <div class="dd-flag dd-flag-${f.severity}">
                ${severityIcon(f.severity)}
                <span class="dd-flag-message">${esc(f.message)}</span>
              </div>
            `).join('')}
          </div>
        </div>
      `;
    });
  }

  // Action buttons
  flagsHTML += `
    <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
      <button class="btn btn-secondary btn-sm" onclick="runValidation()">🔄 Re-run Validation</button>
      <button class="btn btn-primary btn-sm" onclick="runVerification()" id="btn-verify">🔍 Verify Against Source</button>
      <button class="btn btn-secondary btn-sm" onclick="runMathCheck()" id="btn-math">🧮 Math Check</button>
    </div>
    <div id="math-check-results" style="margin-top:12px;"></div>
    <div id="verification-results" style="margin-top:16px;"></div>
  `;

  document.getElementById('tab-diligence').innerHTML = flagsHTML;
}

function renderSponsorTab(se, ds) {
  se = se || {};
  ds = ds || {};

  function row(label, val) {
    return `<div class="metric-row"><span class="metric-label">${label}</span><span class="metric-value">${val}</span></div>`;
  }
  function longRow(label, val) {
    return `<div class="metric-row metric-row-long"><span class="metric-label">${label}</span><span class="metric-value metric-value-long">${val}</span></div>`;
  }

  const alignmentScore = se.alignment_score;
  let alignmentHTML = '';
  if (alignmentScore != null) {
    const aColor = alignmentScore >= 8 ? 'var(--green)' : alignmentScore >= 5 ? 'var(--yellow)' : 'var(--red)';
    alignmentHTML = `
      <div class="sponsor-alignment mb-3">
        <div class="alignment-score" style="color:${aColor};border-color:${aColor};">
          <div class="alignment-value">${alignmentScore}</div>
          <div class="alignment-label">Alignment<br>Score</div>
        </div>
      </div>
    `;
  }

  document.getElementById('tab-sponsor').innerHTML = `
    ${alignmentHTML}
    <div class="metrics-section">
      <div class="metrics-section-title">Sponsor Overview</div>
      <div class="metrics-grid">
        ${row('Sponsor Name', fmtVal(se.sponsor_name))}
        ${row('Full-Cycle Deals', se.sponsor_full_cycle_deals != null ? se.sponsor_full_cycle_deals : '—')}
        ${row('Property Management', fmtVal(se.sponsor_property_mgmt))}
        ${row('Reporting', fmtVal(se.sponsor_communication))}
        ${row('GP Skin in the Game', fmtVal(se.sponsor_skin_in_game || ds.gp_coinvest))}
        ${row('GP Co-Invest %', ds.gp_equity_coinvest_pct != null ? fmtPct(ds.gp_equity_coinvest_pct) : '—')}
      </div>
      ${se.sponsor_track_record ? longRow('Track Record', fmtVal(se.sponsor_track_record)) : ''}
      ${se.sponsor_prior_returns ? longRow('Prior Returns (Realized)', fmtVal(se.sponsor_prior_returns)) : ''}
      ${se.sponsor_default_history ? longRow('Default History', fmtVal(se.sponsor_default_history)) : ''}
      ${se.sponsor_team_experience ? longRow('Team Experience', fmtVal(se.sponsor_team_experience)) : ''}
    </div>
  `;
}

async function runValidation() {
  if (!currentDealId) return;
  try {
    const data = await api(`${API.deals}/${currentDealId}/validate`);
    toast(`Validation complete: ${data.summary.red} red, ${data.summary.yellow} yellow, ${data.summary.green} green`, 'info');
    openDeal(currentDealId);
  } catch (e) { console.error(e); }
}

async function runMathCheck() {
  if (!currentDealId) return;
  const btn = document.getElementById('btn-math');
  const resultsDiv = document.getElementById('math-check-results');
  if (btn) { btn.disabled = true; btn.textContent = '🧮 Checking...'; }
  try {
    const data = await api(`${API.deals}/${currentDealId}/math-check`);
    const checks = data.checks || [];
    const s = data.summary || {};
    
    let html = `<div class="dd-summary-bar" style="margin-bottom:8px;">
      <span class="dd-summary-item" style="background:var(--green-dim);color:var(--green);">✅ ${s.pass || 0} Pass</span>
      <span class="dd-summary-item" style="background:var(--red-dim);color:var(--red);">❌ ${s.fail || 0} Fail</span>
      <span class="dd-summary-item" style="background:#3a3000;color:#ffb700;">⚠️ ${s.warn || 0} Warn</span>
      <span class="dd-summary-item" style="background:var(--surface-2);color:var(--text-muted);">ℹ️ ${s.info || 0} Info</span>
    </div>`;
    
    const statusOrder = {fail: 0, warn: 1, pass: 2, info: 3};
    const sorted = [...checks].sort((a, b) => (statusOrder[a.status] || 9) - (statusOrder[b.status] || 9));
    
    sorted.forEach(c => {
      const icon = c.status === 'pass' ? '✅' : c.status === 'fail' ? '❌' : c.status === 'warn' ? '⚠️' : 'ℹ️';
      const cls = c.status === 'pass' ? 'dd-flag-green' : c.status === 'fail' ? 'dd-flag-red' : c.status === 'warn' ? 'dd-flag-yellow' : '';
      html += `<div class="dd-flag-item ${cls}" style="padding:6px 10px;">
        <span class="dd-flag-icon">${icon}</span>
        <span class="dd-flag-msg">
          <strong>${esc(c.check)}</strong><br>
          <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-muted);">${esc(c.formula)}</span><br>
          <span style="font-size:12px;">Expected: <strong>${esc(String(c.expected))}</strong> | Actual: <strong>${esc(String(c.actual))}</strong> | ${esc(c.difference)}</span>
        </span>
      </div>`;
    });
    
    if (resultsDiv) resultsDiv.innerHTML = html;
    toast(`Math check: ${s.pass || 0} pass, ${s.fail || 0} fail, ${s.warn || 0} warnings`, s.fail ? 'error' : 'success');
  } catch (e) {
    console.error(e);
    toast('Math check failed: ' + (e.message || e), 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🧮 Math Check'; }
  }
}

async function runVerification() {
  if (!currentDealId) return;
  const btn = document.getElementById('btn-verify');
  const resultsDiv = document.getElementById('verification-results');
  if (btn) btn.disabled = true;
  if (btn) btn.textContent = '🔍 Verifying (this takes ~30s)...';
  if (resultsDiv) resultsDiv.innerHTML = '<div style="padding:12px;color:var(--text-muted);">Sending extracted data + document pages to AI for forensic audit...</div>';

  try {
    const data = await api(`${API.deals}/${currentDealId}/verify`, 'POST');
    const v = data.verification || {};
    const summary = v.summary || {};
    const corrections = data.corrections_applied || [];
    const audits = v.audit_results || [];
    const missing = v.missing_data || [];
    const calcChecks = v.calculation_checks || [];

    let html = '';

    // Summary bar
    html += `<div class="dd-summary-bar" style="margin-bottom:12px;">
      <span class="dd-summary-item" style="background:var(--green-dim);color:var(--green);">✅ ${summary.confirmed || 0} Confirmed</span>
      <span class="dd-summary-item" style="background:var(--red-dim);color:var(--red);">❌ ${summary.wrong || 0} Wrong</span>
      <span class="dd-summary-item" style="background:#3a3000;color:#ffb700;">⚠️ ${summary.unverifiable || 0} Unverifiable</span>
      <span class="dd-summary-item" style="background:var(--green-dim);color:var(--green);">🧮 ${summary.calculated_correct || 0} Calcs OK</span>
      ${summary.calculated_wrong ? `<span class="dd-summary-item" style="background:var(--red-dim);color:var(--red);">🧮 ${summary.calculated_wrong} Calcs Wrong</span>` : ''}
      ${summary.missing_found ? `<span class="dd-summary-item" style="background:#002a3a;color:#00b4d8;">📋 ${summary.missing_found} Missing Found</span>` : ''}
      <span class="dd-summary-item" style="background:var(--surface-2);color:var(--text);">🎯 Confidence: ${summary.confidence_score || '?'}%</span>
    </div>`;

    // Corrections applied
    if (corrections.length > 0) {
      html += '<div class="dd-category-group"><div class="dd-category-title">🔧 Auto-Corrections Applied</div>';
      corrections.forEach(c => {
        html += `<div class="dd-flag-item dd-flag-yellow"><span class="dd-flag-icon">🔧</span><span class="dd-flag-msg">${esc(c)}</span></div>`;
      });
      html += '</div>';
    }

    // Wrong values
    const wrongItems = audits.filter(a => a.status === 'wrong');
    if (wrongItems.length > 0) {
      html += '<div class="dd-category-group"><div class="dd-category-title">❌ Incorrect Values (Auto-Corrected)</div>';
      wrongItems.forEach(a => {
        html += `<div class="dd-flag-item dd-flag-red">
          <span class="dd-flag-icon">❌</span>
          <span class="dd-flag-msg"><strong>${a.section}.${a.field}</strong>: Was ${JSON.stringify(a.extracted_value)} → Now ${JSON.stringify(a.correct_value)}<br><em>${esc(a.source || '')}</em></span>
        </div>`;
      });
      html += '</div>';
    }

    // Missing data found
    if (missing.length > 0) {
      html += '<div class="dd-category-group"><div class="dd-category-title">📋 Missing Data Found in Documents</div>';
      missing.forEach(m => {
        html += `<div class="dd-flag-item" style="border-left:3px solid #00b4d8;">
          <span class="dd-flag-icon">📋</span>
          <span class="dd-flag-msg"><strong>${m.section}.${m.field}</strong>: ${JSON.stringify(m.found_value)}<br><em>${esc(m.source || '')}</em></span>
        </div>`;
      });
      html += '</div>';
    }

    // Calculation checks
    if (calcChecks.length > 0) {
      html += '<div class="dd-category-group"><div class="dd-category-title">🧮 Calculation Verification</div>';
      calcChecks.forEach(c => {
        const icon = c.status === 'correct' ? '✅' : '❌';
        const cls = c.status === 'correct' ? 'dd-flag-green' : 'dd-flag-red';
        html += `<div class="dd-flag-item ${cls}">
          <span class="dd-flag-icon">${icon}</span>
          <span class="dd-flag-msg"><strong>${c.calculation}</strong>: ${c.formula} = ${c.inputs} → ${c.result} ${c.status === 'correct' ? '✓' : '≠ ' + c.extracted_value}</span>
        </div>`;
      });
      html += '</div>';
    }

    // Confirmed fields (collapsed)
    const confirmedItems = audits.filter(a => a.status === 'confirmed');
    if (confirmedItems.length > 0) {
      html += `<details style="margin-top:8px;"><summary style="cursor:pointer;color:var(--text-muted);font-size:12px;">✅ ${confirmedItems.length} Confirmed Fields (click to expand)</summary>
        <div class="dd-category-group" style="margin-top:4px;">`;
      confirmedItems.forEach(a => {
        html += `<div class="dd-flag-item dd-flag-green" style="padding:4px 8px;font-size:12px;">
          <span class="dd-flag-icon">✅</span>
          <span class="dd-flag-msg">${a.section}.${a.field}: ${JSON.stringify(a.extracted_value)}</span>
        </div>`;
      });
      html += '</div></details>';
    }

    // Math checks
    const mathChecks = data.math_checks || [];
    const mathSummary = data.math_summary || {};
    if (mathChecks.length > 0) {
      html += `<div class="dd-category-group" style="margin-top:16px;">
        <div class="dd-category-title">🧮 Independent Math Verification (Zero AI — Pure Arithmetic)</div>
        <div class="dd-summary-bar" style="margin-bottom:8px;">
          <span class="dd-summary-item" style="background:var(--green-dim);color:var(--green);">✅ ${mathSummary.pass || 0} Pass</span>
          <span class="dd-summary-item" style="background:var(--red-dim);color:var(--red);">❌ ${mathSummary.fail || 0} Fail</span>
          <span class="dd-summary-item" style="background:#3a3000;color:#ffb700;">⚠️ ${mathSummary.warn || 0} Warn</span>
          <span class="dd-summary-item" style="background:var(--surface-2);color:var(--text-muted);">ℹ️ ${mathSummary.info || 0} Info</span>
        </div>`;
      
      // Show fails first, then warns, then passes
      const statusOrder = {fail: 0, warn: 1, pass: 2, info: 3};
      const sorted = [...mathChecks].sort((a, b) => (statusOrder[a.status] || 9) - (statusOrder[b.status] || 9));
      
      sorted.forEach(c => {
        const icon = c.status === 'pass' ? '✅' : c.status === 'fail' ? '❌' : c.status === 'warn' ? '⚠️' : 'ℹ️';
        const cls = c.status === 'pass' ? 'dd-flag-green' : c.status === 'fail' ? 'dd-flag-red' : c.status === 'warn' ? 'dd-flag-yellow' : '';
        html += `<div class="dd-flag-item ${cls}" style="padding:6px 10px;">
          <span class="dd-flag-icon">${icon}</span>
          <span class="dd-flag-msg">
            <strong>${esc(c.check)}</strong><br>
            <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-muted);">${esc(c.formula)}</span><br>
            <span style="font-size:12px;">Expected: <strong>${esc(String(c.expected))}</strong> | Actual: <strong>${esc(String(c.actual))}</strong> | ${esc(c.difference)}</span>
          </span>
        </div>`;
      });
      html += '</div>';
    }

    if (resultsDiv) resultsDiv.innerHTML = html;
    toast(`Verification complete: ${summary.confirmed || 0} confirmed, ${summary.wrong || 0} corrected, confidence ${summary.confidence_score || '?'}%`, 'info');

    // Refresh the deal to show corrected data
    if (corrections.length > 0) {
      setTimeout(() => openDeal(currentDealId), 1000);
    }
  } catch (e) {
    console.error(e);
    toast('Verification failed: ' + (e.message || e), 'error');
    if (resultsDiv) resultsDiv.innerHTML = `<div style="color:var(--red);padding:8px;">Verification failed: ${esc(e.message || String(e))}</div>`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🔍 Verify Against Source'; }
  }
}

function renderDocumentsTab(deal) {
  const docs = deal.documents || [];

  document.getElementById('tab-documents').innerHTML = `
    <div class="flex gap-2 mb-3">
      <button class="btn btn-primary btn-sm" onclick="extractMetrics()" id="btn-extract">🤖 Extract Metrics</button>
      <button class="btn btn-secondary btn-sm" onclick="scoreDeal()" id="btn-score">📊 Score Deal</button>
    </div>

    <div class="upload-zone" id="upload-zone" onclick="document.getElementById('file-input').click()">
      <div class="upload-icon">📄</div>
      <p><strong>Click to upload</strong> or drag & drop PDF documents</p>
      <p class="text-muted" style="margin-top:4px;font-size:11px;">Upload multiple docs — offering memos, proformas, market studies. All docs are combined for analysis.</p>
    </div>
    <input type="file" id="file-input" accept=".pdf" multiple style="display:none" onchange="uploadFiles(this)">

    <div style="margin-top:8px;margin-bottom:8px;">
      <label style="font-size:11px;font-weight:600;color:var(--text-label);text-transform:uppercase;letter-spacing:0.04em;">Document Type</label>
      <select class="form-input" id="upload-doc-type" style="margin-top:4px;">
        <option value="offering_memo">Offering Memorandum</option>
        <option value="pitch_deck">Pitch Deck</option>
        <option value="proforma">Proforma</option>
        <option value="market_study">Market Study</option>
        <option value="appraisal">Appraisal</option>
        <option value="other">Other</option>
      </select>
    </div>

    <div class="doc-list" id="doc-list">
      ${docs.length ? docs.map(d => `
        <div class="doc-item">
          <span class="doc-item-icon">📄</span>
          <div class="doc-item-info">
            <div class="doc-item-name">${esc(d.filename)}</div>
            <div class="doc-item-meta">${d.doc_type} · ${d.page_count} pages · ${d.has_text ? '✓ Text extracted' : 'No text'}</div>
          </div>
          <div class="doc-item-actions">
            <button class="btn btn-ghost btn-sm" onclick="viewDocText(${d.id})">View</button>
            <button class="btn btn-ghost btn-sm" onclick="deleteDoc(${d.id})" style="color:var(--red);">×</button>
          </div>
        </div>
      `).join('') : '<p class="text-muted text-sm" style="padding:8px;">No documents uploaded yet</p>'}
    </div>
  `;

  // Setup drag & drop
  setTimeout(() => {
    const zone = document.getElementById('upload-zone');
    if (!zone) return;
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('dragover');
      if (e.dataTransfer.files.length) uploadMultipleFiles(Array.from(e.dataTransfer.files));
    });
  }, 50);
}

// ===== File Upload =====
async function uploadFiles(input) {
  if (!input.files.length) return;
  await uploadMultipleFiles(Array.from(input.files));
  input.value = '';
}

function showAnalysisOverlay(step, detail, pct) {
  const ov = document.getElementById('analysis-overlay');
  ov.style.display = 'flex';
  document.getElementById('analysis-step').textContent = step;
  document.getElementById('analysis-detail').textContent = detail || '';
  document.getElementById('analysis-progress').style.width = (pct || 5) + '%';
}
function hideAnalysisOverlay() {
  document.getElementById('analysis-overlay').style.display = 'none';
}

async function uploadMultipleFiles(files) {
  if (!currentDealId || !files.length) return;
  const docType = document.getElementById('upload-doc-type')?.value || 'other';

  showAnalysisOverlay(`Uploading ${files.length} document${files.length > 1 ? 's' : ''}...`, 'Preparing files...', 5);
  try {
    for (let i = 0; i < files.length; i++) {
      showAnalysisOverlay(`Uploading ${i + 1} of ${files.length}...`, files[i].name, 5 + (i / files.length) * 15);
      const formData = new FormData();
      formData.append('file', files[i]);
      formData.append('doc_type', docType);
      await fetch(`${API.deals}/${currentDealId}/documents/upload`, {
        method: 'POST',
        body: formData,
      }).then(r => {
        if (!r.ok) throw new Error(`Upload failed: ${files[i].name}`);
        return r.json();
      });
    }

    // Auto-run full pipeline: Extract → Verify → Score
    try {
      showAnalysisOverlay('Step 1/3: Extracting metrics...', 'AI is reading all pages and extracting financial data. This takes 30-60 seconds.', 25);
      await api(`${API.deals}/${currentDealId}/extract`, { method: 'POST' });

      showAnalysisOverlay('Step 2/3: Verifying data...', 'AI is double-checking extracted values against source documents.', 60);
      await api(`${API.deals}/${currentDealId}/verify`, 'POST');

      showAnalysisOverlay('Step 3/3: Scoring deal...', 'Calculating risk scores and investment grade.', 85);
      await api(`${API.deals}/${currentDealId}/score`, { method: 'POST' });

      showAnalysisOverlay('Analysis complete ✓', 'Loading results...', 100);
      await new Promise(r => setTimeout(r, 500));
      toast('Analysis complete ✓', 'success');
    } catch (e) {
      console.error('Auto-analysis error:', e);
      toast('Upload done. Auto-analysis had an issue — try Extract manually.', 'warn');
    }
    hideAnalysisOverlay();
    openDeal(currentDealId);
  } catch (e) {
    hideAnalysisOverlay();
    toast('Upload failed: ' + e.message, 'error');
  }
}

async function deleteDoc(docId) {
  if (!confirm('Delete this document?')) return;
  await api(`${API.deals}/documents/${docId}`, { method: 'DELETE' });
  toast('Document deleted', 'success');
  openDeal(currentDealId);
}

async function viewDocText(docId) {
  try {
    const data = await api(`${API.deals}/documents/${docId}/text`);
    const win = window.open('', '_blank');
    win.document.write(`<html><head><title>${data.filename}</title><style>body{font-family:monospace;padding:24px;font-size:13px;line-height:1.6;max-width:900px;margin:0 auto;white-space:pre-wrap;}</style></head><body>${esc(data.text)}</body></html>`);
  } catch (e) { console.error(e); }
}

// ===== AI Actions =====
async function extractMetrics() {
  if (!currentDealId) return;
  const btn = document.getElementById('btn-extract');
  btn.disabled = true;
  showAnalysisOverlay('Step 1/3: Extracting metrics...', 'AI is reading all pages and extracting financial data. This takes 30-60 seconds.', 25);
  try {
    await api(`${API.deals}/${currentDealId}/extract`, { method: 'POST' });

    // Step 2: Auto-verify
    showAnalysisOverlay('Step 2/3: Verifying data...', 'AI is double-checking extracted values against source documents.', 60);
    const vResult = await api(`${API.deals}/${currentDealId}/verify`, 'POST');
    const corrections = vResult.corrections_applied || [];
    const conf = vResult.verification?.summary?.confidence_score || '?';

    if (corrections.length > 0) {
      toast(`Verified (${conf}% confidence). ${corrections.length} corrections applied.`, 'success');
    } else {
      toast(`Verified (${conf}% confidence). All values confirmed.`, 'success');
    }

    // Step 3: Auto-score
    showAnalysisOverlay('Step 3/3: Scoring deal...', 'Calculating risk scores and investment grade.', 85);
    await api(`${API.deals}/${currentDealId}/score`, { method: 'POST' });

    showAnalysisOverlay('Analysis complete ✓', 'Loading results...', 100);
    await new Promise(r => setTimeout(r, 500));
    hideAnalysisOverlay();
    openDeal(currentDealId);
  } catch (e) {
    hideAnalysisOverlay();
    console.error(e);
    toast('Extraction failed: ' + (e.message || e), 'error');
    openDeal(currentDealId);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '🤖 Extract Metrics';
  }
}

async function scoreDeal() {
  if (!currentDealId) return;
  const btn = document.getElementById('btn-score');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Scoring...';
  try {
    await api(`${API.deals}/${currentDealId}/score`, { method: 'POST' });
    toast('Deal scored', 'success');
    openDeal(currentDealId);
  } catch (e) {
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '📊 Score Deal';
  }
}

async function updateDealStatus() {
  if (!currentDealId) return;
  const status = document.getElementById('detail-status').value;
  await api(`${API.deals}/${currentDealId}`, {
    method: 'PUT',
    body: JSON.stringify({ status }),
  });
  toast('Status updated', 'success');
}

async function saveDealNotes() {
  if (!currentDealId) return;
  const notes = document.getElementById('deal-notes')?.value || '';
  await api(`${API.deals}/${currentDealId}`, {
    method: 'PUT',
    body: JSON.stringify({ notes }),
  });
}

// ===== Chat =====
async function loadChatHistory(dealId) {
  try {
    const history = await api(`${API.chat}/history/${dealId}`);
    const container = document.getElementById('chat-messages');
    container.innerHTML = history.map(m => `
      <div class="chat-message ${m.role}">
        <div class="chat-avatar">${m.role === 'user' ? '👤' : '🤖'}</div>
        <div class="chat-bubble">${esc(m.content)}</div>
      </div>
    `).join('');
    container.scrollTop = container.scrollHeight;
  } catch (e) { console.error(e); }
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg = input.value.trim();
  if (!msg || !currentDealId) return;
  input.value = '';

  // Add user message to UI
  const container = document.getElementById('chat-messages');
  container.innerHTML += `
    <div class="chat-message user">
      <div class="chat-avatar">👤</div>
      <div class="chat-bubble">${esc(msg)}</div>
    </div>
  `;
  container.scrollTop = container.scrollHeight;

  // Show typing indicator
  container.innerHTML += `<div class="chat-message assistant" id="typing"><div class="chat-avatar">🤖</div><div class="chat-bubble"><span class="spinner"></span> Thinking...</div></div>`;
  container.scrollTop = container.scrollHeight;

  try {
    const data = await api(API.chat, {
      method: 'POST',
      body: JSON.stringify({ deal_id: currentDealId, message: msg }),
    });
    document.getElementById('typing')?.remove();
    container.innerHTML += `
      <div class="chat-message assistant">
        <div class="chat-avatar">🤖</div>
        <div class="chat-bubble">${esc(data.response)}</div>
      </div>
    `;
    container.scrollTop = container.scrollHeight;
  } catch (e) {
    document.getElementById('typing')?.remove();
  }
}

// ===== Compare =====
async function loadCompareList() {
  try {
    allDeals = await api(API.deals);
    const container = document.getElementById('compare-deals-list');
    container.innerHTML = allDeals.map(d => `
      <label class="compare-deal-item ${selectedCompareIds.has(d.id) ? 'selected' : ''}">
        <input type="checkbox" ${selectedCompareIds.has(d.id) ? 'checked' : ''} onchange="toggleCompare(${d.id}, this.checked)">
        <div>
          <div style="font-weight:600;">${esc(d.project_name)}</div>
          <div style="font-size:10px;color:var(--text-muted);">${esc(d.developer_name || '')} · ${d.overall_score != null ? d.overall_score.toFixed(1) : '—'}</div>
        </div>
      </label>
    `).join('');

    document.getElementById('btn-compare').disabled = selectedCompareIds.size < 2;
  } catch (e) { console.error(e); }
}

function toggleCompare(id, checked) {
  if (checked) selectedCompareIds.add(id);
  else selectedCompareIds.delete(id);

  document.getElementById('btn-compare').disabled = selectedCompareIds.size < 2;

  // Update visual
  document.querySelectorAll('.compare-deal-item').forEach(el => {
    const cb = el.querySelector('input[type="checkbox"]');
    if (cb.checked) el.classList.add('selected');
    else el.classList.remove('selected');
  });
}

async function runComparison() {
  const ids = Array.from(selectedCompareIds);
  if (ids.length < 2) return;

  try {
    const data = await api(`${API.deals}/compare`, {
      method: 'POST',
      body: JSON.stringify({ deal_ids: ids }),
    });
    renderCompareTable(data.deals);
    document.getElementById('btn-export').style.display = 'inline-flex';
  } catch (e) { console.error(e); }
}

function renderCompareTable(deals) {
  const container = document.getElementById('compare-table-container');

  // Define all metric rows
  const sections = [
    { name: 'Scores', rows: [
      ['Overall Score', d => d.scores?.overall?.toFixed(1)],
      ['Returns', d => d.scores?.returns?.score],
      ['Market', d => d.scores?.market?.score],
      ['Structure', d => d.scores?.structure?.score],
      ['Risk', d => d.scores?.risk?.score],
      ['Financials', d => d.scores?.financials?.score],
    ]},
    { name: 'Deal Structure', rows: [
      ['Investment Class', d => d.metrics?.deal_structure?.investment_class],
      ['Min Investment', d => fmt$(d.metrics?.deal_structure?.minimum_investment)],
      ['Total Project Cost', d => fmt$(d.metrics?.deal_structure?.total_project_cost)],
      ['Total Equity', d => fmt$(d.metrics?.deal_structure?.total_equity_required)],
      ['LTV', d => fmtPct(d.metrics?.deal_structure?.ltv)],
      ['Interest Rate', d => fmtPct(d.metrics?.deal_structure?.interest_rate)],
      ['Hold Period', d => d.metrics?.deal_structure?.hold_period_years ? d.metrics.deal_structure.hold_period_years + ' yrs' : null],
      ['Preferred Return', d => fmtPct(d.metrics?.deal_structure?.preferred_return)],
      ['GP Co-Invest', d => d.metrics?.deal_structure?.gp_coinvest],
      ['Asset Mgmt Fee', d => fmtPct(d.metrics?.deal_structure?.fees_asset_mgmt)],
    ]},
    { name: 'Target Returns', rows: [
      ['Target IRR', d => d.metrics?.target_returns?.target_irr, true],
      ['Equity Multiple', d => d.metrics?.target_returns?.target_equity_multiple, true],
      ['Cash-on-Cash', d => d.metrics?.target_returns?.target_cash_on_cash, true],
      ['Avg Annual Return', d => d.metrics?.target_returns?.target_avg_annual_return, true],
      ['Projected Profit', d => fmt$(d.metrics?.target_returns?.projected_profit)],
    ]},
    { name: 'Project Details', rows: [
      ['Units', d => d.metrics?.project_details?.unit_count],
      ['Total SqFt', d => fmtNum(d.metrics?.project_details?.total_sqft)],
      ['Price/Unit', d => fmt$(d.metrics?.project_details?.price_per_unit)],
      ['Price/SqFt', d => fmt$(d.metrics?.project_details?.price_per_sqft)],
      ['Construction Type', d => d.metrics?.project_details?.construction_type],
      ['Entitlement Status', d => d.metrics?.project_details?.entitlement_status],
    ]},
    { name: 'Financials', rows: [
      ['Stabilized NOI', d => fmt$(d.metrics?.financial_projections?.stabilized_noi)],
      ['Entry Cap Rate', d => fmtPct(d.metrics?.financial_projections?.entry_cap_rate)],
      ['Exit Cap Rate', d => fmtPct(d.metrics?.financial_projections?.exit_cap_rate)],
      ['Avg Rent/Unit', d => fmt$(d.metrics?.financial_projections?.avg_rent_per_unit)],
      ['Rent Growth', d => fmtPct(d.metrics?.financial_projections?.rent_growth_assumption)],
      ['Occupancy', d => fmtPct(d.metrics?.financial_projections?.occupancy_assumption)],
    ]},
  ];

  let html = '<div style="overflow:auto;"><table class="compare-table">';

  // Header
  html += '<thead><tr><th>Metric</th>';
  deals.forEach(d => {
    html += `<th>${esc(d.project_name)}<br><span style="font-weight:400;font-size:10px;opacity:0.7;">${esc(d.developer_name || '')}</span></th>`;
  });
  html += '</tr></thead><tbody>';

  sections.forEach(section => {
    html += `<tr class="section-header"><td colspan="${deals.length + 1}">${section.name}</td></tr>`;
    section.rows.forEach(([label, getter, isHigherBetter]) => {
      html += `<tr><td>${label}</td>`;
      const vals = deals.map(d => {
        const raw = getter(d);
        return { display: raw != null ? String(raw) : '—', raw: typeof raw === 'number' ? raw : null };
      });

      // Find best/worst for numeric rows
      const nums = vals.filter(v => v.raw != null).map(v => v.raw);
      const max = nums.length >= 2 ? Math.max(...nums) : null;
      const min = nums.length >= 2 ? Math.min(...nums) : null;

      vals.forEach(v => {
        let cls = '';
        if (v.raw != null && max !== min) {
          if (isHigherBetter !== false) {
            if (v.raw === max) cls = 'best';
            if (v.raw === min) cls = 'worst';
          }
        }
        html += `<td class="${cls}">${esc(v.display)}</td>`;
      });
      html += '</tr>';
    });
  });

  html += '</tbody></table></div>';
  container.innerHTML = html;
}

async function exportComparison() {
  const ids = Array.from(selectedCompareIds);
  if (ids.length < 2) return;

  try {
    const res = await fetch(`${API.deals}/compare/export`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deal_ids: ids }),
    });
    if (!res.ok) throw new Error('Export failed');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'deal_comparison.xlsx';
    a.click();
    URL.revokeObjectURL(url);
    toast('Excel exported', 'success');
  } catch (e) {
    toast('Export failed', 'error');
  }
}

// ===== Developers =====
async function loadDevelopers() {
  try {
    allDevelopers = await api(API.developers);
    renderDevelopers();
  } catch (e) { console.error(e); }
}

function renderDevelopers() {
  const grid = document.getElementById('dev-grid');
  const empty = document.getElementById('dev-empty');

  if (!allDevelopers.length) {
    grid.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  grid.innerHTML = allDevelopers.map(d => `
    <div class="dev-card" onclick="viewDeveloper(${d.id})">
      <div class="dev-card-name">${esc(d.name)}</div>
      <div class="dev-card-contact">${esc(d.contact_name || '')}${d.contact_email ? ' · ' + esc(d.contact_email) : ''}</div>
      <div class="dev-card-stats">
        <div class="dev-stat">
          <div class="dev-stat-value">${d.deal_count}</div>
          <div class="dev-stat-label">Deals</div>
        </div>
      </div>
    </div>
  `).join('');
}

function openAddDevModal() {
  openModal('modal-add-dev');
}

async function createDeveloper() {
  const name = document.getElementById('new-dev-name').value.trim();
  if (!name) { toast('Company name required', 'error'); return; }

  const data = {
    name,
    contact_name: document.getElementById('new-dev-contact').value,
    contact_email: document.getElementById('new-dev-email').value,
    phone: document.getElementById('new-dev-phone').value,
    track_record: document.getElementById('new-dev-track').value,
    notes: document.getElementById('new-dev-notes').value,
  };

  await api(API.developers, { method: 'POST', body: JSON.stringify(data) });
  closeModal('modal-add-dev');
  toast('Developer added', 'success');
  // Clear
  document.getElementById('new-dev-name').value = '';
  document.getElementById('new-dev-contact').value = '';
  document.getElementById('new-dev-email').value = '';
  document.getElementById('new-dev-phone').value = '';
  document.getElementById('new-dev-track').value = '';
  document.getElementById('new-dev-notes').value = '';
  loadDevelopers();
}

async function viewDeveloper(id) {
  currentDeveloperId = id;
  try {
    const dev = await api(`${API.developers}/${id}`);
    document.getElementById('dev-detail-title').textContent = dev.name || 'Developer';
    renderDeveloperDetail(dev);
    showPage('developer-detail');
  } catch (e) { console.error(e); }
}

function renderDeveloperDetail(dev) {
  const el = document.getElementById('dev-detail-content');
  const deals = dev.deals || [];
  const joined = dev.created_at ? new Date(dev.created_at).toLocaleDateString() : '—';

  function row(label, val) {
    return `<div class="metric-row"><span class="metric-label">${label}</span><span class="metric-value">${val}</span></div>`;
  }

  // Summary stats
  const scored = deals.filter(d => (d.scores || {}).overall != null);
  const avgScore = scored.length
    ? (scored.reduce((a, d) => a + d.scores.overall, 0) / scored.length).toFixed(1)
    : '—';
  const reviewing = deals.filter(d => d.status === 'reviewing').length;
  const committed = deals.filter(d => d.status === 'committed' || d.status === 'closed').length;

  // Contact card
  const contactCard = `
    <div class="metrics-section">
      <div class="metrics-section-title">Contact</div>
      <div class="metrics-grid">
        ${row('Contact Name', esc(dev.contact_name || '—'))}
        ${row('Email', dev.contact_email ? `<a href="mailto:${esc(dev.contact_email)}">${esc(dev.contact_email)}</a>` : '—')}
        ${row('Phone', dev.phone ? `<a href="tel:${esc(dev.phone)}">${esc(dev.phone)}</a>` : '—')}
        ${row('Joined', joined)}
      </div>
    </div>
  `;

  // Summary stats cards
  const statsCard = `
    <div class="stats-grid mb-3">
      <div class="stat-card"><div class="stat-label">Total Deals</div><div class="stat-value">${deals.length}</div></div>
      <div class="stat-card"><div class="stat-label">Avg Score</div><div class="stat-value">${avgScore}</div></div>
      <div class="stat-card"><div class="stat-label">Reviewing</div><div class="stat-value">${reviewing}</div></div>
      <div class="stat-card"><div class="stat-label">Committed / Closed</div><div class="stat-value">${committed}</div></div>
    </div>
  `;

  // Track record
  const trackCard = dev.track_record ? `
    <div class="metrics-section">
      <div class="metrics-section-title">Track Record</div>
      <p style="padding:8px 12px;font-size:13px;white-space:pre-wrap;line-height:1.5;">${esc(dev.track_record)}</p>
    </div>
  ` : '';

  // Notes
  const notesCard = dev.notes ? `
    <div class="metrics-section">
      <div class="metrics-section-title">Notes</div>
      <p style="padding:8px 12px;font-size:13px;white-space:pre-wrap;line-height:1.5;">${esc(dev.notes)}</p>
    </div>
  ` : '';

  // Deals table
  const dealsCard = `
    <div class="metrics-section">
      <div class="metrics-section-title">Deals (${deals.length})</div>
      ${deals.length ? `
        <table class="dist-table">
          <thead><tr><th>Project</th><th>Type</th><th>Status</th><th>Score</th><th></th></tr></thead>
          <tbody>
            ${deals.map(d => {
              const score = (d.scores || {}).overall;
              const scoreDisplay = score != null
                ? `<span style="color:${scoreColor(score)};font-weight:600;">${score.toFixed(1)}</span>`
                : '—';
              return `
                <tr style="cursor:pointer;" onclick="openDeal(${d.id})">
                  <td><strong>${esc(d.project_name)}</strong></td>
                  <td>${esc(d.property_type || '—')}</td>
                  <td><span class="${statusClass(d.status)}">${esc(d.status || 'reviewing')}</span></td>
                  <td>${scoreDisplay}</td>
                  <td><button class="btn btn-secondary btn-sm" onclick="event.stopPropagation();openDeal(${d.id})">Open</button></td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      ` : '<p style="padding:12px;color:var(--text-muted);font-size:13px;">No deals tracked for this developer yet.</p>'}
    </div>
  `;

  el.innerHTML = statsCard + contactCard + trackCard + notesCard + dealsCard;
}

function openEditDevModal() {
  if (!currentDeveloperId) return;
  const dev = allDevelopers.find(d => d.id === currentDeveloperId) || {};
  document.getElementById('edit-dev-name').value = dev.name || '';
  document.getElementById('edit-dev-contact').value = dev.contact_name || '';
  document.getElementById('edit-dev-email').value = dev.contact_email || '';
  document.getElementById('edit-dev-phone').value = dev.phone || '';
  document.getElementById('edit-dev-track').value = dev.track_record || '';
  document.getElementById('edit-dev-notes').value = dev.notes || '';
  openModal('modal-edit-dev');
}

async function saveDeveloperEdit() {
  if (!currentDeveloperId) return;
  const name = document.getElementById('edit-dev-name').value.trim();
  if (!name) { toast('Company name required', 'error'); return; }

  const data = {
    name,
    contact_name: document.getElementById('edit-dev-contact').value,
    contact_email: document.getElementById('edit-dev-email').value,
    phone: document.getElementById('edit-dev-phone').value,
    track_record: document.getElementById('edit-dev-track').value,
    notes: document.getElementById('edit-dev-notes').value,
  };

  try {
    await api(`${API.developers}/${currentDeveloperId}`, 'PUT', data);
    closeModal('modal-edit-dev');
    toast('Developer updated', 'success');
    // Refresh cached list and detail view
    allDevelopers = await api(API.developers);
    viewDeveloper(currentDeveloperId);
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function deleteDeveloper() {
  if (!currentDeveloperId) return;
  const dev = allDevelopers.find(d => d.id === currentDeveloperId) || {};
  const dealCount = dev.deal_count || 0;
  const msg = dealCount > 0
    ? `Delete "${dev.name}"? This will also delete ${dealCount} associated deal${dealCount > 1 ? 's' : ''} and cannot be undone.`
    : `Delete "${dev.name}"? This cannot be undone.`;
  if (!confirm(msg)) return;

  try {
    await api(`${API.developers}/${currentDeveloperId}`, 'DELETE');
    toast('Developer deleted', 'info');
    currentDeveloperId = null;
    showPage('developers');
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

// Mobile sidebar toggle
function toggleMobileSidebar() {
  document.querySelector('.sidebar').classList.toggle('open');
  document.getElementById('mobile-overlay').classList.toggle('active');
}
// Close sidebar on nav click (mobile)
document.querySelectorAll('.nav-item').forEach(el => {
  el.addEventListener('click', () => {
    document.querySelector('.sidebar').classList.remove('open');
    document.getElementById('mobile-overlay').classList.remove('active');
  });
});

// ===== Portfolio / Investments =====

async function loadPortfolio() {
  try {
    const [investments, summary, deals] = await Promise.all([
      api(`${API.investments}/`),
      api(`${API.investments}/portfolio`),
      api(API.deals),
    ]);
    allInvestments = investments;
    allDeals = deals;
    renderPortfolioSummary(summary);
    renderInvestmentsList(investments);
  } catch (e) { console.error(e); }
}

function renderPortfolioSummary(s) {
  const el = document.getElementById('portfolio-summary');
  el.innerHTML = `
    <div class="portfolio-cards">
      <div class="portfolio-card">
        <div class="portfolio-card-value">${fmt$(s.total_invested)}</div>
        <div class="portfolio-card-label">Total Invested</div>
      </div>
      <div class="portfolio-card">
        <div class="portfolio-card-value">${fmt$(s.total_distributions)}</div>
        <div class="portfolio-card-label">Distributions</div>
      </div>
      <div class="portfolio-card">
        <div class="portfolio-card-value" style="color:${s.net_profit >= 0 ? 'var(--green)' : 'var(--red)'};">${fmt$(s.net_profit)}</div>
        <div class="portfolio-card-label">Net Profit</div>
      </div>
      <div class="portfolio-card">
        <div class="portfolio-card-value">${s.overall_multiple}x</div>
        <div class="portfolio-card-label">Multiple</div>
      </div>
      <div class="portfolio-card">
        <div class="portfolio-card-value">${s.active_investments}</div>
        <div class="portfolio-card-label">Active</div>
      </div>
      <div class="portfolio-card">
        <div class="portfolio-card-value">${s.exited_investments}</div>
        <div class="portfolio-card-label">Exited</div>
      </div>
    </div>
  `;
}

function renderInvestmentsList(investments) {
  const el = document.getElementById('investments-list');
  const empty = document.getElementById('investments-empty');

  if (!investments.length) {
    el.innerHTML = '';
    empty.style.display = 'block';
    return;
  }
  empty.style.display = 'none';

  const statusColors = {
    active: 'var(--green)', exited: 'var(--accent)', pending: 'var(--yellow)', defaulted: 'var(--red)'
  };

  el.innerHTML = `<div class="investments-grid">${investments.map(inv => {
    const sc = statusColors[inv.status] || 'var(--text-muted)';
    return `
      <div class="investment-card" onclick="openInvestment(${inv.id})">
        <div class="inv-card-header">
          <div class="inv-card-name">${esc(inv.project_name || 'Untitled')}</div>
          <span class="inv-status-badge" style="color:${sc};border-color:${sc};">${inv.status}</span>
        </div>
        <div class="inv-card-sponsor">${esc(inv.sponsor_name || '—')}</div>
        <div class="inv-card-metrics">
          <div class="inv-metric">
            <span class="inv-metric-val">${fmt$(inv.amount_invested)}</span>
            <span class="inv-metric-lbl">Invested</span>
          </div>
          <div class="inv-metric">
            <span class="inv-metric-val">${fmt$(inv.total_distributions)}</span>
            <span class="inv-metric-lbl">Distributions</span>
          </div>
          <div class="inv-metric">
            <span class="inv-metric-val">${inv.actual_multiple}x</span>
            <span class="inv-metric-lbl">Multiple</span>
          </div>
          <div class="inv-metric">
            <span class="inv-metric-val">${inv.actual_coc ? inv.actual_coc + '%' : '—'}</span>
            <span class="inv-metric-lbl">CoC</span>
          </div>
        </div>
      </div>
    `;
  }).join('')}</div>`;
}

async function openInvestment(id) {
  currentInvestmentId = id;
  try {
    const inv = await api(`${API.investments}/${id}`);
    document.getElementById('inv-detail-title').textContent = inv.project_name || 'Investment Detail';
    document.getElementById('inv-status').value = inv.status;
    renderInvestmentDetail(inv);
    showPage('investment-detail');
  } catch (e) { console.error(e); }
}

function renderInvestmentDetail(inv) {
  const el = document.getElementById('inv-detail-content');
  const dists = inv.distributions || [];

  function row(label, val) {
    return `<div class="metric-row"><span class="metric-label">${label}</span><span class="metric-value">${val}</span></div>`;
  }

  el.innerHTML = `
    <div class="metrics-section">
      <div class="metrics-section-title">Investment Summary</div>
      <div class="metrics-grid">
        ${row('Project', esc(inv.project_name || '—'))}
        ${row('Sponsor', esc(inv.sponsor_name || '—'))}
        ${row('Investment Date', inv.investment_date || '—')}
        ${row('Amount Invested', fmt$(inv.amount_invested))}
        ${row('Shares/Units', inv.shares || '—')}
        ${row('Class', esc(inv.investment_class || '—'))}
        ${row('Preferred Return', inv.preferred_return != null ? inv.preferred_return + '%' : '—')}
        ${row('Projected IRR', inv.projected_irr != null ? inv.projected_irr + '%' : '—')}
        ${row('Projected Multiple', inv.projected_equity_multiple != null ? inv.projected_equity_multiple + 'x' : '—')}
        ${row('Hold Period', inv.hold_period_years != null ? inv.hold_period_years + ' years' : '—')}
      </div>
    </div>

    <div class="metrics-section">
      <div class="metrics-section-title">Performance</div>
      <div class="metrics-grid">
        ${row('Total Distributions', fmt$(inv.total_distributions))}
        ${row('Total Returned', fmt$(inv.total_returned))}
        ${row('Net Profit', `<span style="color:${inv.net_profit >= 0 ? 'var(--green)' : 'var(--red)'};">${fmt$(inv.net_profit)}</span>`)}
        ${row('Actual Multiple', inv.actual_multiple + 'x')}
        ${row('Actual Cash-on-Cash', inv.actual_coc ? inv.actual_coc + '%' : '—')}
        ${inv.exit_date ? row('Exit Date', inv.exit_date) : ''}
        ${inv.exit_amount ? row('Exit Amount', fmt$(inv.exit_amount)) : ''}
      </div>
    </div>

    <div class="metrics-section">
      <div class="metrics-section-title" style="display:flex;justify-content:space-between;align-items:center;">
        Distributions
        <button class="btn btn-primary btn-sm" onclick="openAddDistModal()">+ Add Distribution</button>
      </div>
      ${dists.length ? `
        <table class="dist-table">
          <thead><tr><th>Date</th><th>Amount</th><th>Type</th><th>Period</th><th></th></tr></thead>
          <tbody>
            ${dists.map(d => `
              <tr>
                <td>${d.date || '—'}</td>
                <td>${fmt$(d.amount)}</td>
                <td>${d.dist_type.replace('_', ' ')}</td>
                <td>${esc(d.period || '—')}</td>
                <td><button class="btn-icon btn-sm" onclick="deleteDist(${d.id})" title="Delete">×</button></td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      ` : '<p style="padding:12px;color:var(--text-muted);font-size:13px;">No distributions recorded yet.</p>'}
    </div>

    ${inv.notes ? `<div class="metrics-section"><div class="metrics-section-title">Notes</div><p style="padding:8px 12px;font-size:13px;">${esc(inv.notes)}</p></div>` : ''}

    ${inv.deal_id ? `<div style="margin-top:12px;"><button class="btn btn-secondary btn-sm" onclick="openDeal(${inv.deal_id})">📋 View Deal Analysis</button></div>` : ''}
  `;
}

function openAddInvestmentModal() {
  // Populate deal dropdown
  const sel = document.getElementById('inv-deal-id');
  sel.innerHTML = '<option value="">— None (standalone) —</option>' +
    allDeals.map(d => `<option value="${d.id}">${esc(d.project_name)}</option>`).join('');
  // Clear form
  ['inv-project-name','inv-sponsor','inv-amount','inv-shares','inv-date','inv-class','inv-pref','inv-irr','inv-em','inv-hold','inv-notes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  openModal('modal-add-investment');
}

async function createInvestment() {
  const name = document.getElementById('inv-project-name').value.trim();
  const dealId = document.getElementById('inv-deal-id').value;
  if (!name && !dealId) { toast('Project name required', 'error'); return; }

  const data = {
    deal_id: dealId ? parseInt(dealId) : null,
    project_name: name,
    sponsor_name: document.getElementById('inv-sponsor').value.trim(),
    amount_invested: parseFloat(document.getElementById('inv-amount').value) || 0,
    shares: parseFloat(document.getElementById('inv-shares').value) || 0,
    investment_date: document.getElementById('inv-date').value || null,
    investment_class: document.getElementById('inv-class').value.trim(),
    preferred_return: parseFloat(document.getElementById('inv-pref').value) || null,
    projected_irr: parseFloat(document.getElementById('inv-irr').value) || null,
    projected_equity_multiple: parseFloat(document.getElementById('inv-em').value) || null,
    hold_period_years: parseFloat(document.getElementById('inv-hold').value) || null,
    notes: document.getElementById('inv-notes').value.trim(),
  };

  try {
    await api(`${API.investments}/`, 'POST', data);
    closeModal('modal-add-investment');
    toast('Investment added', 'success');
    loadPortfolio();
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function updateInvestmentStatus() {
  if (!currentInvestmentId) return;
  const status = document.getElementById('inv-status').value;
  try {
    await api(`${API.investments}/${currentInvestmentId}`, 'PUT', { status });
    toast('Status updated', 'success');
  } catch (e) { console.error(e); }
}

async function deleteInvestment() {
  if (!currentInvestmentId || !confirm('Delete this investment?')) return;
  try {
    await api(`${API.investments}/${currentInvestmentId}`, 'DELETE');
    toast('Investment deleted', 'info');
    showPage('portfolio');
  } catch (e) { console.error(e); }
}

function openAddDistModal() {
  document.getElementById('dist-date').value = new Date().toISOString().split('T')[0];
  document.getElementById('dist-amount').value = '';
  document.getElementById('dist-type').value = 'cash_flow';
  document.getElementById('dist-period').value = '';
  document.getElementById('dist-notes').value = '';
  openModal('modal-add-distribution');
}

async function addDistribution() {
  if (!currentInvestmentId) return;
  const data = {
    date: document.getElementById('dist-date').value,
    amount: parseFloat(document.getElementById('dist-amount').value) || 0,
    dist_type: document.getElementById('dist-type').value,
    period: document.getElementById('dist-period').value.trim(),
    notes: document.getElementById('dist-notes').value.trim(),
  };
  if (!data.date || !data.amount) { toast('Date and amount required', 'error'); return; }

  try {
    await api(`${API.investments}/${currentInvestmentId}/distributions`, 'POST', data);
    closeModal('modal-add-distribution');
    toast('Distribution recorded', 'success');
    openInvestment(currentInvestmentId);
  } catch (e) { toast('Error: ' + e.message, 'error'); }
}

async function deleteDist(distId) {
  if (!currentInvestmentId || !confirm('Delete this distribution?')) return;
  try {
    await api(`${API.investments}/${currentInvestmentId}/distributions/${distId}`, 'DELETE');
    toast('Distribution deleted', 'info');
    openInvestment(currentInvestmentId);
  } catch (e) { console.error(e); }
}
