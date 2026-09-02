const DEFAULT_INSTANCE = "default";
let pollTimer = null;
let workspaceHosts = new Map();

const hostsElement = document.querySelector("#hosts");
const hostsSummaryElement = document.querySelector("#hosts-summary");
const workspacesElement = document.querySelector("#workspaces");
const deploymentsElement = document.querySelector("#deployments");
const deploymentsSummaryElement = document.querySelector("#deployments-summary");
const pollStatusElement = document.querySelector("#poll-status");
const instanceDialog = document.querySelector("#instance-dialog");
const tokensDialog = document.querySelector("#tokens-dialog");
const deleteDialog = document.querySelector("#delete-dialog");
const logsDialog = document.querySelector("#logs-dialog");
const toastElement = document.querySelector("#toast");

document.querySelector("#refresh-button").addEventListener("click", refresh);
document.querySelector("#tokens-button").addEventListener("click", () => tokensDialog.showModal());
document.querySelector("#instance-form").addEventListener("submit", createInstance);
document.querySelector("#tokens-form").addEventListener("submit", saveTokens);
document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => document.querySelector(`#${button.dataset.close}`).close());
});

workspacesElement.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const { action, workspace, instance, host, command, type, status } = target.dataset;
  if (action === "new") openInstanceDialog(workspace);
  if (action === "quick") await submitInstance(workspace, host, DEFAULT_INSTANCE);
  if (action === "delete") await deleteInstance(workspace, host, instance, false, type, status);
  if (action === "purge") await deleteInstance(workspace, host, instance, true, type, status);
  if (action === "logs") openLogsDialog(workspace, host, instance);
  if (action === "dismiss-operation") {
    await dismissFailedOperation(target, workspace, host, instance);
  }
  if (action === "copy-ssh") await copySshCommand(target, command);
});

