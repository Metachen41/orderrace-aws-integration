/* ================================================================
   OrderRace Admin Dashboard
   ================================================================
   CONFIG: Set these values after deployment.
   They are printed as CloudFormation Outputs after `sam deploy`.
   ================================================================ */

const CONFIG = {
  API_URL: '',          // e.g. https://xxxx.execute-api.eu-central-1.amazonaws.com/Prod
  USER_POOL_ID: '',     // e.g. eu-central-1_xxxxxxx
  CLIENT_ID: '',        // e.g. 1abc2def3ghi4jkl
  REGION: 'eu-central-1',
};

/* Try to load config from config.js (created during deploy) */
if (window.DASHBOARD_CONFIG) {
  Object.assign(CONFIG, window.DASHBOARD_CONFIG);
}

/* ================================================================
   Auth State
   ================================================================ */
let idToken = null;
let cognitoUser = null;
let typesChart = null;
let apiChart = null;

/* ================================================================
   Cognito Auth
   ================================================================ */
const poolData = {
  UserPoolId: CONFIG.USER_POOL_ID,
  ClientId: CONFIG.CLIENT_ID,
};

function getPool() {
  return new AmazonCognitoIdentity.CognitoUserPool(poolData);
}

function checkSession() {
  const pool = getPool();
  const user = pool.getCurrentUser();
  if (!user) return;
  user.getSession((err, session) => {
    if (err || !session || !session.isValid()) return;
    idToken = session.getIdToken().getJwtToken();
    cognitoUser = user;
    showDashboard(user.getUsername());
  });
}

document.getElementById('login-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const email = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  errEl.style.display = 'none';

  const authData = {
    Username: email,
    Password: password,
  };
  const authDetails = new AmazonCognitoIdentity.AuthenticationDetails(authData);
  const userData = { Username: email, Pool: getPool() };
  const user = new AmazonCognitoIdentity.CognitoUser(userData);

  user.authenticateUser(authDetails, {
    onSuccess: (session) => {
      idToken = session.getIdToken().getJwtToken();
      cognitoUser = user;
      showDashboard(email);
    },
    onFailure: (err) => {
      errEl.textContent = err.message || 'Anmeldung fehlgeschlagen';
      errEl.style.display = 'block';
    },
    newPasswordRequired: () => {
      cognitoUser = user;
      document.getElementById('login-form').style.display = 'none';
      document.getElementById('new-password-form').style.display = 'block';
    },
  });
});

document.getElementById('new-password-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const newPw = document.getElementById('new-password').value;
  const errEl = document.getElementById('login-error');
  errEl.style.display = 'none';

  cognitoUser.completeNewPasswordChallenge(newPw, {}, {
    onSuccess: (session) => {
      idToken = session.getIdToken().getJwtToken();
      showDashboard(cognitoUser.getUsername());
    },
    onFailure: (err) => {
      errEl.textContent = err.message || 'Passwort konnte nicht gesetzt werden';
      errEl.style.display = 'block';
    },
  });
});

function showDashboard(username) {
  document.getElementById('login-view').style.display = 'none';
  document.getElementById('dashboard-view').style.display = 'block';
  document.getElementById('user-info').textContent = username;
  loadAll();
}

/* ================================================================
   API Calls
   ================================================================ */
async function apiGet(path) {
  const resp = await fetch(`${CONFIG.API_URL}${path}`, {
    headers: { Authorization: `Bearer ${idToken}` },
  });
  if (resp.status === 401) {
    app.logout();
    throw new Error('Session expired');
  }
  return resp.json();
}

/* ================================================================
   Data Loading
   ================================================================ */
async function loadAll() {
  await Promise.all([loadStats(), loadOrders(), loadEvents(), loadMetrics()]);
}

async function loadStats() {
  try {
    const data = await apiGet('/admin/api/stats');
    document.getElementById('stat-total').textContent = data.total_orders ?? '-';
    document.getElementById('stat-today').textContent = data.today_orders ?? '-';
    document.getElementById('stat-pending').textContent = data.pending_downloads ?? '-';
    document.getElementById('stat-processed').textContent = data.fully_processed ?? '-';
    document.getElementById('stat-errors').textContent = data.errors_today ?? '-';
    document.getElementById('stat-files').textContent = data.total_files ?? '-';
    renderTypesChart(data.by_type || {});
  } catch (e) {
    console.error('Stats load error:', e);
  }
}

async function loadOrders() {
  try {
    const data = await apiGet('/admin/api/orders?limit=200');
    const orders = data.orders || [];
    renderRecentOrders(orders.slice(0, 10));
    renderAllOrders(orders);
  } catch (e) {
    console.error('Orders load error:', e);
  }
}

