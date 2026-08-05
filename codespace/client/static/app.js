const DEFAULT_INSTANCE = "default";
let pollTimer = null;
let projectHosts = new Map();

const hostsElement = document.querySelector("#hosts");
const projectsElement = document.querySelector("#projects");
const pollStatusElement = document.querySelector("#poll-status");
const instanceDialog = document.querySelector("#instance-dialog");
const tokensDialog = document.querySelector("#tokens-dialog");
const deleteDialog = document.querySelector("#delete-dialog");
const toastElement = document.querySelector("#toast");

document.querySelector("#refresh-button").addEventListener("click", refresh);
document.querySelector("#tokens-button").addEventListener("click", () => tokensDialog.showModal());
document.querySelector("#instance-form").addEventListener("submit", createInstance);
document.querySelector("#tokens-form").addEventListener("submit", saveTokens);
document.querySelectorAll("[data-close]").forEach((button) => {
  button.addEventListener("click", () => document.querySelector(`#${button.dataset.close}`).close());
});

projectsElement.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const { action, project, instance, host, command, type, status } = target.dataset;
  if (action === "new") openInstanceDialog(project);
  if (action === "quick") await submitInstance(project, host, DEFAULT_INSTANCE);
  if (action === "delete") await deleteInstance(project, host, instance, false, type, status);
  if (action === "purge") await deleteInstance(project, host, instance, true, type, status);
  if (action === "copy-ssh") await copySshCommand(target, command);
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
  renderProjects(dashboard);
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