deploymentsElement.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const { action, deployment, host } = target.dataset;
  if (action === "deploy") await deployDeployment(target, deployment, host);
  if (action === "clean") await cleanDeployment(deployment, host, false);
  if (action === "purge") await cleanDeployment(deployment, host, true);
  if (action === "logs") openDeploymentLogsDialog(deployment, host);
  if (action === "dismiss-operation") {
    await dismissFailedDeploymentOperation(target, deployment, host);
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
      // Keep the status-based fallback.
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
    // Skip the DOM rebuild while the user is selecting text so polling does not
    // clear their selection mid-copy; the next poll re-renders once they finish.
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
  renderWorkspaces(dashboard);
  renderDeployments(dashboard);
  const savedTokens = Object.values(dashboard.tokens).filter(Boolean).length;
  document.querySelector("#tokens-button").textContent = `Tokens ${savedTokens}/2`;
  const deploymentOperations = dashboard.deployments.flatMap((deployment) =>
    deployment.hosts.map((host) => host.operation).filter(Boolean),
  );
  const busy = [...dashboard.operations, ...deploymentOperations].some((operation) =>
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

// Status buckets that drive the per-environment status dot colour.
const RUNNING_STATES = new Set(["running", "succeeded"]);
const PENDING_STATES = new Set(["queued", "pending", "created", "paused"]);

function classifyStatus(status) {
  const value = (status || "unknown").toLowerCase();
  if (RUNNING_STATES.has(value)) return "running";
  if (PENDING_STATES.has(value)) return "pending";
  return "stopped";
}

function renderHosts(hosts) {
  const online = hosts.filter((host) => host.status === "online").length;
  hostsSummaryElement.textContent = hosts.length ? `${online}/${hosts.length} online` : "";
  hostsElement.replaceChildren(
    ...hosts.map((host) => {
      const item = element("div", `host ${host.status}`);
      if (host.inventory_errors.length) item.classList.add("inventory-error");

      const identity = element("div", "host-identity");
      identity.append(element("span", "status-dot"));
      identity.append(element("strong", "", host.id));
      item.append(identity);
      // The colored dot and edge stripe already signal a healthy host, so only
      // spell out the state text when it is worth reading: offline or degraded.
      if (host.status !== "online") {
        item.append(element("span", "host-state", host.status));
      }
      item.append(element("span", "host-count", `${host.environment_count} env`));

      if (host.inventory_errors.length) {
        const label = host.inventory_errors.length === 1 ? "inventory issue" : "inventory issues";
        item.append(element("span", "host-warning", `${host.inventory_errors.length} ${label}`));
      }
      if (host.error) item.append(element("span", "host-error", host.error));
      return item;
    }),
  );
}

// Compose the single-line workspace source, e.g. "github:curoky/devspace". The
// provider and type are implied by this string, so they no longer need tags.
function workspaceSource(workspace) {
  if (workspace.repo) {
    return workspace.provider ? `${workspace.provider}:${workspace.repo}` : workspace.repo;
  }
  return workspace.git_url || workspace.open_path;
}

function renderWorkspaces(dashboard) {
  workspaceHosts = new Map(dashboard.workspaces.map((workspace) => [workspace.id, workspace.hosts]));
  const cards = dashboard.workspaces.map((workspace) => {
    const environments = dashboard.environments.filter((item) => item.workspace === workspace.id);
    const operations = dashboard.operations.filter((item) => item.workspace === workspace.id);
    const card = element("article", "workspace-card");

    const header = element("div", "workspace-header");
    const name = element("h3", "", workspace.id);
    const source = workspaceSource(workspace);
    name.title = workspace.description ? `${source} — ${workspace.description}` : source;

    // The header row carries the workspace identity inline: name then source
    // path; the environments listed below already convey how many exist.
    const title = element("div", "workspace-title");
    const sourceLine = element("span", "workspace-source", source);
    sourceLine.title = workspace.description ? `${source} — ${workspace.description}` : source;
    title.append(name, sourceLine);

    // The host chips double as the "quick create" action: clicking one queues a
    // default instance on that host, so the standalone host tag is redundant.
    const headerActions = element("div", "workspace-header-actions");
    workspace.hosts.forEach((host) => {
      const platformSuffix = host.platform ? ` · ${host.platform}` : "";
      const quickButton = actionButton(`+ ${host.name}${platformSuffix}`, "quick", {
        workspace: workspace.id,
        host: host.name,
      });
      quickButton.classList.remove("secondary");
      quickButton.classList.add("compact", "host-action");
      quickButton.title = `Create "${DEFAULT_INSTANCE}" instance on ${host.name}`;
      headerActions.append(quickButton);
    });
    const createButton = actionButton("New…", "new", { workspace: workspace.id });
    createButton.classList.remove("secondary");
    createButton.classList.add("compact", "primary");
    createButton.title = "Create a named instance on a chosen host";
    headerActions.append(createButton);
    header.append(title, headerActions);
    card.append(header);

    const list = element("div", "environment-list");
    operations.forEach((operation) =>
      list.append(renderOperation(operation, operation.instance, operation)),
    );
    environments.forEach((environment) => list.append(renderEnvironment(environment)));
    if (!operations.length && !environments.length) {
      const empty = element("div", "empty");
      empty.append(element("strong", "", "No environments"));
      empty.append(element("span", "muted", "Pick a host above to create one."));
      list.append(empty);
    }
    card.append(list);
    return card;
  });
  workspacesElement.replaceChildren(...cards);
}

// Deployments mirror the workspace card, but each card is one deployment and its
// rows are the hosts that declared it: a live/stopped/missing host row with
// deploy/clean/purge/logs controls, plus any in-flight operation for that host.
function renderDeployments(dashboard) {
  const deployments = dashboard.deployments || [];
  const running = deployments.reduce(
    (total, deployment) =>
      total + deployment.hosts.filter((host) => host.state === "running").length,
    0,
  );
  const placements = deployments.reduce((total, deployment) => total + deployment.hosts.length, 0);
  deploymentsSummaryElement.textContent = placements ? `${running}/${placements} running` : "";

  const cards = deployments.map((deployment) => {
    const card = element("article", "workspace-card");

    const header = element("div", "workspace-header");
    const title = element("div", "workspace-title");
    title.append(element("h3", "", deployment.id));
    const image = element("span", "workspace-source", deployment.image);
    image.title = deployment.image;
    title.append(image);
    header.append(title);
    card.append(header);

    const list = element("div", "environment-list");
    if (deployment.hosts.length) {
      deployment.hosts.forEach((host) => list.append(renderDeploymentHost(deployment, host)));
    } else {
      const empty = element("div", "empty");
      empty.append(element("strong", "", "No hosts"));
      empty.append(element("span", "muted", "Add this deployment to a host in config."));
      list.append(empty);
    }
    card.append(list);
    return card;
  });
  deploymentsElement.replaceChildren(...cards);
}

function renderDeploymentHost(deployment, host) {
  if (host.operation) {
    return renderOperation(host.operation, host.operation.host, {
      deployment: deployment.id,
      host: host.operation.host,
    });
  }

  const row = element("div", "environment");
  const info = element("div", "environment-info");
  info.append(element("span", `env-status-dot ${host.state}`));
  info.append(element("span", "environment-title", host.host));
  const stateLabel = host.status || host.state;
  info.append(element("span", `status-badge ${host.state}`, stateLabel));
  if (host.error) info.append(element("span", "environment-image", host.error));
  row.append(info);

  const target = { deployment: deployment.id, host: host.host };
  const actions = element("div", "environment-actions");
  const deployLabel = host.state === "missing" ? "Deploy" : "Redeploy";
  const deployButton = actionButton(deployLabel, "deploy", target);
  deployButton.classList.remove("secondary");
  deployButton.classList.add("primary");
  deployButton.title =
    host.state === "missing"
      ? "Pull the image and start the container"
      : "Pull the image and replace the container";
  actions.append(deployButton);
  if (host.state !== "missing") {
    const logsButton = actionButton("Logs", "logs", target);
    logsButton.title = "View recent podman logs";
    actions.append(logsButton);
    const cleanButton = actionButton("Clean", "clean", target);
    cleanButton.title = "Remove the container, keep managed data";
    actions.append(cleanButton);
  }
  const purgeButton = actionButton("Purge", "purge", target);
  purgeButton.classList.add("danger");
  purgeButton.title = "Remove the container and its managed data";
  actions.append(purgeButton);
  row.append(actions);
  return row;
}

// One in-flight operation row, shared by environments and deployments. The
// caller supplies the title (instance or host name) and the dataset used to
// dismiss it, since those differ between the two callers.
function renderOperation(operation, title, dismissTarget) {
  const row = element("div", `operation ${operation.status}`);
  const heading = element("div", "operation-heading");
  heading.append(element("div", "environment-title", title));
  const actions = element("div", "operation-heading-actions");
  actions.append(element("span", `status-badge ${operation.status}`, operation.status));
  if (operation.status === "failed") {
    const dismissButton = actionButton("×", "dismiss-operation", dismissTarget);
    dismissButton.classList.add("icon", "operation-dismiss");
    dismissButton.setAttribute("aria-label", "Dismiss failed operation");
    dismissButton.title = "Dismiss failed operation";
    actions.append(dismissButton);
  }
  heading.append(actions);
  row.append(heading);
  row.append(element("div", "environment-subtitle", operation.stage));
  if (operation.error) row.append(element("p", "host-error", operation.error));
  return row;
}

function renderEnvironment(environment) {
  const row = element("div", "environment");

  const info = element("div", "environment-info");
  info.append(element("span", `env-status-dot ${classifyStatus(environment.status)}`));
  info.append(element("span", "environment-title", environment.instance));
  info.append(
    element(
      "span",
      `status-badge ${environment.status || "unknown"}`,
      environment.status || "unknown",
    ),
  );
  info.append(element("span", "badge badge-host", environment.host));
  if (environment.platform && environment.platform !== "native") {
    info.append(element("span", "badge badge-platform", environment.platform));
  }
  const image = element("span", "environment-image", environment.image);
  image.title = environment.image;
  info.append(image);
  row.append(info);

  const target = {
    workspace: environment.workspace,
    host: environment.host,
    instance: environment.instance,
    type: environment.type,
    status: environment.status || "unknown",
  };
  const actions = element("div", "environment-actions");
  const traeLink = link("Open in Trae", environment.trae_url);
  traeLink.classList.add("editor-action");
  actions.append(traeLink);
  actions.append(link("Trae CN", environment.trae_cn_url));
  const sshButton = actionButton("SSH", "copy-ssh", target);
  sshButton.classList.add("ssh-command");
  sshButton.dataset.command = environment.ssh_command;
  sshButton.title = `Copy ${environment.ssh_command}`;
  actions.append(sshButton);
  const logsButton = actionButton("Logs", "logs", target);
  logsButton.title = "View recent podman logs";
  actions.append(logsButton);
  const deleteButton = actionButton("Delete", "delete", target);
  deleteButton.title = "Delete container, keep workspace files";
  actions.append(deleteButton);
  const purgeButton = actionButton("Purge", "purge", target);
  purgeButton.classList.add("danger");
  purgeButton.title = "Delete container and workspace files";
  actions.append(purgeButton);
  row.append(actions);
  return row;
}

function openInstanceDialog(workspace) {
  document.querySelector("#instance-workspace").value = workspace;
  document.querySelector("#instance-title").textContent = `New ${workspace} instance`;
  const hostSelect = document.querySelector("#instance-host");
  const hosts = workspaceHosts.get(workspace) || [];
  hostSelect.replaceChildren(
    ...hosts.map((host) => {
      const option = element("option", "", host.platform ? `${host.name} · ${host.platform}` : host.name);
      option.value = host.name;
      return option;
    }),
  );
  document.querySelector("#instance-name").value = "";
  instanceDialog.showModal();
  document.querySelector("#instance-name").focus();
}

async function createInstance(event) {
  event.preventDefault();
  const workspace = document.querySelector("#instance-workspace").value;
  const host = document.querySelector("#instance-host").value;
  const instance = document.querySelector("#instance-name").value;
  if (await submitInstance(workspace, host, instance)) instanceDialog.close();
}

async function submitInstance(workspace, host, instance) {
  try {
    await api(`/api/workspaces/${encodeURIComponent(workspace)}/instances`, {
      method: "POST",
      body: JSON.stringify({ host, instance }),
    });
    notify(`Queued ${workspace}/${instance} on ${host}`);
    await refresh();
    return true;
  } catch (error) {
    notify(error.message);
    return false;
  }
}

async function dismissFailedOperation(button, workspace, host, instance) {
  button.disabled = true;
  try {
    await api(
      `/api/workspaces/${encodeURIComponent(workspace)}/hosts/${encodeURIComponent(host)}/operations/${encodeURIComponent(instance)}`,
      { method: "DELETE" },
    );
    await refresh();
  } catch (error) {
    button.disabled = false;
    notify(error.message);
  }
}

async function deployDeployment(button, deployment, host) {
  button.disabled = true;
  try {
    await api(
      `/api/deployments/${encodeURIComponent(deployment)}/hosts/${encodeURIComponent(host)}/deploy`,
      { method: "POST" },
    );
    notify(`Queued ${deployment} on ${host}`);
    await refresh();
  } catch (error) {
    button.disabled = false;
    notify(error.message);
  }
}

async function cleanDeployment(deployment, host, purge) {
  const scope = purge ? "container and managed data" : "container";
  if (!window.confirm(`Remove ${deployment} ${scope} on ${host}?`)) return;
  try {
    await api(
      `/api/deployments/${encodeURIComponent(deployment)}/hosts/${encodeURIComponent(host)}?purge=${purge}`,
      { method: "DELETE" },
    );
    notify(`Cleaned ${deployment} on ${host}`);
    await refresh();
  } catch (error) {
    notify(error.message);
  }
}

async function dismissFailedDeploymentOperation(button, deployment, host) {
  button.disabled = true;
  try {
    await api(
      `/api/deployments/${encodeURIComponent(deployment)}/hosts/${encodeURIComponent(host)}/operations`,
      { method: "DELETE" },
    );
    await refresh();
  } catch (error) {
    button.disabled = false;
    notify(error.message);
  }
}

const deleteStatusElement = document.querySelector("#delete-status");
const deleteDetailElement = document.querySelector("#delete-detail");
const deleteConfirmButton = document.querySelector("#delete-confirm");
deleteConfirmButton.addEventListener("click", confirmDelete);
deleteDialog.addEventListener("close", () => {
  pendingDelete = null;
});

let pendingDelete = null;

async function deleteInstance(workspace, host, instance, purge, type, status) {
  pendingDelete = { workspace, host, instance, purge };
  const scope = purge ? "container and workspace" : "container";
  document.querySelector("#delete-eyebrow").textContent = `Delete ${scope}`;
  document.querySelector("#delete-title").textContent = `${host}/${workspace}/${instance}`;
  deleteStatusElement.className = "muted";
  deleteStatusElement.textContent = "Checking repository state…";
  deleteDetailElement.hidden = true;
  deleteDetailElement.textContent = "";
  deleteConfirmButton.disabled = true;
  deleteDialog.showModal();

  if ((type === "repo" || type === "git") && status !== "running") {
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = `Container is ${status}; repository state was not inspected. Deleting may lose unpushed or uncommitted work.`;
    deleteConfirmButton.disabled = false;
    return;
  }

  let result;
  try {
    result = await sendDelete(workspace, host, instance, purge, false);
  } catch (error) {
    // The container can stop after the dashboard refresh. Keep failed
    // prechecks actionable so broken environments remain removable.
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = `Could not inspect repository state: ${error.message}. Forcing deletion may lose unpushed or uncommitted work.`;
    deleteConfirmButton.disabled = false;
    return;
  }
  if (deleteDialog.open === false || pendingDelete === null) return;

  const state = result.state || {};
  const reasons = [];
  if (state.unpushed) reasons.push("unpushed commits");
  if (state.uncommitted) reasons.push("uncommitted changes");
  if (reasons.length) {
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = `This repository has ${reasons.join(" and ")}. Deleting loses this work.`;
    deleteDetailElement.textContent = (state.detail || []).join("\n");
    deleteDetailElement.hidden = false;
  } else {
    deleteStatusElement.className = "muted";
    deleteStatusElement.textContent = "No unpushed or uncommitted work detected.";
  }
  deleteConfirmButton.disabled = false;
}

async function confirmDelete() {
  if (pendingDelete === null) return;
  const { workspace, host, instance, purge } = pendingDelete;
  deleteConfirmButton.disabled = true;
  try {
    await sendDelete(workspace, host, instance, purge, true);
    deleteDialog.close();
    notify(`Deleted ${workspace}/${instance} on ${host}`);
    await refresh();
  } catch (error) {
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = error.message;
    deleteConfirmButton.disabled = false;
  }
}

function sendDelete(workspace, host, instance, purge, force) {
  return api(
    `/api/workspaces/${encodeURIComponent(workspace)}/hosts/${encodeURIComponent(host)}/instances/${encodeURIComponent(instance)}?purge=${purge}&force=${force}`,
    { method: "DELETE" },
  );
}

const logsStatusElement = document.querySelector("#logs-status");
const logsOutputElement = document.querySelector("#logs-output");
document.querySelector("#logs-refresh").addEventListener("click", loadLogs);
logsDialog.addEventListener("close", () => {
  pendingLogs = null;
});

let pendingLogs = null;

function openLogsDialog(workspace, host, instance) {
  showLogsDialog(
    `${host}/${workspace}/${instance}`,
    `/api/workspaces/${encodeURIComponent(workspace)}/hosts/${encodeURIComponent(host)}/instances/${encodeURIComponent(instance)}/logs`,
  );
}

function openDeploymentLogsDialog(deployment, host) {
  showLogsDialog(
    `${host}/${deployment}`,
    `/api/deployments/${encodeURIComponent(deployment)}/hosts/${encodeURIComponent(host)}/logs`,
  );
}

function showLogsDialog(title, path) {
  pendingLogs = { title, path };
  document.querySelector("#logs-title").textContent = title;
  logsDialog.showModal();
  loadLogs();
}

async function loadLogs() {
  if (pendingLogs === null) return;
  const { path } = pendingLogs;
  logsStatusElement.className = "muted";
  logsStatusElement.textContent = "Loading logs…";
  logsStatusElement.hidden = false;
  logsOutputElement.hidden = true;
  try {
    const result = await api(path);
    if (pendingLogs === null || logsDialog.open === false) return;
    const logs = result.logs || "";
    if (logs.trim()) {
      logsStatusElement.hidden = true;
      logsOutputElement.textContent = logs;
      logsOutputElement.hidden = false;
      logsOutputElement.scrollTop = logsOutputElement.scrollHeight;
    } else {
      logsStatusElement.textContent = "No logs available.";
    }
  } catch (error) {
    logsStatusElement.className = "delete-warning";
    logsStatusElement.textContent = error.message;
  }
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
        api(`/api/tokens/${provider}`, {
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
    button.title = "Copied";
    window.setTimeout(() => {
      if (!button.isConnected) return;
      button.classList.remove("copied");
      button.textContent = "SSH";
      button.title = `Copy ${command}`;
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