async function loadEvents() {
  try {
    const data = await apiGet('/admin/api/events?days=7&limit=200');
    const events = data.events || [];
    renderEvents(events);
    renderErrors(events.filter(e => e.event_type.includes('ERROR')));
  } catch (e) {
    console.error('Events load error:', e);
  }
}

async function loadMetrics() {
  try {
    const data = await apiGet('/admin/api/metrics?hours=168');
    renderApiChart(data.metrics || {});
  } catch (e) {
    console.error('Metrics load error:', e);
  }
}

/* ================================================================
   Rendering
   ================================================================ */
function formatTime(ts) {
  if (!ts) return '-';
  const d = ts > 9999999999 ? new Date(ts) : new Date(ts * 1000);
  return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function statusBadge(status) {
  const map = {
    pending: ['badge-warning', 'Offen'],
    partial: ['badge-info', 'Teilweise'],
    processed: ['badge-success', 'Abgeholt'],
    empty: ['badge-muted', 'Leer'],
  };
  const [cls, label] = map[status] || ['badge-muted', status];
  return `<span class="badge ${cls}">${label}</span>`;
}

function eventBadge(type) {
  if (type.includes('ERROR')) return `<span class="badge badge-danger">${type}</span>`;
  if (type.includes('SUCCESS')) return `<span class="badge badge-success">${type}</span>`;
  return `<span class="badge badge-info">${type}</span>`;
}

function renderRecentOrders(orders) {
  const tbody = document.getElementById('recent-orders-body');
  tbody.innerHTML = orders.map(o => `
    <tr class="clickable" onclick="app.showDetail('${o.order_id}')">
      <td>${formatTime(o.timestamp)}</td>
      <td><strong>${o.order_id}</strong></td>
      <td><span class="badge badge-info">${o.data_type}</span></td>
      <td>${o.file_count}</td>
      <td>${statusBadge(o.status)}</td>
    </tr>
  `).join('');
}

function renderAllOrders(orders) {
  const tbody = document.getElementById('all-orders-body');
  tbody.innerHTML = orders.map(o => `
    <tr class="clickable" onclick="app.showDetail('${o.order_id}')">
      <td>${formatTime(o.timestamp)}</td>
      <td><strong>${o.order_id}</strong></td>
      <td><span class="badge badge-info">${o.data_type}</span></td>
      <td>${o.file_count}</td>
      <td>${o.files_pending}</td>
      <td>${o.files_processed}</td>
      <td>${o.audit_version ?? '-'}</td>
      <td>${statusBadge(o.status)}</td>
    </tr>
  `).join('');
}

function renderEvents(events) {
  const tbody = document.getElementById('events-body');
  tbody.innerHTML = events.map(e => `
    <tr>
      <td>${formatTime(e.timestamp)}</td>
      <td>${eventBadge(e.event_type)}</td>
      <td>${e.order_id || '-'}</td>
      <td><span class="badge ${e.status_code >= 400 ? 'badge-danger' : 'badge-success'}">${e.status_code}</span></td>
      <td>${e.details || e.error_message || '-'}</td>
    </tr>
  `).join('');
}

function renderErrors(errors) {
  const tbody = document.getElementById('errors-body');
  if (!errors.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-secondary);padding:24px;">Keine Fehler in den letzten 7 Tagen</td></tr>';
    return;
  }
  tbody.innerHTML = errors.map(e => `
    <tr>
      <td>${formatTime(e.timestamp)}</td>
      <td>${eventBadge(e.event_type)}</td>
      <td>${e.order_id || '-'}</td>
      <td style="color:var(--danger)">${e.error_message || '-'}</td>
    </tr>
  `).join('');
}

/* ================================================================
   Charts
   ================================================================ */
const chartColors = ['#6366f1', '#3b82f6', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6'];

function renderTypesChart(byType) {
  const ctx = document.getElementById('chart-types');
  const labels = Object.keys(byType);
  const values = Object.values(byType);

  if (typesChart) typesChart.destroy();
  typesChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: chartColors.slice(0, labels.length),
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { position: 'bottom', labels: { color: '#8b8fa3', padding: 16 } },
      },
    },
  });
}