function renderHosts(hosts) {
  hostsElement.replaceChildren(
    ...hosts.map((host) => {
      const item = element("div", `host ${host.status}`);
      if (host.inventory_errors.length) item.classList.add("inventory-error");

      const identity = element("div", "host-identity");
      identity.append(element("span", "status-dot"));
      identity.append(element("strong", "", host.id));
      item.append(identity);
      item.append(element("span", "host-state", host.status));
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

function renderProjects(dashboard) {
  projectHosts = new Map(dashboard.projects.map((project) => [project.id, project.hosts]));
  const cards = dashboard.projects.map((project) => {
    const environments = dashboard.environments.filter((item) => item.project === project.id);
    const operations = dashboard.operations.filter((item) => item.project === project.id);
    const card = element("article", "project-card");

    const header = element("div", "project-header");
    const info = element("div", "project-info");
    const name = element("h3", "", project.id);
    const label = project.repo || project.open_path;
    name.title = project.description ? `${label} — ${project.description}` : label;

    const title = element("div", "project-title");
    const metadata = element("div", "project-meta");
    project.hosts.forEach((host) => {
      const text = host.platform ? `${host.name} · ${host.platform}` : host.name;
      metadata.append(element("span", "badge badge-host", text));
    });
    if (project.provider) {
      metadata.append(element("span", "badge", project.provider));
    }
    metadata.append(element("span", "badge badge-type", project.type));

    const source = element("p", "project-source", project.description || label);
    source.title = label;
    title.append(name, source);

    const headerActions = element("div", "project-header-actions");
    project.hosts.forEach((host) => {
      const quickButton = actionButton(`Quick · ${host.name}`, "quick", {
        project: project.id,
        host: host.name,
      });
      quickButton.classList.add("compact");
      quickButton.title = `Create instance named "${DEFAULT_INSTANCE}" on ${host.name}`;
      headerActions.append(quickButton);
    });
    const createButton = actionButton("New…", "new", { project: project.id });
    createButton.classList.remove("secondary");
    createButton.classList.add("compact", "primary");
    createButton.title = "Create a named instance on a chosen host";
    headerActions.append(createButton);
    const controls = element("div", "project-controls");
    controls.append(metadata, headerActions);
    info.append(title, controls);
    header.append(info);
    card.append(header);

    const list = element("div", "environment-list");
    operations.forEach((operation) => list.append(renderOperation(operation)));
    environments.forEach((environment) => list.append(renderEnvironment(environment)));
    if (!operations.length && !environments.length) {
      const empty = element("div", "empty");
      empty.append(element("strong", "", "No environments"));
      empty.append(element("span", "muted", "Create a default or named instance to get started."));
      list.append(empty);
    }
    card.append(list);
    return card;
  });
  projectsElement.replaceChildren(...cards);
}

function renderOperation(operation) {
  const row = element("div", `operation ${operation.status}`);
  const heading = element("div", "operation-heading");
  heading.append(element("div", "environment-title", operation.instance));
  heading.append(element("span", `status-badge ${operation.status}`, operation.status));
  row.append(heading);
  row.append(element("div", "environment-subtitle", operation.stage));
  if (operation.error) row.append(element("p", "host-error", operation.error));
  return row;
}

function renderEnvironment(environment) {
  const row = element("div", "environment");

  const info = element("div", "environment-info");
  info.append(element("span", "environment-title", environment.instance));
  info.append(
    element(
      "span",
      `status-badge ${environment.status || "unknown"}`,
      environment.status || "unknown",
    ),
  );
  info.append(element("span", "badge badge-host", environment.host));
  info.append(element("span", "badge badge-platform", environment.platform));
  const image = element("span", "environment-image", environment.image);
  image.title = environment.image;
  info.append(image);
  row.append(info);

  const target = {
    project: environment.project,
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

function openInstanceDialog(project) {
  document.querySelector("#instance-project").value = project;
  document.querySelector("#instance-title").textContent = `New ${project} instance`;
  const hostSelect = document.querySelector("#instance-host");
  const hosts = projectHosts.get(project) || [];
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
  const project = document.querySelector("#instance-project").value;
  const host = document.querySelector("#instance-host").value;
  const instance = document.querySelector("#instance-name").value;
  if (await submitInstance(project, host, instance)) instanceDialog.close();
}

async function submitInstance(project, host, instance) {
  try {
    await api(`/api/projects/${encodeURIComponent(project)}/instances`, {
      method: "POST",
      body: JSON.stringify({ host, instance }),
    });
    notify(`Queued ${project}/${instance} on ${host}`);
    await refresh();
    return true;
  } catch (error) {
    notify(error.message);
    return false;
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

async function deleteInstance(project, host, instance, purge, type, status) {
  pendingDelete = { project, host, instance, purge };
  const scope = purge ? "container and workspace" : "container";
  document.querySelector("#delete-eyebrow").textContent = `Delete ${scope}`;
  document.querySelector("#delete-title").textContent = `${host}/${project}/${instance}`;
  deleteStatusElement.className = "muted";
  deleteStatusElement.textContent = "Checking repository state…";
  deleteDetailElement.hidden = true;
  deleteDetailElement.textContent = "";
  deleteConfirmButton.disabled = true;
  deleteDialog.showModal();

  if (type === "repo" && status !== "running") {
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = `Container is ${status}; repository state was not inspected. Deleting may lose unpushed or uncommitted work.`;
    deleteConfirmButton.disabled = false;
    return;
  }

  let result;
  try {
    result = await sendDelete(project, host, instance, purge, false);
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
  const { project, host, instance, purge } = pendingDelete;
  deleteConfirmButton.disabled = true;
  try {
    await sendDelete(project, host, instance, purge, true);
    deleteDialog.close();
    notify(`Deleted ${project}/${instance} on ${host}`);
    await refresh();
  } catch (error) {
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = error.message;
    deleteConfirmButton.disabled = false;
  }
}

function sendDelete(project, host, instance, purge, force) {
  return api(
    `/api/projects/${encodeURIComponent(project)}/hosts/${encodeURIComponent(host)}/instances/${encodeURIComponent(instance)}?purge=${purge}&force=${force}`,
    { method: "DELETE" },
  );
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

function actionButton(
  label,
  action,
  { project, host = "", instance = "", type = "", status = "" },
) {
  const button = element("button", "secondary", label);
  button.type = "button";
  Object.assign(button.dataset, { action, project, host, instance, type, status });
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
