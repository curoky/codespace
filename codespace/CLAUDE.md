# Codespace Agent Guide

This file is the source of truth for agents changing `codespace/`. Keep it
synchronized with architecture, directory layout, lifecycle ordering, API
contracts, and host requirements. Committed documentation and code use English.

## Scope

Codespace is a localhost-only, single-process control plane for development
containers on remote rootful Podman hosts. The local Python process forwards
each host's Podman Unix socket through system OpenSSH and calls Podman directly.
Do not add a remote HTTP agent or use the podman-py SSH adapter.

FastAPI serves both the JSON API and the native files in `static/`. GitHub and
GitLab tokens exist only in process memory.

## Layout

| Path | Responsibility |
| --- | --- |
| `app.py`, `__main__.py` | Web application and process entry point. |
| `config.py`, `models.py` | Configuration, identities, and API models. |
| `transport.py`, `runtime.py` | SSH tunnels and Podman primitives. |
| `service.py`, `operations.py` | Orchestration and operation state. |
| `provider.py`, `ssh.py` | Deploy keys and SSH projections. |
| `static/` | Native Web source served by FastAPI. |
| `client/run.sh` | Background launcher for the local control plane. |
| `images/dev/` | Reference development image. |
| `images/sidecar/` | Host shared-service image and launcher. |
| `tests/` | Tests organized by public module behavior. |

Do not recreate `agent/`, the old client Python package, generated Web assets,
or a Node build chain. `client/` contains only the shell launcher.

## Configuration

Read only `~/.config/codespace/config.toml` at process startup. Do not add YAML,
environment overrides, live reload, or fallback configuration sources.

```toml
default_image = "ghcr.io/curoky/devspace:codespace-debian13"
hosts = ["home", "office"]

[projects.devspace]
host = "home"
provider = "github"
repo = "curoky/devspace"
description = "Devspace repository"

[projects.service-api]
host = "office"
provider = "gitlab"
repo = "group/service-api"
image = "registry.example.com/codespace-api:latest"
```

Required top-level fields are `default_image` and `hosts`. Each project requires
`host`, `provider`, and `repo`; `description` and `image` are optional. Reject
unknown fields.

- Project and instance IDs match `^[a-z0-9][a-z0-9-]{0,31}$`.
- Host aliases match `^[a-z0-9][a-z0-9.-]{0,62}$`.
- Hosts are unique and each project references a configured host.
- Project `image` falls back to `default_image`.

## Host Contract

Each host ID is an existing root SSH alias in local `~/.ssh/config`. System
OpenSSH must remain responsible for identity files, jump hosts, and host-key
policy.

Every host provides:

- rootful Podman at `/run/podman/podman.sock`;
- workspace root `/var/lib/codespace`;
- ports `20000-29999` reserved for environment SSH;
- one host-level sidecar container for shared services;
- project images satisfying the development image contract.

The development image contract is:

- user `x` with uid/gid `5230`;
- writable `/workspace`;
- host networking;
- the existing s6 entrypoint, sshd, onceinit, and Atuin client wiring;
- Git and OpenSSH clients.

The sidecar image is `ghcr.io/curoky/devspace:codespace-sidecar`; its fixed
host-local container name is `codespace-sidecar`. It runs s6 and Atuin server
on `127.0.0.1:8002`, with `ATUIN_DB_URI` supplied at creation. Development
containers remain service clients. Keep the sidecar independent from project
and instance resources.

## Resource Identity

An environment uses one deterministic ID as its container name, local SSH
alias, and deploy-key title:

```text
codespace-<host>-<project>-<instance>
```

Its workspace is `/var/lib/codespace/<project>/<instance>`. Its SSH port is
`20000 + int(sha256(environment_id)[:4], 16) % 10000`. Reject a collision with
another managed environment on the same host; do not probe for a different
port.

Podman inventory is authoritative. Environment containers require
`codespace.managed=true` and complete project, instance, repo, provider, image,
and SSH-port labels. Missing, malformed, or unknown-project labels are inventory
errors; do not infer defaults.

Sidecars are host-scoped and have exactly one container instance per host. They
must not reuse the environment identity, workspace, deploy-key, or SSH
projection contracts. Their detailed implementation contract belongs in
`images/sidecar/CLAUDE.md`.