function renderApiChart(metrics) {
  const ctx = document.getElementById('chart-api');
  if (apiChart) apiChart.destroy();

  const datasets = [];
  let idx = 0;
  for (const [label, series] of Object.entries(metrics)) {
    if (!label.includes('invocations')) continue;
    const pairs = series.timestamps.map((t, i) => ({ x: new Date(t), y: series.values[i] }));
    pairs.sort((a, b) => a.x - b.x);
    datasets.push({
      label: label.replace('_invocations', ''),
      data: pairs,
      borderColor: chartColors[idx % chartColors.length],
      backgroundColor: 'transparent',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.3,
    });
    idx++;
  }

  apiChart = new Chart(ctx, {
    type: 'line',
    data: { datasets },
    options: {
      responsive: true,
      interaction: { intersect: false, mode: 'index' },
      scales: {
        x: {
          type: 'timeseries',
          time: { unit: 'day' },
          ticks: { color: '#8b8fa3' },
          grid: { color: 'rgba(46,49,64,0.5)' },
        },
        y: {
          beginAtZero: true,
          ticks: { color: '#8b8fa3' },
          grid: { color: 'rgba(46,49,64,0.5)' },
        },
      },
      plugins: {
        legend: { position: 'bottom', labels: { color: '#8b8fa3', padding: 12 } },
      },
    },
  });
}

/* ================================================================
   Order Detail
   ================================================================ */
async function showOrderDetail(orderId) {
  const overlay = document.getElementById('order-overlay');
  overlay.classList.add('active');
  document.getElementById('detail-title').textContent = `Auftrag: ${orderId}`;
  document.getElementById('detail-grid').innerHTML = '<div class="loading">Laden...</div>';
  document.getElementById('detail-files').innerHTML = '';
  document.getElementById('detail-events').innerHTML = '';

  try {
    const data = await apiGet(`/admin/api/orders/${encodeURIComponent(orderId)}`);

    document.getElementById('detail-grid').innerHTML = `
      <div class="detail-item"><div class="label">Order-ID</div><div class="val">${data.order_id}</div></div>
      <div class="detail-item"><div class="label">Typ</div><div class="val">${data.data_type}</div></div>
      <div class="detail-item"><div class="label">Zeitpunkt</div><div class="val">${formatTime(data.timestamp)}</div></div>
      <div class="detail-item"><div class="label">Datenmenge</div><div class="val">${formatBytes(data.data_size)}</div></div>
      <div class="detail-item"><div class="label">Audit-Version</div><div class="val">${data.audit_version ?? '-'}</div></div>
      <div class="detail-item"><div class="label">Dateien</div><div class="val">${(data.files || []).length}</div></div>
    `;

    document.getElementById('detail-files').innerHTML = (data.files || []).map(f => `
      <li>
        <span class="dot ${f.status === 'processed' ? 'dot-processed' : 'dot-pending'}"></span>
        <span style="flex:1">${f.key}</span>
        <span class="badge ${f.status === 'processed' ? 'badge-success' : 'badge-warning'}">${f.status === 'processed' ? 'Abgeholt' : 'Offen'}</span>
      </li>
    `).join('');

    const events = data.events || [];
    if (events.length) {
      document.getElementById('detail-events').innerHTML = `
        <table><thead><tr><th>Zeitpunkt</th><th>Event</th><th>Details</th></tr></thead><tbody>
        ${events.map(e => `<tr><td>${formatTime(e.timestamp)}</td><td>${eventBadge(e.event_type)}</td><td>${e.details || e.error_message || '-'}</td></tr>`).join('')}
        </tbody></table>
      `;
    }
  } catch (e) {
    document.getElementById('detail-grid').innerHTML = `<div class="loading" style="color:var(--danger)">Fehler: ${e.message}</div>`;
  }
}

function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) { val /= 1024; i++; }
  return `${val.toFixed(i > 0 ? 1 : 0)} ${units[i]}`;
}

/* ================================================================
   Tab Navigation
   ================================================================ */
document.querySelectorAll('.nav-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
  });
});

/* ================================================================
   App API (exposed for onclick handlers)
   ================================================================ */
const app = {
  refresh: loadAll,
  logout: () => {
    const pool = getPool();
    const user = pool.getCurrentUser();
    if (user) user.signOut();
    idToken = null;
    cognitoUser = null;
    document.getElementById('dashboard-view').style.display = 'none';
    document.getElementById('login-view').style.display = 'flex';
    document.getElementById('login-form').style.display = 'block';
    document.getElementById('new-password-form').style.display = 'none';
  },
  showDetail: showOrderDetail,
  closeDetail: () => {
    document.getElementById('order-overlay').classList.remove('active');
  },
};

/* Close overlay on background click */
document.getElementById('order-overlay').addEventListener('click', (e) => {
  if (e.target === e.currentTarget) app.closeDetail();
});

/* ================================================================
   Init: check for existing session
   ================================================================ */
checkSession();
