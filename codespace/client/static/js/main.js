const state = { config: null, dashboard: { agents: [], codespaces: [], operations: [] }, operations: new Map(), filter: { agent: 'all', search: '' }, error: null };

async function request(path, options = {}) {
  const response = await fetch(path, { headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) }, ...options });
  const body = response.headers.get('content-type')?.includes('application/json') ? await response.json() : {};
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

const escapeHtml = (value) => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const repoName = (repo) => repo.includes('/') ? repo.split('/').at(-1) : repo;
const defaultAlias = (agent, repo, workspace) => agent && repo && workspace ? `${agent}-${repoName(repo)}-${workspace}` : '';

async function loadAll() {
  try {
    state.error = null;
    state.config = await request('/api/config');
    await refreshDashboard();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function refreshDashboard() {
  state.dashboard = await request('/api/dashboard');
  for (const op of state.dashboard.operations || []) state.operations.set(op.id, op);
  render();
  for (const op of state.operations.values()) if (op.status === 'queued' || op.status === 'running') pollOperation(op.id);
}

function render() {
  document.querySelector('#global-error').classList.toggle('hidden', !state.error);
  document.querySelector('#global-error').textContent = state.error || '';
  renderConfig(); renderAgents(); renderFilters(); renderCodespaces(); renderOperations();
}

function renderConfig() {
  const el = document.querySelector('#config-summary');
  if (!state.config) { el.textContent = '加载配置中...'; return; }
  el.textContent = `Default agent: ${state.config.default_agent}; GitHub token: ${state.config.github.has_token ? '已配置' : '未配置'}`;
}

function renderAgents() {
  document.querySelector('#agent-summary').innerHTML = (state.dashboard.agents || []).map((agent) => `<article class="agent-card ${escapeHtml(agent.status)}"><h3>${escapeHtml(agent.name)}</h3><p>${escapeHtml(agent.id)}</p><p>${escapeHtml(agent.agent_url)}</p><p>Status: ${escapeHtml(agent.status)}</p><p>Codespaces: ${agent.codespace_count}</p>${agent.error ? `<p class="error-banner">${escapeHtml(agent.error)}</p>` : ''}</article>`).join('');
}

function renderFilters() {
  const options = ['<option value="all">All</option>', ...(state.dashboard.agents || []).map((a) => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)}</option>`)];
  document.querySelector('#agent-filter').innerHTML = options.join('');
  document.querySelector('#agent-filter').value = state.filter.agent;
}

function renderCodespaces() {
  const search = state.filter.search.toLowerCase();
  const rows = (state.dashboard.codespaces || []).filter((cs) => (state.filter.agent === 'all' || cs.agent_id === state.filter.agent) && (!search || [cs.repo, cs.workspace, cs.alias, cs.id, cs.agent_name].filter(Boolean).some((v) => String(v).toLowerCase().includes(search))));
  document.querySelector('#codespace-empty').classList.toggle('hidden', rows.length > 0);
  document.querySelector('#codespace-tbody').innerHTML = rows.map((cs) => `<tr><td>${escapeHtml(cs.agent_name)}</td><td>${escapeHtml(cs.repo)}</td><td>${escapeHtml(cs.workspace)}</td><td>${escapeHtml(cs.alias || '无本地 alias')}</td><td>${escapeHtml(cs.status || '-')}</td><td><code>${escapeHtml(cs.ssh_command)}</code> <button data-action="copy" data-ssh="${escapeHtml(cs.ssh_command)}">Copy</button></td><td><button data-action="delete" data-agent="${escapeHtml(cs.agent_id)}" data-id="${escapeHtml(cs.id)}" data-repo="${escapeHtml(cs.repo)}">Delete</button> <button data-action="purge" data-agent="${escapeHtml(cs.agent_id)}" data-id="${escapeHtml(cs.id)}" data-repo="${escapeHtml(cs.repo)}">Delete + Purge</button></td></tr>`).join('');
}

function renderOperations() {
  const ops = [...state.operations.values()];
  document.querySelector('#operation-list').innerHTML = ops.length ? ops.map((op) => `<article class="operation-item ${escapeHtml(op.status)}"><strong>${escapeHtml(op.alias)}</strong><p>${escapeHtml(op.status)} — ${escapeHtml(op.stage)}</p>${op.error ? `<p class="error-banner">${escapeHtml(op.error)}</p>` : ''}</article>`).join('') : '<p class="empty">暂无 operation</p>';
}

function openCreate() {
  const cfg = state.config;
  const dialog = document.querySelector('#create-dialog');
  document.querySelector('#create-agent').innerHTML = cfg.agents.map((a) => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)}</option>`).join('');
  document.querySelector('#create-agent').value = cfg.default_agent;
  document.querySelector('#create-workspace').value = cfg.defaults.workspace;
  document.querySelector('#create-image').value = cfg.defaults.image;
  document.querySelector('#create-user').value = cfg.defaults.user;
  document.querySelector('#create-extra-repos').value = cfg.defaults.extra_repos.join('\n');
  updateAlias(); dialog.showModal();
}

function updateAlias() {
  document.querySelector('#create-alias').value = defaultAlias(document.querySelector('#create-agent').value, document.querySelector('#create-repo').value.trim(), document.querySelector('#create-workspace').value.trim());
}

async function submitCreate(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const agent = form.agent.value;
  const payload = { repo: form.repo.value.trim(), workspace: form.workspace.value.trim(), alias: form.alias.value.trim(), image: form.image.value.trim(), user: form.user.value.trim(), extra_repos: form.extra_repos.value.split(/\n|,/).map((x) => x.trim()).filter(Boolean) };
  try {
    const result = await request(`/api/agents/${encodeURIComponent(agent)}/codespaces`, { method: 'POST', body: JSON.stringify(payload) });
    document.querySelector('#create-dialog').close();
    state.operations.set(result.operation_id, { id: result.operation_id, status: 'queued', stage: 'queued', ...payload, agent_id: agent });
    render(); pollOperation(result.operation_id);
  } catch (error) {
    document.querySelector('#create-error').textContent = error.message;
    document.querySelector('#create-error').classList.remove('hidden');
  }
}

async function pollOperation(id) {
  const op = state.operations.get(id);
  if (!op || op._polling) return;
  op._polling = true;
  while (true) {
    const latest = await request(`/api/operations/${encodeURIComponent(id)}`).catch((error) => ({ ...op, status: 'failed', stage: 'polling failed', error: error.message }));
    state.operations.set(id, latest); render();
    if (latest.status === 'succeeded') { await refreshDashboard(); return; }
    if (latest.status === 'failed') return;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

document.querySelector('#refresh-button').addEventListener('click', refreshDashboard);
document.querySelector('#create-button').addEventListener('click', openCreate);
document.querySelector('#create-cancel').addEventListener('click', () => document.querySelector('#create-dialog').close());
document.querySelector('#create-form').addEventListener('submit', submitCreate);
for (const id of ['#create-agent', '#create-repo', '#create-workspace']) document.querySelector(id).addEventListener('input', updateAlias);
document.querySelector('#agent-filter').addEventListener('change', (event) => { state.filter.agent = event.target.value; render(); });
document.querySelector('#search-input').addEventListener('input', (event) => { state.filter.search = event.target.value; render(); });
document.querySelector('#codespace-tbody').addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]'); if (!button) return;
  if (button.dataset.action === 'copy') { await navigator.clipboard.writeText(button.dataset.ssh); return; }
  const purge = button.dataset.action === 'purge';
  if (!confirm(purge ? '确认删除并 purge workspace？' : '确认删除 codespace？')) return;
  await request(`/api/agents/${encodeURIComponent(button.dataset.agent)}/codespaces/${encodeURIComponent(button.dataset.id)}?repo=${encodeURIComponent(button.dataset.repo)}${purge ? '&purge=true' : ''}`, { method: 'DELETE' });
  await refreshDashboard();
});

loadAll();