## Transport

Maintain one reusable system SSH process and one Podman client per host:

```text
ssh -N -o ExitOnForwardFailure=yes -o StreamLocalBindUnlink=yes \
  -L <local.sock>:/run/podman/podman.sock <host>
```

Sockets live in a process-private runtime directory with mode `0700`. Rebuild a
host tunnel after its process dies. Close Podman clients and SSH subprocesses
during application shutdown. Dashboard inventory queries run concurrently, and
one offline host must not block other hosts.

## Environment Lifecycle

Creation order is load-bearing:

1. Validate inventory, token, duplicate identity, and SSH port collision.
2. Generate or reuse `~/.ssh/codespace/id_ed25519`.
3. Generate the environment deploy key in memory.
4. Pull the project image.
5. Use the same image as a helper to create and chown the host workspace.
6. Create the labeled host-network container with the fixed runtime parameters.
7. Overwrite Codespace-owned login and repository SSH credentials.
8. Verify an actual SSH login through the generated route.
9. Replace matching provider deploy keys with one read-write key.
10. Preserve an existing Git checkout or clone the configured repository.
11. Atomically regenerate the host SSH projection.

Before deploy-key registration, rollback removes the container and preserves
the workspace. After registration, revoke the key before removing the
container. If revocation fails, stop and retain the labeled container so normal
deletion can retry after token recovery.

Deletion requires the provider token and revokes every matching deploy key
before remote mutation. A missing provider key is idempotent success. With
`purge=false`, remove only the container. With `purge=true`, stop it, use its
labeled image to remove the workspace, then remove the container. Provider
failure must leave container and workspace state unchanged.

## SSH Projection

Add exactly one include to `~/.ssh/config`:

```sshconfig
Include ~/.ssh/codespace/config
```

Codespace fully owns `~/.ssh/codespace/config` and `hosts/*.conf`. Rewrite a
host projection only after successful inventory; preserve its last projection
while offline and remove it when the host leaves TOML.

Each environment entry uses `HostName 127.0.0.1`, its deterministic port, user
`x`, `ProxyJump <host>`, the global login key, and an independent known-hosts
file. Do not parse or merge historical SSH blocks.

## Web Contract

Run with:

```bash
uv run python -m codespace
```

For a detached local process with repository-local logging, run:

```bash
codespace/client/run.sh
```

The application is fixed to one worker on `127.0.0.1:8765`. Keep these APIs
only:

- `GET /api/dashboard`
- `PUT /api/tokens/{provider}`
- `POST /api/projects/{project}/instances`
- `DELETE /api/projects/{project}/instances/{instance}?purge=true|false`

Return errors as `{"error": "..."}`. The Dashboard response is the browser's
only source of truth. Poll only while a create operation is queued or running.
Do not add SSE, operation dismissal, frontend optimistic state, OpenAPI pages,
or separate host and port configuration.

## Security Boundary

- Treat a rootful Podman socket as root access to its host.
- Keep system OpenSSH host-key verification enabled.
- Never return, log, persist, or send provider tokens anywhere except the
  selected Git provider.
- Deploy private keys may exist only in their development container.
- Do not expose the Web application remotely or add multiple workers.
- Shared services in the sidecar must bind only to addresses required by
  host-network clients; they are not public Internet services by default.

## Change Rules

- Preserve unrelated files under `images/dev/`, especially s6, Atuin client,
  Ollama, onceinit, and sshd wiring.
- Put host-shared service assets under `images/sidecar/`, not in project
  lifecycle modules.
- Keep sidecar inventory distinct from environment inventory.
- Never restore the Python HTTP agent, Podman socket mount, or workspace mount
  in the sidecar image.
- Keep `client/` limited to the local launcher; application code remains in the
  flat `codespace` package.
- Update this file and `images/sidecar/CLAUDE.md` whenever the sidecar naming,
  labels, image, storage, or lifecycle becomes concrete.
- Prefer focused tests beside the affected module; do not restore compatibility
  paths.

## Validation

Run the narrowest relevant checks, then the complete Codespace suite:

```bash
uv run ruff format --check codespace
uv run ruff check codespace
uv run mypy codespace
uv run pytest codespace/tests
uv lock --check
```
