const state = {
  config: null,
  dashboard: { agents: [], codespaces: [], operations: [] },
  operations: new Map(),
  filter: { agent: 'all', status: 'all', search: '', sort: 'agent' },
  error: null,
  lastUpdated: null,
  autoRefresh: true,
  autoRefreshTimer: null,
};

const $ = (selector) => document.querySelector(selector);

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...options,
  });
  const body = response.headers.get('content-type')?.includes('application/json') ? await response.json() : {};
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;');
const repoName = (repo) => (repo || '').includes('/') ? repo.split('/').at(-1) : repo;
const defaultAlias = (agent, repo, workspace) => agent && repo && workspace ? `${agent}-${repoName(repo)}-${workspace}` : '';
const isBusyOperation = (op) => op.status === 'queued' || op.status === 'running';
const formatTime = (timestamp) => timestamp ? new Date(timestamp).toLocaleTimeString() : '尚未刷新';
const normalizeStatus = (status) => String(status || 'unknown').toLowerCase();
const tokenSourceLabel = () => state.config?.github?.token_env || 'GITHUB_TOKEN';
const tokenMissingMessage = () => `创建 codespace 需要 GitHub token。请在启动 Web GUI 前设置 ${tokenSourceLabel()}，或在 config.yaml 的 github.token_env 中指定环境变量名。`;

async function loadAll() {
  try {
    state.error = null;
    state.config = await request('/api/config');
    render();
    await refreshDashboard();
    scheduleAutoRefresh();
  } catch (error) {
    state.error = error.message;
    render();
  }
}

async function refreshDashboard() {
  const refreshButton = $('#refresh-button');
  refreshButton.disabled = true;
  refreshButton.classList.add('is-loading');
  try {
    state.error = null;
    state.dashboard = await request('/api/dashboard');
    state.lastUpdated = Date.now();
    for (const op of state.dashboard.operations || []) state.operations.set(op.id, op);
    render();
    for (const op of state.operations.values()) if (isBusyOperation(op)) pollOperation(op.id);
  } catch (error) {
    state.error = error.message;
    render();
  } finally {
    refreshButton.disabled = false;
    refreshButton.classList.remove('is-loading');
  }
}

function scheduleAutoRefresh() {
  if (state.autoRefreshTimer) clearInterval(state.autoRefreshTimer);
  if (!state.autoRefresh) return;
  state.autoRefreshTimer = setInterval(() => refreshDashboard(), 15000);
}

function render() {
  $('#global-error').classList.toggle('d-none', !state.error);
  $('#global-error').textContent = state.error || '';
  renderConfig();
  renderStats();
  renderTokenStatus();
  renderAgents();
  renderTemplates();
  renderQuickTemplates();
  renderFilters();
  renderCodespaces();
  renderOperations();
}

function renderConfig() {
  const el = $('#config-summary');
  if (!state.config) {
    el.textContent = 'Loading...';
    return;
  }
  el.classList.toggle('text-bg-warning', !state.config.github.has_token);
  el.classList.toggle('text-bg-light', state.config.github.has_token);
  el.textContent = `${state.config.default_agent} · ${state.config.github.has_token ? 'token ok' : 'no token'}`;
}

function renderStats() {
  const agents = state.dashboard.agents || [];
  const ops = [...state.operations.values()];
  const codespaceCount = state.dashboard.codespaces?.length || 0;
  const runningOps = ops.filter(isBusyOperation).length;
  $('#stat-codespaces').textContent = codespaceCount;
  $('#stat-online-agents').textContent = agents.filter((agent) => agent.status === 'online').length;
  $('#stat-offline-agents').textContent = agents.filter((agent) => agent.status === 'offline').length;
  $('#stat-running-ops').textContent = runningOps;
  $('#last-updated').textContent = `Last updated: ${formatTime(state.lastUpdated)}`;
}

function renderTokenStatus() {
  const github = state.config?.github;
  const tone = github?.has_token ? 'success' : 'warning';
  const title = github?.has_token ? 'Token ready' : 'Token missing';
  const detail = github?.has_token ? escapeHtml(tokenSourceLabel()) : `set ${escapeHtml(tokenSourceLabel())}`;
  $('#token-status-card').innerHTML = `
    <div class="token-status ${tone}">
      <div>
        <strong>${title}</strong>
        <p class="mb-0 small">${detail}</p>
      </div>
    </div>`;
}

