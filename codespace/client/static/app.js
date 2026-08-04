const DEFAULT_INSTANCE = "default";
let pollTimer = null;

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
  const { action, project, instance, command } = target.dataset;
  if (action === "new") openInstanceDialog(project);
  if (action === "quick") await submitInstance(project, DEFAULT_INSTANCE);
  if (action === "delete") await deleteInstance(project, instance, false);
  if (action === "purge") await deleteInstance(project, instance, true);
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
    metadata.append(element("span", "badge badge-host", project.host));
    if (project.provider) {
      metadata.append(element("span", "badge", project.provider));
    }
    metadata.append(element("span", "badge badge-type", project.type));
    title.append(name, metadata);
    info.append(title);

    const source = element("p", "project-source", project.description || label);
    source.title = label;
    info.append(source);

    const quickButton = actionButton("Quick Create", "quick", project.id);
    quickButton.classList.add("compact");
    quickButton.title = `Create instance named "${DEFAULT_INSTANCE}"`;
    const createButton = actionButton("New", "new", project.id);
    createButton.classList.remove("secondary");
    createButton.classList.add("compact", "primary");
    createButton.title = "Create a named instance";
    const headerActions = element("div", "project-header-actions");
    headerActions.append(quickButton, createButton);
    header.append(info, headerActions);
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
  const top = element("div", "environment-top");
  const title = element("div", "environment-info");
  const heading = element("div", "environment-heading");
  heading.append(element("div", "environment-title", environment.instance));
  heading.append(
    element(
      "span",
      `status-badge ${environment.status || "unknown"}`,
      environment.status || "unknown",
    ),
  );
  title.append(heading);
  top.append(title, element("span", "badge badge-platform", environment.platform));
  row.append(top);

  const image = element("div", "environment-image", environment.image);
  image.title = environment.image;
  row.append(image);

  const actions = element("div", "environment-actions");
  const traeLink = link("Open in Trae", environment.trae_url);
  traeLink.classList.add("editor-action");
  actions.append(traeLink);
  actions.append(link("Trae CN", environment.trae_cn_url));
  const sshButton = actionButton(
    "SSH",
    "copy-ssh",
    environment.project,
    environment.instance,
  );
  sshButton.classList.add("ssh-command");
  sshButton.dataset.command = environment.ssh_command;
  sshButton.title = `Copy ${environment.ssh_command}`;
  actions.append(sshButton);
  actions.append(actionButton("Keep workspace", "delete", environment.project, environment.instance));
  const purgeButton = actionButton("Purge", "purge", environment.project, environment.instance);
  purgeButton.classList.add("danger");
  actions.append(purgeButton);
  row.append(actions);
  return row;
}

function openInstanceDialog(project) {
  document.querySelector("#instance-project").value = project;
  document.querySelector("#instance-title").textContent = `New ${project} instance`;
  document.querySelector("#instance-name").value = "";
  instanceDialog.showModal();
  document.querySelector("#instance-name").focus();
}

async function createInstance(event) {
  event.preventDefault();
  const project = document.querySelector("#instance-project").value;
  const instance = document.querySelector("#instance-name").value;
  if (await submitInstance(project, instance)) instanceDialog.close();
}

async function submitInstance(project, instance) {
  try {
    await api(`/api/projects/${encodeURIComponent(project)}/instances`, {
      method: "POST",
      body: JSON.stringify({ instance }),
    });
    notify(`Queued ${project}/${instance}`);
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

async function deleteInstance(project, instance, purge) {
  pendingDelete = { project, instance, purge };
  const scope = purge ? "container and workspace" : "container";
  document.querySelector("#delete-eyebrow").textContent = `Delete ${scope}`;
  document.querySelector("#delete-title").textContent = `${project}/${instance}`;
  deleteStatusElement.className = "muted";
  deleteStatusElement.textContent = "Checking repository state…";
  deleteDetailElement.hidden = true;
  deleteDetailElement.textContent = "";
  deleteConfirmButton.disabled = true;
  deleteDialog.showModal();

  let result;
  try {
    result = await sendDelete(project, instance, purge, false);
  } catch (error) {
    // A failed or unstartable container blocks the git precheck. Surface it as a
    // warning but still allow forced deletion so broken environments stay removable.
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
  const { project, instance, purge } = pendingDelete;
  deleteConfirmButton.disabled = true;
  try {
    await sendDelete(project, instance, purge, true);
    deleteDialog.close();
    notify(`Deleted ${project}/${instance}`);
    await refresh();
  } catch (error) {
    deleteStatusElement.className = "delete-warning";
    deleteStatusElement.textContent = error.message;
    deleteConfirmButton.disabled = false;
  }
}

function sendDelete(project, instance, purge, force) {
  return api(
    `/api/projects/${encodeURIComponent(project)}/instances/${encodeURIComponent(instance)}?purge=${purge}&force=${force}`,
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

function actionButton(label, action, project, instance = "") {
  const button = element("button", "secondary", label);
  button.type = "button";
  Object.assign(button.dataset, { action, project, instance });
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
