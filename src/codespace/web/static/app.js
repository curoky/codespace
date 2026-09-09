const DEFAULT_WORKSPACE = "default";
let pollTimer = null;
let projectHosts = new Map();
let pendingDelete = null;
let pendingLogs = null;

const hostsElement = document.querySelector("#hosts");
const hostsSummaryElement = document.querySelector("#hosts-summary");
const projectsElement = document.querySelector("#projects");
const servicesElement = document.querySelector("#services");
const servicesSummaryElement = document.querySelector("#services-summary");
const pollStatusElement = document.querySelector("#poll-status");
const workspaceDialog = document.querySelector("#workspace-dialog");
const tokensDialog = document.querySelector("#tokens-dialog");
const deleteDialog = document.querySelector("#delete-dialog");
const logsDialog = document.querySelector("#logs-dialog");
const toastElement = document.querySelector("#toast");
const deleteStatusElement = document.querySelector("#delete-status");
const deleteDetailElement = document.querySelector("#delete-detail");
const deleteConfirmButton = document.querySelector("#delete-confirm");
const logsStatusElement = document.querySelector("#logs-status");
const logsOutputElement = document.querySelector("#logs-output");
const logsSourceElement = document.querySelector("#logs-source");

document.querySelector("#refresh-button").addEventListener("click", refresh);
document.querySelector("#tokens-button").addEventListener("click", () => tokensDialog.showModal());
document.querySelector("#workspace-form").addEventListener("submit", createWorkspace);
document.querySelector("#tokens-form").addEventListener("submit", saveTokens);
document.querySelector("#logs-refresh").addEventListener("click", loadLogs);
logsSourceElement.addEventListener("change", () => {
  if (pendingLogs === null) return;
  pendingLogs.source = logsSourceElement.value;
  loadLogs();
});
deleteConfirmButton.addEventListener("click", confirmDelete);
deleteDialog.addEventListener("close", () => {
  pendingDelete = null;
});
logsDialog.addEventListener("close", () => {
  pendingLogs = null;
});
document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => document.querySelector(`#${button.dataset.close}`).close());
});

projectsElement.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const { action, project, workspace, host, command, source, status } = target.dataset;
  if (action === "new") openWorkspaceDialog(project);
  if (action === "quick") await submitWorkspace(project, host, DEFAULT_WORKSPACE);
  if (action === "delete") {
    await deleteWorkspace(project, host, workspace, false, source, status);
  }
  if (action === "purge") {
    await deleteWorkspace(project, host, workspace, true, source, status);
  }
  if (action === "logs") openWorkspaceLogsDialog(project, host, workspace);
  if (action === "dismiss-operation") {
    await dismissWorkspaceOperation(target, project, host, workspace);
  }
  if (action === "copy-ssh") await copySshCommand(target, command);
});

servicesElement.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const { action, service, host } = target.dataset;
  if (action === "apply") await applyService(target, service, host);
  if (action === "remove") await removeService(service, host, false);
  if (action === "purge") await removeService(service, host, true);
  if (action === "logs") openServiceLogsDialog(service, host);
  if (action === "dismiss-operation") {
    await dismissServiceOperation(target, service, host);
  }
});

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    let body = null;
    try {
      body = await response.json();
      message = body.error || message;
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    const error = new Error(message);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return response.json();
}

async function refresh() {
  pollStatusElement.textContent = "Refreshing…";
  try {
    const dashboard = await api("/api/dashboard");
    if (hasActiveSelection()) return;
    render(dashboard);
  } catch (error) {
    notify(error.message);
  } finally {
    pollStatusElement.textContent = "";
  }
}