function renderAgents() {
  const agents = state.dashboard.agents || [];
  $('#agent-summary').innerHTML = agents.length ? agents.map((agent) => `
    <article class="agent-card ${escapeHtml(agent.status)}" data-agent="${escapeHtml(agent.id)}">
      <div class="d-flex justify-content-between align-items-start gap-2 mb-3">
        <div>
          <h3 class="h6 mb-1">${escapeHtml(agent.name)}</h3>
        </div>
        <span class="status-pill ${escapeHtml(agent.status)}">
          ${escapeHtml(agent.status)}
        </span>
      </div>
      <div class="agent-meta">
        <span>${escapeHtml(agent.agent_url)}</span>
        <span>${escapeHtml(agent.ssh_host)}</span>
        <span>${agent.codespace_count} codespaces</span>
      </div>
      ${agent.error ? `<div class="alert alert-danger small mt-3 mb-0">${escapeHtml(agent.error)}</div>` : ''}
    </article>`).join('') : '<div class="empty-state"><p class="mb-0">暂无 agent 信息</p></div>';
}

function renderTemplates() {
  const templates = state.config?.templates || [];
  $('#template-list').innerHTML = templates.length ? templates.map((template) => `
    <article class="template-card">
      <div class="d-flex justify-content-between align-items-start gap-2 mb-2">
        <div>
          <h3 class="h6 mb-1">${escapeHtml(template.name)}</h3>
        </div>
        <span class="repo-chip">${escapeHtml(template.repo)}</span>
      </div>
      ${template.description ? `<p class="text-secondary small mb-2">${escapeHtml(template.description)}</p>` : ''}
      <div class="agent-meta mb-3">
        <span>${escapeHtml(template.agent || state.config.default_agent)}</span>
        <span>${escapeHtml(template.workspace || state.config.defaults.workspace)}</span>
        <span>${escapeHtml(template.image || state.config.defaults.image)}</span>
      </div>
      <button class="btn btn-primary btn-sm w-100" data-action="create-template" data-template="${escapeHtml(template.id)}" type="button">
        Create
      </button>
    </article>`).join('') : '<div class="empty-state"><p class="mb-0">暂无模板</p></div>';
}

function renderQuickTemplates() {
  const templates = state.config?.templates || [];
  $('#quick-template-select').innerHTML = [
    '<option value="">选择模板...</option>',
    ...templates.map((template) => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.name)} · ${escapeHtml(template.repo)}</option>`),
  ].join('');
  $('#quick-template-button').disabled = templates.length === 0;
}

function renderFilters() {
  const options = [
    '<option value="all">All agents</option>',
    ...(state.dashboard.agents || []).map((a) => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)}</option>`),
  ];
  $('#agent-filter').innerHTML = options.join('');
  $('#agent-filter').value = state.filter.agent;
  $('#status-filter').value = state.filter.status;
  $('#sort-select').value = state.filter.sort;
  $('#search-input').value = state.filter.search;
  $('#auto-refresh-toggle').checked = state.autoRefresh;
}

function filteredCodespaces() {
  const search = state.filter.search.toLowerCase();
  const rows = (state.dashboard.codespaces || []).filter((cs) => {
    const status = normalizeStatus(cs.status);
    return (state.filter.agent === 'all' || cs.agent_id === state.filter.agent)
      && (state.filter.status === 'all' || status === state.filter.status || (state.filter.status === 'unknown' && !cs.status))
      && (!search || [cs.repo, cs.workspace, cs.alias, cs.id, cs.agent_name, cs.status]
        .filter(Boolean)
        .some((v) => String(v).toLowerCase().includes(search)));
  });
  return rows.sort((left, right) => String(left[state.filter.sort] || left.agent_name || '').localeCompare(String(right[state.filter.sort] || right.agent_name || '')));
}

