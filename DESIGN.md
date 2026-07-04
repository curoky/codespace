# DESIGN.md

High-level design of `devspace` — a personal, opinionated development environment delivered as portable dotfiles, container images, and host bootstrap scripts.

> **Maintenance rule**: Any code change that affects the architecture, directory layout, build/release flow, or cross-component contracts described below MUST be reflected in this file in the same change. Treat DESIGN.md as the single source of truth for "how the pieces fit together".

## 1. Goals

- Reproducible developer environment across **macOS host**, **Linux host**, **Windows host**, and **containers** (Docker / devcontainer).
- Single repository owns **configuration** (dotfiles), **packaging** (images), **toolchain builders** (deps), and **host setup** (host).
- Configuration is **declarative and idempotent**: setup scripts can be re-run safely.
- Heavy toolchains (CUDA, GCC, LLVM, TensorFlow, PyTorch, Python) are built **out-of-band** as separate images and consumed downstream.

## 2. Top-level layout

| Path | Responsibility |
| --- | --- |
| [dotfiles/](file:///workspace/devspace/dotfiles) | Per-tool configuration files (zsh, git, ssh, vscode, tmux, …) and a single dispatcher [setup.sh](file:///workspace/devspace/dotfiles/setup.sh). |
| [host/](file:///workspace/devspace/host) | Per-OS bootstrap scripts ([darwin](file:///workspace/devspace/host/darwin/bootstrap.sh), [linux](file:///workspace/devspace/host/linux/bootstrap.sh), [win](file:///workspace/devspace/host/win/bootstrap.sh)) plus host-only assets (Brewfiles, conda lockfiles). |
| [images/](file:///workspace/devspace/images) | Dockerfiles that produce the published `ghcr.io/curoky/devspace:*` images. [base/](file:///workspace/devspace/images/base) is the foundation; [gcc/](file:///workspace/devspace/images/gcc), [gui/](file:///workspace/devspace/images/gui), [pytorch/](file:///workspace/devspace/images/pytorch), [tensorflow/](file:///workspace/devspace/images/tensorflow), [iso/](file:///workspace/devspace/images/iso) extend it. |
| [deps/](file:///workspace/devspace/deps) | Independent builders for upstream dependencies (CUDA, GCC, LLVM, Python, TensorFlow, host-tools, tabby). Each subdir owns its `Dockerfile` / `Taskfile.yaml` / `build.sh`. |
| [tools/](file:///workspace/devspace/tools) | Repo-local helper scripts used by CI, hooks, and ad-hoc maintenance (license headers, git history rewrites, GitHub Actions disk cleanup, …). |
| [codespace/](file:///workspace/devspace/codespace) | Codespace agent/client implementation plus the local Web GUI source and built static assets. |
| [.github/workflows/](file:///workspace/devspace/.github/workflows) | CI: image build matrix, ISO build, dependency rebuilds, registry cleanup. |
| [.devcontainer/devcontainer.json](file:///workspace/devspace/.devcontainer/devcontainer.json) | Consumer entry: pulls the published base image. |
| [pyproject.toml](file:///workspace/devspace/pyproject.toml), [uv.lock](file:///workspace/devspace/uv.lock) | Repo Python tooling (uv-managed); declares lint config (ruff/yapf/black) and CLI deps (typer). |
| [lefthook.yml](file:///workspace/devspace/lefthook.yml) | Pre-commit / commit-msg hooks (shfmt, ruff, clang-format, author check). |

## 3. Component design

### 3.1 dotfiles

- **Source of truth** for all user-level configuration. Everything else links into it.
- [dotfiles/setup.sh](file:///workspace/devspace/dotfiles/setup.sh) is the dispatcher with two helpers:
  - `link_path` — symlink (preferred for editable configs).
  - `copy_path` — copy with `0600` perms (used for `.zshrc`, `.gitconfig`, `~/.ssh/config`).
- Dispatch is parameterized by `(SCENE, CONF_PATH)`:
  - `SCENE ∈ {docker, host-linux}` controls Linux-only branches.
  - `OS_NAME == Darwin` triggers macOS-only links (VSCode, Trae, Snipaste).
- Subfolders are grouped by tool. Notable groups:
  - [zsh/](file:///workspace/devspace/dotfiles/zsh) — modular shell init under `lib/` (numbered prefix = load order).
  - [vscode/](file:///workspace/devspace/dotfiles/vscode) — `app/` for desktop, `remote-server-settings.json` for SSH/devcontainer.
  - [s6/](file:///workspace/devspace/dotfiles/s6) — service definitions (`sshd`, `ollama`) consumed by base image entrypoint.
  - [archive/](file:///workspace/devspace/dotfiles/archive) — frozen / rarely-used configs kept for reference; not wired into `setup.sh` by default.

### 3.2 Container images

Three layers:

1. **base** — [images/base/Dockerfile](file:///workspace/devspace/images/base/Dockerfile)
   - Multi-stage build:
     - `stage_sbt` — produces a static-binary toolset under `/opt/sbt`.
     - `stage_conda` — bakes a Miniconda install.
     - `main` — final image, layered as: apt patch → user `x` (uid 5230) → static tools → nix → rust → java → node → go → python (uv) → conda → dotfiles linked from `/opt/devspace` → s6 init generated from the static s6 binaries.
   - Entrypoint: [/etc/s6/init/bin/init](file:///workspace/devspace/images/base/script/setup-s6.sh) — a self-hosted s6 init built by [setup-s6.sh](file:///workspace/devspace/images/base/script/setup-s6.sh) from the s6/execline binaries under `/opt/sbt/store` (no s6-overlay); services declared in dotfiles.
   - Runs `dotfiles/setup.sh docker` twice (once as `x`, once as `root`) so both users get a consistent home.
2. **dist** — [images/gcc](file:///workspace/devspace/images/gcc), [images/gui](file:///workspace/devspace/images/gui), [images/pytorch](file:///workspace/devspace/images/pytorch), [images/tensorflow](file:///workspace/devspace/images/tensorflow), [images/iso](file:///workspace/devspace/images/iso): downstream specializations layered on top of base.
3. **deps** — [deps/](file:///workspace/devspace/deps): standalone builders that emit tarballs/images consumed by `dist` (or by external users). Each has its own `Taskfile.yaml` so it can be invoked independently of the main release pipeline.

### 3.3 Host bootstrap

- [host/darwin/bootstrap.sh](file:///workspace/devspace/host/darwin/bootstrap.sh) — installs Homebrew, links `~/devspace`, runs `dotfiles/setup.sh`, then `brew bundle` from `host/darwin/conf/brew/Brewfile.*`.
- [host/linux/bootstrap.sh](file:///workspace/devspace/host/linux/bootstrap.sh), [host/linux/vultr-bootstrap.sh](file:///workspace/devspace/host/linux/vultr-bootstrap.sh) — Linux host (incl. VPS) variants.
- [host/win/bootstrap.sh](file:///workspace/devspace/host/win/bootstrap.sh) — Windows (WSL/MSYS) variant.
- Host-only assets (Brewfiles with lockfiles, conda env yamls) live next to their bootstrap script — they are **not** part of the container build.

### 3.4 CI / Release

- [build-image.yaml](file:///workspace/devspace/.github/workflows/build-image.yaml) — matrix-builds `base` across Debian/Ubuntu bases, then `dist` images. Uses `ghcr.io/curoky/devspace-cache:*` for buildx cache.
- [build-iso.yaml](file:///workspace/devspace/.github/workflows/build-iso.yaml) — produces the live ISO via `images/iso`.
- [deps-*.yaml](file:///workspace/devspace/.github/workflows) — independently rebuild upstream toolchains; outputs are consumed by `images/*` via `COPY --from=…` or pre-staged tarballs.
- [cleanup.yaml](file:///workspace/devspace/.github/workflows/cleanup.yaml) — prunes old GHCR tags.
- Triggers: push (path-filtered), `workflow_dispatch` (with `disable_docker_cache`), weekly cron.

### 3.5 Repo tooling

- [lefthook.yml](file:///workspace/devspace/lefthook.yml) — `pre-commit` formats shell/python/c++/protobuf; `commit-msg` enforces author identity via [tools/check-author.sh](file:///workspace/devspace/tools/check-author.sh).
- [pyproject.toml](file:///workspace/devspace/pyproject.toml) — ruff (line 100, py311 target), yapf (google), black; `typer` is the only runtime dep (used by ad-hoc scripts under `tools/`).
- [codespace/client/webui/package.json](file:///workspace/devspace/codespace/client/webui/package.json), [codespace/client/webui/pnpm-lock.yaml](file:///workspace/devspace/codespace/client/webui/pnpm-lock.yaml), [codespace/client/webui/vite.config.ts](file:///workspace/devspace/codespace/client/webui/vite.config.ts), [codespace/client/webui/tsconfig.json](file:///workspace/devspace/codespace/client/webui/tsconfig.json) — pnpm-managed Vite / TypeScript toolchain for the local codespace Web GUI; `pnpm --dir codespace/client/webui build` writes static assets to `codespace/client/static/`.
- [.dockerignore](file:///workspace/devspace/.dockerignore), [.gitignore](file:///workspace/devspace/.gitignore) — keep build context lean.

### 3.6 Codespace

- [codespace/agent/](file:///workspace/devspace/codespace/agent) — FastAPI agent and Podman orchestration that runs on the Linux host with access to the rootful Podman socket.
- [codespace/client/](file:///workspace/devspace/codespace/client) — Typer CLI, local Web GUI server, GitHub deploy-key orchestration, and local SSH config management.
- [codespace/client/webui/](file:///workspace/devspace/codespace/client/webui) — React / TypeScript / Mantine frontend source for the local Web GUI. This is intentionally co-located under `codespace/` instead of the repository root so codespace-specific code stays in one tree.
- [codespace/client/static/](file:///workspace/devspace/codespace/client/static) — built frontend assets served by `codespace.client.web`; never edit these by hand, rebuild them from `codespace/client/webui/`.
- Web GUI frontend commands are run with an explicit directory, for example `pnpm --dir codespace/client/webui typecheck` and `pnpm --dir codespace/client/webui build`.

## 4. Cross-component contracts

These are the load-bearing assumptions; touching them requires updating both sides **and** this section.

1. **User identity in containers**: user `x` with uid/gid `5230:5230`. Hard-coded in [images/base/Dockerfile](file:///workspace/devspace/images/base/Dockerfile) and [setup-user.sh](file:///workspace/devspace/images/base/script/setup-user.sh); referenced by every `COPY --chown=…`.
2. **Repo mount path inside container**: `/opt/devspace`, with `~/devspace` as a symlink. Dotfiles paths in `setup.sh` resolve relative to `$CONF_PATH` which defaults to `$HOME/devspace/dotfiles`.
3. **Image tag scheme**: `ghcr.io/curoky/devspace:base-<distro><ver>` for base, `ghcr.io/curoky/devspace:<name>` for dist. Cache mirror under `ghcr.io/curoky/devspace-cache:*`.
4. **Service supervision**: containers start via a self-hosted s6 init (no s6-overlay). All s6 config lives in [dotfiles/s6](file:///workspace/devspace/dotfiles/s6) (`s6-rc.d/` service definitions, `skel/` for s6-linux-init) and is copied to `/etc/s6`; [setup-s6.sh](file:///workspace/devspace/images/base/script/setup-s6.sh) then compiles the s6-rc db to `/etc/s6/db` and generates the init at `/etc/s6/init` via `s6-linux-init-maker` (skel `/etc/s6/skel`). New long-running services go under [dotfiles/s6/s6-rc.d](file:///workspace/devspace/dotfiles/s6/s6-rc.d) and must be added to a `user*/contents.d/` bundle. Service `run`/oneshot `up` files are execline scripts; load the container environment with `s6-envdir -Lf -- /run/s6/container_environment` at the top of the run script.
5. **Language conventions**: code and committed docs are English; interactive chat is Chinese.

## 5. Extension recipes

- **Add a new tool config** → drop files under `dotfiles/<tool>/`, add `link_path`/`copy_path` line in [setup.sh](file:///workspace/devspace/dotfiles/setup.sh) under the right scene, update §3.1.
- **Add a new image variant** → create `images/<name>/{Dockerfile,build.sh}`, add a matrix entry in [build-image.yaml](file:///workspace/devspace/.github/workflows/build-image.yaml), update §3.2.
- **Add a new dependency builder** → create `deps/<name>/{Dockerfile,Taskfile.yaml,build.sh}`, add a `deps-<name>.yaml` workflow, update §3.2.
- **Add a host platform** → create `host/<os>/bootstrap.sh` and required conf assets; update §3.3.

## 6. Known caveats

- `dotfiles/archive/` is intentionally not wired into `setup.sh`; do not assume those configs are active.
- `setup.sh` has a `TODO: remove` on the `CONF_PATH` default — keep both call sites in sync until removed.
- Some CI matrix entries are commented out (TF variants, tabby) — they are paused, not deleted.
