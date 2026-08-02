# Codespace Agent Guide

This file is the source of truth for agents changing `codespace/`. Keep it
synchronized with architecture, directory layout, lifecycle ordering, API
contracts, and host requirements. Committed documentation and code use English.

## Scope

Codespace is a localhost-only, single-process control plane for development
containers on remote rootful Podman hosts. The local Python process forwards
each host's Podman Unix socket through system OpenSSH and calls Podman directly.
Do not add a remote HTTP agent or use the podman-py SSH adapter.

FastAPI serves both the JSON API and the native files in `client/static/`.
GitHub and GitLab tokens live in process memory; the optional `[tokens]` table
in `config.toml` seeds them at startup and the Web UI overrides them at runtime.

## Layout

| Path | Responsibility |
| --- | --- |
| `client/` | Complete local control-plane Python package and launcher. |
| `client/app.py`, `client/__main__.py` | Web application and entry point. |
| `client/config.py`, `client/models.py` | Configuration and API models. |
| `client/transport.py`, `client/runtime.py` | SSH and Podman primitives. |
| `client/service.py`, `client/operations.py` | Orchestration and operations. |
| `client/provider.py`, `client/ssh.py` | Deploy keys and SSH projections. |
| `client/static/` | Native Web source served by FastAPI. |
| `client/tests/` | Tests organized by public module behavior. |
| `client/run.sh` | Detached launcher for the local control plane. |
| `images/dev/` | Reference development image. |
| `images/sidecar/` | Host shared-service image and launcher. |

Do not recreate `agent/`, top-level client modules, generated Web assets, or a
Node build chain. All local control-plane code belongs in `client/`.

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
platform = "linux/arm64"

[host_options.office]
podman_socket = "/tmp/podmanxd.sock"

[tokens]
github = "ghp_xxx"
gitlab = "glpat-xxx"
```

Required top-level fields are `default_image` and `hosts`. Each project requires
`host`, `provider`, and `repo`; `description` and `image` are optional. The
optional `platform` is `linux/amd64` or `linux/arm64`; when omitted, Podman
selects the host-native image platform. The
optional `host_options.<host>` table overrides per-host settings; its only field
is `podman_socket` (absolute remote path, default `/run/podman/podman.sock`).
The optional `[tokens]` table seeds provider tokens at startup; `github` and
`gitlab` are each optional non-blank strings. Reject unknown fields.

- Project and instance IDs match `^[a-z0-9][a-z0-9-]{0,31}$`.
- Host aliases match `^[a-z0-9][a-z0-9.-]{0,62}$`.
- Hosts are unique and each project references a configured host.
- Every `host_options` key references a configured host.
- Project `image` falls back to `default_image`.

## Host Contract

Each host ID is an existing root SSH alias in local `~/.ssh/config`. System
OpenSSH must remain responsible for identity files, jump hosts, and host-key
policy.

Every host provides:

- rootful Podman at `/run/podman/podman.sock`, or another absolute socket path
  declared through `host_options.<host>.podman_socket`;
- a writable home for the SSH login user; the workspace root is `~/codespace2`
  (resolved to the login user's absolute `$HOME` per host and created on first
  use, since a Podman bind-mount source cannot contain `~`);
- ports `20000-29999` reserved for environment SSH;
- one host-level sidecar container for shared services;
- project images satisfying the development image contract.

Running a non-native project platform requires the host kernel to register the
corresponding persistent `binfmt_misc` interpreter, normally QEMU user-static.
Codespace selects the image platform but does not install or manage host
emulation.

The development image contract is:

- user `x` with uid/gid `5230`;
- writable `/workspace`;
- host networking, with environment sshd bound only to `127.0.0.1`;
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

Its workspace is `<login-home>/codespace2/<project>/<instance>` on the host,
bind-mounted at `/workspace` inside the container. Its SSH port is
`20000 + int(sha256(environment_id)[:4], 16) % 10000`. Reject a collision with
another managed environment on the same host; do not probe for a different
port.

Podman inventory is authoritative. Environment containers require
`codespace.managed=true` and complete project, instance, repo, provider, image,
platform, and SSH-port labels. The platform label is the configured
`linux/amd64` or `linux/arm64`, or `native` when no platform was selected.
Missing, malformed, or unknown-project labels are inventory errors; do not infer
defaults.

Sidecars are host-scoped and have exactly one container instance per host. They
must not reuse the environment identity, workspace, deploy-key, or SSH
projection contracts. Their detailed implementation contract belongs in
`images/sidecar/CLAUDE.md`.

## Transport

Maintain one reusable system SSH process and one Podman client per host:

```text
ssh -N -o ExitOnForwardFailure=yes -o StreamLocalBindUnlink=yes \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -L <local.sock>:<host podman_socket> <host>
```

The forward target is the host's resolved `podman_socket`
(default `/run/podman/podman.sock`). Sockets live in a process-private runtime
directory with mode `0700`. SSH keepalives make a silently-broken forward exit
on its own, and every Podman client carries a bounded call timeout so a
half-dead tunnel fails fast instead of hanging an operation. Rebuild a host
tunnel after its process dies. Close Podman clients and SSH subprocesses during
application shutdown. Dashboard inventory queries run concurrently, and one
offline host must not block other hosts.

## Environment Lifecycle

Creation order is load-bearing:

1. Validate inventory, token, duplicate identity, and SSH port collision.
2. Generate or reuse `~/.ssh/codespace/id_ed25519`.
3. Generate the environment deploy key in memory.
4. Pull the project image for its configured platform, or the host-native
   platform when omitted.
5. Create the host workspace directory over SSH (`mkdir` as the login user,
   which shares uid/gid 5230 with the container user, so ownership is correct
   without a helper container).
6. Create the labeled host-network container with the fixed runtime parameters.
7. Write Codespace-owned login and repository SSH credentials, merging the
   managed `~/.ssh/config` block so user-added entries survive.
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
uv run python -m codespace.client
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
- Never return, log, or send provider tokens anywhere except the selected Git
  provider. The control plane may read tokens from the local `[tokens]` config
  table but never writes them back; that file holds plaintext secrets, so keep
  it local, permission-restricted, and out of version control.
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
- Keep all local control-plane Python, static, launcher, and test files under
  `client/`; do not add top-level compatibility modules.
- Update this file and `images/sidecar/CLAUDE.md` whenever the sidecar naming,
  labels, image, storage, or lifecycle becomes concrete.
- Prefer focused tests beside the affected module; do not restore compatibility
  paths.

## Validation

Run the narrowest relevant checks, then the complete Codespace suite:

```bash
uv run ruff format --check codespace/client
uv run ruff check codespace/client
uv run mypy codespace/client
uv run pytest codespace/client/tests
uv lock --check
```