function renderCodespaces() {
  const rows = filteredCodespaces();
  $('#codespace-count').textContent = rows.length;
  $('#codespace-empty').classList.toggle('d-none', rows.length > 0);
  $('#codespace-card-grid').innerHTML = rows.map((cs) => `
    <article class="codespace-card">
      <div class="d-flex justify-content-between align-items-start gap-2 mb-3">
        <div>
          <p class="text-secondary small mb-1">${escapeHtml(cs.agent_name)} · ${escapeHtml(cs.workspace)}</p>
          <h3 class="h6 mb-0">${escapeHtml(cs.repo)}</h3>
        </div>
        <span class="status-pill ${escapeHtml(normalizeStatus(cs.status))}">${escapeHtml(cs.status || 'unknown')}</span>
      </div>
      <div class="codespace-meta mb-3">
        <span>${escapeHtml(cs.id)}</span>
        <span>${escapeHtml(cs.ssh_host)}:${cs.port}</span>
        <span>${escapeHtml(cs.user)}</span>
      </div>
      <code class="ssh-code w-100 mb-3" title="${escapeHtml(cs.ssh_command)}">${escapeHtml(cs.ssh_command)}</code>
      <div class="d-flex gap-2">
        <button class="btn btn-primary btn-sm flex-fill" data-action="copy" data-ssh="${escapeHtml(cs.ssh_command)}" type="button">
          Copy
        </button>
        <button class="btn btn-outline-danger btn-sm" data-action="delete" data-agent="${escapeHtml(cs.agent_id)}" data-id="${escapeHtml(cs.id)}" data-repo="${escapeHtml(cs.repo)}" type="button">
          Delete
        </button>
        <button class="btn btn-danger btn-sm" data-action="purge" data-agent="${escapeHtml(cs.agent_id)}" data-id="${escapeHtml(cs.id)}" data-repo="${escapeHtml(cs.repo)}" type="button">
          Purge
        </button>
      </div>
    </article>`).join('');
  $('#codespace-tbody').innerHTML = rows.map((cs) => `
    <tr>
      <td>
        <button class="btn btn-link p-0 text-decoration-none" data-action="filter-agent" data-agent="${escapeHtml(cs.agent_id)}">
          ${escapeHtml(cs.agent_name)}
        </button>
        <div class="text-secondary small">${escapeHtml(cs.agent_id)}</div>
      </td>
      <td><span class="repo-chip">${escapeHtml(cs.repo)}</span></td>
      <td>${escapeHtml(cs.workspace)}</td>
      <td>${cs.alias ? `<code>${escapeHtml(cs.alias)}</code>` : '<span class="text-secondary">无本地 alias</span>'}</td>
      <td><span class="status-pill ${escapeHtml(normalizeStatus(cs.status))}">${escapeHtml(cs.status || 'unknown')}</span></td>
      <td>
        <div class="d-flex align-items-center gap-2">
          <code class="ssh-code" title="${escapeHtml(cs.ssh_command)}">${escapeHtml(cs.ssh_command)}</code>
          <button class="btn btn-outline-primary btn-sm" data-action="copy" data-ssh="${escapeHtml(cs.ssh_command)}" title="Copy SSH command">
            Copy
          </button>
        </div>
      </td>
      <td class="text-end">
        <div class="btn-group btn-group-sm">
          <button class="btn btn-outline-danger" data-action="delete" data-agent="${escapeHtml(cs.agent_id)}" data-id="${escapeHtml(cs.id)}" data-repo="${escapeHtml(cs.repo)}">
            Delete
          </button>
          <button class="btn btn-danger" data-action="purge" data-agent="${escapeHtml(cs.agent_id)}" data-id="${escapeHtml(cs.id)}" data-repo="${escapeHtml(cs.repo)}">
            Purge
          </button>
        </div>
      </td>
    </tr>`).join('');
}

async function handleCodespaceAction(button) {
  if (button.dataset.action === 'filter-agent') {
    state.filter.agent = button.dataset.agent;
    render();
    return;
  }
  if (button.dataset.action === 'copy') {
    await navigator.clipboard.writeText(button.dataset.ssh);
    showToast('SSH command copied');
    return;
  }
  const purge = button.dataset.action === 'purge';
  if (!confirm(purge ? '确认删除并 purge workspace？' : '确认删除 codespace？')) return;
  button.disabled = true;
  try {
    const result = await request(`/api/agents/${encodeURIComponent(button.dataset.agent)}/codespaces/${encodeURIComponent(button.dataset.id)}?repo=${encodeURIComponent(button.dataset.repo)}${purge ? '&purge=true' : ''}`, { method: 'DELETE' });
    state.error = result.warning || null;
    showToast(result.warning || 'Codespace deleted', result.warning ? 'warning' : 'success');
    await refreshDashboard();
  } catch (error) {
    state.error = error.message;
    render();
  } finally {
    button.disabled = false;
  }
}