function render(dashboard) {
  renderHosts(dashboard.hosts);
  renderProjects(dashboard);
  renderServices(dashboard);
  const savedTokens = Object.values(dashboard.tokens).filter(Boolean).length;
  document.querySelector("#tokens-button").textContent = `Tokens ${savedTokens}/2`;
  const busy = dashboard.operations.some((operation) =>
    ["queued", "running"].includes(operation.status),
  );
  if (busy && !pollTimer) {
    pollTimer = window.setInterval(refresh, 1500);
    pollStatusElement.textContent = "Operations running";
  } else if (!busy && pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

const RUNNING_STATES = new Set(["running", "succeeded"]);
const PENDING_STATES = new Set(["queued", "pending", "created", "paused"]);

function classifyStatus(status) {
  if (RUNNING_STATES.has(status)) return "running";
  if (PENDING_STATES.has(status)) return "pending";
  return "stopped";
}

function renderHosts(hosts) {
  const online = hosts.filter((host) => host.status === "online").length;
  hostsSummaryElement.textContent = hosts.length ? `${online}/${hosts.length} online` : "";
  hostsElement.replaceChildren(
    ...hosts.map((host) => {
      const item = element("div", `host ${host.status}`);
      const identity = element("div", "host-identity");
      identity.append(element("span", "status-dot"));
      identity.append(element("strong", "", host.id));
      item.append(identity);
      if (host.status !== "online") item.append(element("span", "host-state", host.status));
      item.append(element("span", "host-count", `${host.workspace_count} workspaces`));
      if (host.error) item.append(element("span", "host-error", host.error));
      return item;
    }),
  );
}

function projectSource(project) {
  const source = project.source;
  if (source.type === "empty") return project.open_path;
  if (source.type === "git") return source.url;
  return `${source.type}:${source.repository}`;
}

function renderProjects(dashboard) {
  projectHosts = new Map(dashboard.projects.map((project) => [project.id, project.hosts]));
  const cards = dashboard.projects.map((project) => {
    const workspaces = dashboard.workspaces.filter((item) => item.project === project.id);
    const operations = dashboard.operations.filter(
      (item) => item.kind === "workspace" && item.project === project.id,
    );
    const card = element("article", "project-card");
    const header = element("div", "project-header");
    const name = element("h3", "", project.id);
    const source = projectSource(project);
    name.title = project.description ? `${source} - ${project.description}` : source;
    const title = element("div", "project-title");
    const sourceLine = element("span", "project-source", source);
    sourceLine.title = name.title;
    title.append(name, sourceLine);

    const headerActions = element("div", "project-header-actions");
    project.hosts.forEach((host) => {
      const platformSuffix = host.platform ? ` · ${host.platform}` : "";
      const quickButton = actionButton(`+ ${host.name}${platformSuffix}`, "quick", {
        project: project.id,
        host: host.name,
      });
      quickButton.classList.remove("secondary");
      quickButton.classList.add("compact", "host-action");
      quickButton.title = `Create "${DEFAULT_WORKSPACE}" Workspace on ${host.name}`;
      headerActions.append(quickButton);
    });
    const createButton = actionButton("New…", "new", { project: project.id });
    createButton.classList.remove("secondary");
    createButton.classList.add("compact", "primary");
    createButton.title = "Create a named Workspace on a chosen Host";
    headerActions.append(createButton);
    header.append(title, headerActions);
    card.append(header);

    const list = element("div", "workspace-list");
    operations.forEach((operation) => {
      list.append(
        renderOperation(operation, operation.resource, {
          project: operation.project,
          workspace: operation.resource,
          host: operation.host,
        }),
      );
    });
    workspaces.forEach((workspace) => list.append(renderWorkspace(workspace)));
    if (!operations.length && !workspaces.length) {
      const empty = element("div", "empty");
      empty.append(element("strong", "", "No Workspaces"));
      empty.append(element("span", "muted", "Pick a Host above to create one."));
      list.append(empty);
    }
    card.append(list);
    return card;
  });
  projectsElement.replaceChildren(...cards);
}

function renderServices(dashboard) {
  const services = dashboard.services;
  const hosts = new Map(dashboard.hosts.map((host) => [host.id, host]));
  const running = services.reduce(
    (total, service) =>
      total + service.hosts.filter((host) => host.container?.status === "running").length,
    0,
  );
  const placements = services.reduce((total, service) => total + service.hosts.length, 0);
  servicesSummaryElement.textContent = placements ? `${running}/${placements} running` : "";

  const cards = services.map((service) => {
    const card = element("article", "project-card");
    const header = element("div", "project-header");
    const title = element("div", "project-title");
    title.append(element("h3", "", service.id));
    header.append(title);
    card.append(header);

    const list = element("div", "workspace-list");
    if (service.hosts.length) {
      service.hosts.forEach((host) => {
        const operation = dashboard.operations.find(
          (item) =>
            item.kind === "service" && item.resource === service.id && item.host === host.host,
        );
        list.append(
          operation
            ? renderOperation(operation, host.host, { service: service.id, host: host.host })
            : renderServiceHost(service, host, hosts.get(host.host)),
        );
      });
    } else {
      const empty = element("div", "empty");
      empty.append(element("strong", "", "No Hosts"));
      list.append(empty);
    }
    card.append(list);
    return card;
  });
  servicesElement.replaceChildren(...cards);
}

function renderServiceHost(service, host, hostStatus) {
  const actual = host.container;
  const status = hostStatus.status === "offline" ? "offline" : actual?.status ?? "missing";
  const state = classifyStatus(status);
  const row = element("div", "workspace");
  const info = element("div", "workspace-info");
  info.append(element("span", `workspace-status-dot ${state}`));
  info.append(element("span", "workspace-title", host.host));
  info.append(element("span", `status-badge ${state}`, status));
  if (actual !== null) {
    const image = element("span", "workspace-image", actual.image);
    image.title = actual.image;
    info.append(image);
  }
  if (hostStatus.error) info.append(element("span", "host-error", hostStatus.error));
  row.append(info);

  const target = { service: service.id, host: host.host };
  const actions = element("div", "workspace-actions");
  const applyButton = actionButton(actual === null ? "Apply" : "Reapply", "apply", target);
  applyButton.title = host.desired_image;
  applyButton.classList.remove("secondary");
  applyButton.classList.add("primary");
  actions.append(applyButton);
  if (actual !== null) {
    actions.append(actionButton("Logs", "logs", target));
    actions.append(actionButton("Remove", "remove", target));
  }
  const purgeButton = actionButton("Purge", "purge", target);
  purgeButton.classList.add("danger");
  actions.append(purgeButton);
  row.append(actions);
  return row;
}

function renderOperation(operation, title, dismissTarget) {
  const row = element("div", `operation ${operation.status}`);
  const heading = element("div", "operation-heading");
  heading.append(element("div", "workspace-title", title));
  const actions = element("div", "operation-heading-actions");
  actions.append(element("span", `status-badge ${operation.status}`, operation.status));
  if (operation.status === "failed") {
    const dismissButton = actionButton("×", "dismiss-operation", dismissTarget);
    dismissButton.classList.add("icon", "operation-dismiss");
    dismissButton.setAttribute("aria-label", "Dismiss failed operation");
    actions.append(dismissButton);
  }
  heading.append(actions);
  row.append(heading);
  row.append(element("div", "workspace-subtitle", operation.stage));
  if (operation.error) row.append(element("p", "host-error", operation.error));
  return row;
}

function renderWorkspace(workspace) {
  const row = element("div", "workspace");
  const info = element("div", "workspace-info");
  info.append(element("span", `workspace-status-dot ${classifyStatus(workspace.status)}`));
  info.append(element("span", "workspace-title", workspace.workspace));
  if (workspace.encrypted) info.append(encryptedWorkspaceIcon());
  info.append(
    element("span", `status-badge ${workspace.status}`, workspace.status),
  );
  info.append(element("span", "badge badge-host", workspace.host));
  if (workspace.platform !== "native") {
    info.append(element("span", "badge badge-platform", workspace.platform));
  }
  const image = element("span", "workspace-image", workspace.image);
  image.title = workspace.image;
  info.append(image);
  row.append(info);

  const target = {
    project: workspace.project,
    workspace: workspace.workspace,
    host: workspace.host,
    source: workspace.source.type,
    status: workspace.status,
  };
  const actions = element("div", "workspace-actions");
  const traeLink = link("Open in Trae", workspace.trae_url);
  traeLink.classList.add("editor-action");
  actions.append(traeLink);
  actions.append(link("Trae CN", workspace.trae_cn_url));
  const sshButton = actionButton("SSH", "copy-ssh", target);
  sshButton.classList.add("ssh-command");
  sshButton.dataset.command = workspace.ssh_command;
  sshButton.title = `Copy ${workspace.ssh_command}`;
  actions.append(sshButton);
  actions.append(actionButton("Logs", "logs", target));
  actions.append(actionButton("Delete", "delete", target));
  const purgeButton = actionButton("Purge", "purge", target);
  purgeButton.classList.add("danger");
  actions.append(purgeButton);
  row.append(actions);
  return row;
}

function encryptedWorkspaceIcon() {
  const namespace = "http://www.w3.org/2000/svg";
  const icon = document.createElementNS(namespace, "svg");
  icon.classList.add("workspace-encryption-icon");
  icon.setAttribute("viewBox", "0 0 24 24");
  icon.setAttribute("role", "img");
  icon.setAttribute("aria-label", "Encrypted Workspace");

  const title = document.createElementNS(namespace, "title");
  title.textContent = "Encrypted Workspace";
  const body = document.createElementNS(namespace, "rect");
  body.setAttribute("width", "18");
  body.setAttribute("height", "12");
  body.setAttribute("x", "3");
  body.setAttribute("y", "10");
  body.setAttribute("rx", "2");
  const shackle = document.createElementNS(namespace, "path");
  shackle.setAttribute("d", "M7 10V7a5 5 0 0 1 10 0v3");
  const keyhole = document.createElementNS(namespace, "circle");
  keyhole.setAttribute("cx", "12");
  keyhole.setAttribute("cy", "16");
  keyhole.setAttribute("r", "1");
  icon.append(title, body, shackle, keyhole);
  return icon;
}

function openWorkspaceDialog(project) {
  document.querySelector("#workspace-project").value = project;
  document.querySelector("#workspace-title").textContent = `New ${project} Workspace`;
  const hostSelect = document.querySelector("#workspace-host");
  const hosts = projectHosts.get(project);
  hostSelect.replaceChildren(
    ...hosts.map((host) => {
      const label = host.platform ? `${host.name} · ${host.platform}` : host.name;
      const option = element("option", "", label);
      option.value = host.name;
      return option;
    }),
  );
  document.querySelector("#workspace-name").value = "";
  workspaceDialog.showModal();
  document.querySelector("#workspace-name").focus();
}

async function createWorkspace(event) {
  event.preventDefault();
  const project = document.querySelector("#workspace-project").value;
  const host = document.querySelector("#workspace-host").value;
  const workspace = document.querySelector("#workspace-name").value;
  if (await submitWorkspace(project, host, workspace)) workspaceDialog.close();
}

async function submitWorkspace(project, host, workspace) {
  try {
    await api(`/api/projects/${encodeURIComponent(project)}/workspaces`, {
      method: "POST",
      body: JSON.stringify({ host, workspace }),
    });
    notify(`Queued ${project}/${workspace} on ${host}`);
    await refresh();
    return true;
  } catch (error) {
    notify(error.message);
    return false;
  }
}

async function dismissWorkspaceOperation(button, project, host, workspace) {
  button.disabled = true;
  try {
    await api(
      `/api/projects/${encodeURIComponent(project)}/hosts/${encodeURIComponent(host)}/operations/${encodeURIComponent(workspace)}`,
      { method: "DELETE" },
    );
    await refresh();
  } catch (error) {
    button.disabled = false;
    notify(error.message);
  }
}

async function applyService(button, service, host) {
  button.disabled = true;
  try {
    await api(
      `/api/services/${encodeURIComponent(service)}/hosts/${encodeURIComponent(host)}/apply`,
      { method: "POST" },
    );
    notify(`Queued ${service} on ${host}`);
    await refresh();
  } catch (error) {
    button.disabled = false;
    notify(error.message);
  }
}

async function removeService(service, host, purge) {
  const scope = purge ? "container and managed data" : "container";
  if (!window.confirm(`Remove ${service} ${scope} on ${host}?`)) return;
  try {
    await api(
      `/api/services/${encodeURIComponent(service)}/hosts/${encodeURIComponent(host)}?purge=${purge}`,
      { method: "DELETE" },
    );
    notify(`Removed ${service} on ${host}`);
    await refresh();
  } catch (error) {
    notify(error.message);
  }
}

async function dismissServiceOperation(button, service, host) {
  button.disabled = true;
  try {
    await api(
      `/api/services/${encodeURIComponent(service)}/hosts/${encodeURIComponent(host)}/operation`,
      { method: "DELETE" },
    );
    await refresh();
  } catch (error) {
    button.disabled = false;
    notify(error.message);
  }
}

async function deleteWorkspace(project, host, workspace, purge, source, status) {
  pendingDelete = { project, host, workspace, purge };
  const scope = purge ? "container and Workspace data" : "container";
  document.querySelector("#delete-eyebrow").textContent = `Delete ${scope}`;
  document.querySelector("#delete-title").textContent = `${host}/${project}/${workspace}`;
  deleteStatusElement.className = "muted";
  deleteStatusElement.textContent = "Checking repository state…";
  deleteDetailElement.hidden = true;
  deleteDetailElement.textContent = "";
  deleteConfirmButton.disabled = true;
  deleteDialog.showModal();

  if (source !== "empty" && status !== "running") {
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = `Container is ${status}; repository state was not inspected. Deleting may lose work.`;
    deleteConfirmButton.disabled = false;
    return;
  }
  try {
    const result = await sendDelete(project, host, workspace, purge, false);
    if (!deleteDialog.open || pendingDelete === null) return;
    const state = result.state;
    const reasons = [];
    if (state.unpushed) reasons.push("unpushed commits");
    if (state.uncommitted) reasons.push("uncommitted changes");
    if (reasons.length) {
      deleteStatusElement.className = "delete-warning";
      deleteStatusElement.textContent = `This repository has ${reasons.join(" and ")}.`;
      deleteDetailElement.textContent = state.detail.join("\n");
      deleteDetailElement.hidden = false;
    } else {
      deleteStatusElement.textContent = "No unpushed or uncommitted work detected.";
    }
    deleteConfirmButton.disabled = false;
  } catch (error) {
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = `Could not inspect repository state: ${error.message}.`;
    deleteConfirmButton.disabled = false;
  }
}

async function confirmDelete() {
  if (pendingDelete === null) return;
  const { project, host, workspace, purge } = pendingDelete;
  deleteConfirmButton.disabled = true;
  try {
    await sendDelete(project, host, workspace, purge, true);
    deleteDialog.close();
    notify(`Deleted ${project}/${workspace} on ${host}`);
    await refresh();
  } catch (error) {
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = error.message;
    deleteConfirmButton.disabled = false;
  }
}

function sendDelete(project, host, workspace, purge, force) {
  return api(
    `/api/projects/${encodeURIComponent(project)}/hosts/${encodeURIComponent(host)}/workspaces/${encodeURIComponent(workspace)}?purge=${purge}&force=${force}`,
    { method: "DELETE" },
  );
}

function openWorkspaceLogsDialog(project, host, workspace) {
  showLogsDialog(
    `${host}/${project}/${workspace}`,
    `/api/projects/${encodeURIComponent(project)}/hosts/${encodeURIComponent(host)}/workspaces/${encodeURIComponent(workspace)}/logs`,
  );
}

function openServiceLogsDialog(service, host) {
  showLogsDialog(
    `${host}/${service}`,
    `/api/services/${encodeURIComponent(service)}/hosts/${encodeURIComponent(host)}/logs`,
  );
}

function showLogsDialog(title, path) {
  pendingLogs = { title, path, source: "container" };
  document.querySelector("#logs-title").textContent = title;
  renderLogSources(["container"], "container");
  logsDialog.showModal();
  loadLogs();
}

async function loadLogs() {
  if (pendingLogs === null) return;
  const request = pendingLogs;
  const source = request.source;
  logsStatusElement.className = "muted";
  logsStatusElement.textContent = "Loading logs…";
  logsStatusElement.hidden = false;
  logsOutputElement.hidden = true;
  try {
    const result = await api(
      `${request.path}?source=${encodeURIComponent(source)}`,
    );
    if (pendingLogs !== request || request.source !== source || !logsDialog.open) return;
    renderLogSources(result.sources, result.source);
    const logs = result.logs;
    if (logs.trim()) {
      logsStatusElement.hidden = true;
      logsOutputElement.textContent = logs;
      logsOutputElement.hidden = false;
      logsOutputElement.scrollTop = logsOutputElement.scrollHeight;
    } else {
      logsStatusElement.textContent = "No logs available.";
    }
  } catch (error) {
    if (pendingLogs !== request || request.source !== source || !logsDialog.open) return;
    logsStatusElement.className = "delete-warning";
    logsStatusElement.textContent = error.message;
  }
}

function renderLogSources(sources, selected) {
  logsSourceElement.replaceChildren(
    ...sources.map((source) => {
      const option = document.createElement("option");
      option.value = source;
      option.textContent = source === "container" ? "Container" : source;
      return option;
    }),
  );
  logsSourceElement.value = selected;
  logsSourceElement.disabled = sources.length === 1;
}

async function saveTokens(event) {
  event.preventDefault();
  const supplied = [
    ["github", document.querySelector("#github-token").value],
    ["gitlab", document.querySelector("#gitlab-token").value],
  ].filter(([, token]) => token.trim());
  if (!supplied.length) {
    notify("Enter at least one token.");
    return;
  }
  try {
    await Promise.all(
      supplied.map(([provider, token]) =>
        api(`/api/providers/${provider}/token`, {
          method: "PUT",
          body: JSON.stringify({ token }),
        }),
      ),
    );
    document.querySelector("#github-token").value = "";
    document.querySelector("#gitlab-token").value = "";
    tokensDialog.close();
    notify("Token status updated.");
    await refresh();
  } catch (error) {
    notify(error.message);
  }
}

function hasActiveSelection() {
  const selection = window.getSelection();
  return Boolean(selection && !selection.isCollapsed && selection.toString().trim());
}

async function copySshCommand(button, command) {
  if (!navigator.clipboard) {
    notify("Clipboard API is unavailable.");
    return;
  }
  try {
    await navigator.clipboard.writeText(command);
    button.classList.add("copied");
    button.textContent = "Copied";
    window.setTimeout(() => {
      if (!button.isConnected) return;
      button.classList.remove("copied");
      button.textContent = "SSH";
    }, 2000);
  } catch (error) {
    notify(`Copy failed: ${error.message}`);
  }
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function actionButton(label, action, dataset = {}) {
  const button = element("button", "secondary", label);
  button.type = "button";
  Object.assign(button.dataset, { action, ...dataset });
  return button;
}

function link(label, href) {
  const anchor = element("a", "button-link secondary", label);
  anchor.href = href;
  return anchor;
}

let toastTimer;
function notify(message) {
  toastElement.textContent = message;
  toastElement.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toastElement.classList.remove("visible"), 3500);
}

refresh();
