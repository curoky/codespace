const state = { dashboard: null, pollTimer: null };

const hostsElement = document.querySelector("#hosts");
const projectsElement = document.querySelector("#projects");
const pollStatusElement = document.querySelector("#poll-status");
const instanceDialog = document.querySelector("#instance-dialog");
const tokensDialog = document.querySelector("#tokens-dialog");
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
  const { action, project, instance, value } = target.dataset;
  if (action === "new") openInstanceDialog(project);
  if (action === "copy") await copyText(value);
  if (action === "delete") await deleteInstance(project, instance, false);
  if (action === "purge") await deleteInstance(project, instance, true);
});

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      message = (await response.json()).error || message;
    } catch {
      // Keep the status-based fallback.
    }
    throw new Error(message);
  }
  return response.json();
}

async function refresh() {
  pollStatusElement.textContent = "Refreshing…";
  try {
    state.dashboard = await api("/api/dashboard");
    render();
  } catch (error) {
    notify(error.message);
  } finally {
    pollStatusElement.textContent = "";
  }
}

function render() {
  renderHosts(state.dashboard.hosts);
  renderProjects(state.dashboard);
  const savedTokens = Object.values(state.dashboard.tokens).filter(Boolean).length;
  document.querySelector("#tokens-button").textContent = `Tokens ${savedTokens}/2`;
  const busy = state.dashboard.operations.some((operation) =>
    ["queued", "running"].includes(operation.status),
  );
  if (busy && !state.pollTimer) {
    state.pollTimer = window.setInterval(refresh, 1500);
    pollStatusElement.textContent = "Operations running";
  } else if (!busy && state.pollTimer) {
    window.clearInterval(state.pollTimer);
    state.pollTimer = null;
  }
}

function renderHosts(hosts) {
  hostsElement.replaceChildren(
    ...hosts.map((host) => {
      const item = element("div", `host ${host.status}`);
      if (host.inventory_errors.length) item.classList.add("inventory-error");
      item.append(element("span", "status-dot"));
      item.append(element("strong", "", host.id));
      item.append(element("span", "muted", `${host.environment_count} env`));
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
    const info = element("div");
    info.append(element("h3", "", project.id));
    const meta = element("div", "project-meta");
    meta.append(element("span", "badge", project.host));
    meta.append(element("span", "badge", project.provider));
    info.append(meta);
    info.append(element("p", "repo", project.repo));
    if (project.description) info.append(element("p", "description", project.description));
    const createButton = actionButton("New instance", "new", project.id);
    header.append(info, createButton);
    card.append(header);

    const list = element("div", "environment-list");
    operations.forEach((operation) => list.append(renderOperation(operation)));
    environments.forEach((environment) => list.append(renderEnvironment(environment)));
    if (!operations.length && !environments.length) {
      list.append(element("div", "empty muted", "No environments yet."));
    }
    card.append(list);
    return card;
  });
  projectsElement.replaceChildren(...cards);
}

function renderOperation(operation) {
  const row = element("div", `operation ${operation.status}`);
  row.append(element("div", "environment-title", operation.instance));
  row.append(element("div", "environment-subtitle", operation.stage));
  if (operation.error) row.append(element("p", "host-error", operation.error));
  return row;
}

function renderEnvironment(environment) {
  const row = element("div", "environment");
  const top = element("div", "environment-top");
  const title = element("div");
  title.append(element("div", "environment-title", environment.instance));
  title.append(
    element(
      "div",
      "environment-subtitle",
      `${environment.alias} · ${environment.status || "unknown"} · :${environment.ssh_port}`,
    ),
  );
  top.append(title, element("span", "badge", environment.image));
  row.append(top);

  const actions = element("div", "environment-actions");
  actions.append(link("Trae", environment.trae_url));
  actions.append(link("Trae CN", environment.trae_cn_url));
  actions.append(actionButton("Copy SSH", "copy", environment.project, environment.instance, environment.ssh_command));
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
  try {
    await api(`/api/projects/${encodeURIComponent(project)}/instances`, {
      method: "POST",
      body: JSON.stringify({ instance }),
    });
    instanceDialog.close();
    notify(`Queued ${project}/${instance}`);
    await refresh();
  } catch (error) {
    notify(error.message);
  }
}

async function deleteInstance(project, instance, purge) {
  const action = purge ? "delete the container and workspace" : "delete the container";
  if (!window.confirm(`Really ${action} for ${project}/${instance}?`)) return;
  try {
    await api(
      `/api/projects/${encodeURIComponent(project)}/instances/${encodeURIComponent(instance)}?purge=${purge}`,
      { method: "DELETE" },
    );
    notify(`Deleted ${project}/${instance}`);
    await refresh();
  } catch (error) {
    notify(error.message);
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

async function copyText(value) {
  await navigator.clipboard.writeText(value);
  notify(`Copied: ${value}`);
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function actionButton(label, action, project, instance = "", value = "") {
  const button = element("button", "secondary", label);
  button.type = "button";
  Object.assign(button.dataset, { action, project, instance, value });
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