function renderOperations() {
  const ops = [...state.operations.values()].sort((left, right) => right.created_at - left.created_at);
  $('#operation-list').innerHTML = ops.length ? ops.map((op) => `
    <article class="operation-item ${escapeHtml(op.status)}">
      <div class="d-flex justify-content-between align-items-start gap-2">
        <div>
          <strong>${escapeHtml(op.alias)}</strong>
          <p class="text-secondary small mb-2">${escapeHtml(op.repo)} · ${escapeHtml(op.workspace)} · ${escapeHtml(op.agent_id)}</p>
        </div>
        <span class="status-pill ${escapeHtml(op.status)}">${escapeHtml(op.status)}</span>
      </div>
      <div class="progress mb-2" role="progressbar" aria-label="operation progress">
        <div class="progress-bar ${op.status === 'failed' ? 'bg-danger' : op.status === 'succeeded' ? 'bg-success' : 'progress-bar-striped progress-bar-animated'}" style="width: ${operationProgress(op.status)}%"></div>
      </div>
      <p class="mb-0 small">${escapeHtml(op.stage)}</p>
      ${op.error ? `<div class="alert alert-danger small mt-2 mb-0">${escapeHtml(op.error)}</div>` : ''}
    </article>`).join('') : '<div class="empty-state"><p class="mb-0">暂无 operation</p></div>';
}

function operationProgress(status) {
  if (status === 'queued') return 12;
  if (status === 'running') return 58;
  if (status === 'succeeded') return 100;
  if (status === 'failed') return 100;
  return 0;
}

function openCreate() {
  const cfg = state.config;
  if (!cfg) return;
  $('#create-error').classList.add('d-none');
  $('#create-error').textContent = '';
  $('#create-token-warning').classList.toggle('d-none', cfg.github.has_token);
  $('#create-token-warning').textContent = cfg.github.has_token ? '' : tokenMissingMessage();
  $('#create-agent').innerHTML = cfg.agents.map((a) => `<option value="${escapeHtml(a.id)}">${escapeHtml(a.name)}</option>`).join('');
  $('#create-agent').value = state.filter.agent !== 'all' ? state.filter.agent : cfg.default_agent;
  $('#create-workspace').value = cfg.defaults.workspace;
  $('#create-image').value = cfg.defaults.image;
  $('#create-user').value = cfg.defaults.user;
  $('#create-extra-repos').value = cfg.defaults.extra_repos.join('\n');
  $('#create-auto-alias').checked = true;
  updateCreateAgentHelp();
  updateAlias();
  $('#create-dialog').showModal();
}

function updateCreateAgentHelp() {
  const agent = state.config?.agents.find((item) => item.id === $('#create-agent').value);
  $('#create-agent-help').innerHTML = agent ? `${escapeHtml(agent.agent_url)} · ${escapeHtml(agent.ssh_host)}` : '';
}

function updateAlias() {
  if (!$('#create-auto-alias').checked) return;
  $('#create-alias').value = defaultAlias($('#create-agent').value, $('#create-repo').value.trim(), $('#create-workspace').value.trim());
}

function applyTemplate(template) {
  const cfg = state.config;
  $('#create-agent').value = template.agent || cfg.default_agent;
  $('#create-repo').value = template.repo;
  $('#create-workspace').value = template.workspace || cfg.defaults.workspace;
  $('#create-image').value = template.image || cfg.defaults.image;
  $('#create-user').value = template.user || cfg.defaults.user;
  $('#create-extra-repos').value = (template.extra_repos ?? cfg.defaults.extra_repos).join('\n');
  if (template.alias) {
    $('#create-auto-alias').checked = false;
    $('#create-alias').value = template.alias;
  } else {
    $('#create-auto-alias').checked = true;
    updateAlias();
  }
  updateCreateAgentHelp();
}

function openCreateFromTemplate(templateId) {
  const template = state.config?.templates.find((item) => item.id === templateId);
  if (!template) return;
  openCreate();
  applyTemplate(template);
}

async function submitCreate(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submitButton = form.querySelector('button[type="submit"]');
  const agent = form.agent.value;
  const payload = {
    repo: form.repo.value.trim(),
    workspace: form.workspace.value.trim(),
    alias: form.alias.value.trim(),
    image: form.image.value.trim(),
    user: form.user.value.trim(),
    extra_repos: form.extra_repos.value.split(/\n|,/).map((x) => x.trim()).filter(Boolean),
  };
  submitButton.disabled = true;
  try {
    const result = await request(`/api/agents/${encodeURIComponent(agent)}/codespaces`, { method: 'POST', body: JSON.stringify(payload) });
    $('#create-dialog').close();
    state.operations.set(result.operation_id, { id: result.operation_id, status: 'queued', stage: 'queued', ...payload, agent_id: agent, created_at: Date.now() / 1000 });
    showToast(`Create operation started: ${payload.alias}`);
    render();
    pollOperation(result.operation_id);
  } catch (error) {
    $('#create-error').textContent = error.message;
    $('#create-error').classList.remove('d-none');
    showToast(error.message, 'danger');
  } finally {
    submitButton.disabled = false;
  }
}

async function pollOperation(id) {
  const op = state.operations.get(id);
  if (!op || op._polling) return;
  op._polling = true;
  while (true) {
    const latest = await request(`/api/operations/${encodeURIComponent(id)}`).catch((error) => ({ ...op, status: 'failed', stage: 'polling failed', error: error.message }));
    latest._polling = true;
    state.operations.set(id, latest);
    render();
    if (latest.status === 'succeeded') {
      showToast(`Codespace ready: ${latest.alias}`);
      latest._polling = false;
      await refreshDashboard();
      return;
    }
    if (latest.status === 'failed') {
      showToast(`Operation failed: ${latest.alias}`, 'danger');
      latest._polling = false;
      render();
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

function showToast(message, tone = 'success') {
  const toast = document.createElement('div');
  toast.className = `app-toast ${tone}`;
  toast.textContent = message;
  $('#toast-area').append(toast);
  setTimeout(() => toast.remove(), 3500);
}

$('#refresh-button').addEventListener('click', refreshDashboard);
$('#create-button').addEventListener('click', openCreate);
document.querySelectorAll('[data-action="open-create"]').forEach((button) => button.addEventListener('click', openCreate));
$('#create-cancel').addEventListener('click', () => $('#create-dialog').close());
$('#create-cancel-footer').addEventListener('click', () => $('#create-dialog').close());
$('#create-form').addEventListener('submit', submitCreate);
for (const id of ['#create-agent', '#create-repo', '#create-workspace']) {
  $(id).addEventListener('input', () => { updateCreateAgentHelp(); updateAlias(); });
}
$('#create-auto-alias').addEventListener('change', updateAlias);
$('#create-alias').addEventListener('input', () => { $('#create-auto-alias').checked = false; });
$('#template-list').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action="create-template"]');
  if (!button) return;
  openCreateFromTemplate(button.dataset.template);
});
$('#quick-template-button').addEventListener('click', () => {
  const templateId = $('#quick-template-select').value;
  if (templateId) openCreateFromTemplate(templateId);
});
$('#agent-filter').addEventListener('change', (event) => { state.filter.agent = event.target.value; render(); });
$('#status-filter').addEventListener('change', (event) => { state.filter.status = event.target.value; render(); });
$('#sort-select').addEventListener('change', (event) => { state.filter.sort = event.target.value; render(); });
$('#search-input').addEventListener('input', (event) => { state.filter.search = event.target.value; render(); });
$('#clear-search-button').addEventListener('click', () => {
  state.filter = { agent: 'all', status: 'all', search: '', sort: 'agent' };
  render();
});
$('#auto-refresh-toggle').addEventListener('change', (event) => {
  state.autoRefresh = event.target.checked;
  scheduleAutoRefresh();
});
$('#clear-operations-button').addEventListener('click', () => {
  for (const [id, op] of state.operations.entries()) if (!isBusyOperation(op)) state.operations.delete(id);
  render();
});
$('#codespace-card-grid').addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  await handleCodespaceAction(button);
});
$('#codespace-tbody').addEventListener('click', async (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  await handleCodespaceAction(button);
});

loadAll();
