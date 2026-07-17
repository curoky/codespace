---
description: 在本 dev 容器里执行 shell 命令、查找 python/java/nodejs/go/rust/c++ 等工具链，或遇到「command not found」时使用
alwaysApply: true
---

# Dev 容器工具链地图（给 AI Agent）

目标：跑命令前就知道去哪儿找工具，避免 `command not found`。

## 关键：PATH 只在登录/交互 shell 里完整

工具链 PATH 由 zsh dotfiles（`/opt/devspace/dotfiles/zsh/lib/110-path.sh`）拼出，**只在登录/交互 shell 生效**。Agent 执行命令通常是非登录 shell，PATH 只有 `/usr/bin:/bin:...`，`python`/`go`/`node`/`cargo` 等一律找不到。因此二选一（**推荐第 1 种**）：

1. 走登录 shell 补全 PATH：`zsh -lic '<cmd>'`（如 `zsh -lic 'uv run pytest'`）。
2. 直接用下表的绝对路径，最稳。

> 登录 shell PATH 顺序：`/opt/sb/bin` → 系统路径 → `~/.local/bin` → `~/.nix-profile/bin` → `/opt/conda/condabin` → `/opt/rust/cargo/bin` → `~/devspace/tools`。

## 工具链

### Python —— 一律用 `uv`（别直接找 `python`）
- **uv / uvx**：`/opt/sb/bin/uv`。虚拟环境/依赖/跑脚本都用它：`uv venv` / `uv sync` / `uv run <cmd>` / `uv python install`。
- **多版本 CPython**（uv 预装 3.9–3.14）：`/home/x/.local/share/uv/python/cpython-3.<N>-linux-x86_64-gnu/bin/python3`（N=9..14）。
- **conda**：`/opt/conda/condabin/conda`；base(3.13) 的 python 在 `/opt/conda/bin/python3`。仅需 conda 生态时用，普通项目优先 uv。
- **uv tool 全局工具**（`/home/x/.local/bin/`）：已装 `licenseheaders`、`tensorboard`。
- **ruff**（lint+format）：`/opt/sb/bin/ruff`。

### Java —— `java`/`javac` 默认不在 PATH
- **JDK 25**（默认）：bin `/nix/var/nix/profiles/jdk25/bin`，`JAVA_HOME=/nix/var/nix/profiles/jdk25/lib/openjdk`。
- **JDK 8**：bin `/nix/var/nix/profiles/jdk8/bin`，`JAVA_HOME=/nix/var/nix/profiles/jdk8/lib/openjdk`。
- 用前设好 `JAVA_HOME` 并 `export PATH=$JAVA_HOME/bin:$PATH`，或直接用绝对路径。
- **Maven 3.9.x**：`/home/x/.nix-profile/bin/mvn`。XML LSP **lemminx**：`/home/x/.nix-profile/bin/lemminx`。

### Node.js —— Node 24
- **node / npm / npx / corepack**：`/home/x/.nix-profile/bin/`（= `/nix/var/nix/profiles/nodejs-24/bin`）。
- **pnpm / pnpx**（首选包管理器）：`/opt/sb/bin/pnpm`、`/opt/sb/bin/pnpx`。
- **prettier** `/opt/sb/bin/prettier`；**markdownlint-cli2** `/opt/sb/bin/markdownlint-cli2`；**biome** `/opt/sb/bin/biome`。

### Go —— Go 1.26
- **go / gofmt**：`/home/x/.nix-profile/bin/go`（= `/nix/var/nix/profiles/go-1_26/bin`）。
- **周边工具在 sb store，未软链进 PATH，需用绝对路径** `/opt/sb/store/<name>/bin/<name>`：`gopls`、`golangci-lint`、`gofumpt`、`gotests`、`gomodifytags`、`go-outline`、`impl`、`dlv`(delve)。
- **go-task**（`task`）：`/opt/sb/bin/task`。

### Rust —— 1.96 stable（固定）
- **rustc / cargo / clippy / rustfmt / rust-analyzer**：`/opt/rust/cargo/bin/`。
- 非登录 shell 必须 export `CARGO_HOME=/opt/rust/cargo`、`RUSTUP_HOME=/opt/rust/rustup`，否则会写只读的 `~/.rustup` 报错。工具链固定，别 `rustup update`（home 只读）。

### C / C++ / 构建系统
- **gcc / g++**（GCC 15）：`/home/x/.nix-profile/bin/gcc`、`.../g++`。基础编译开箱即用；链接第三方 nix 库需手动 `-I`/`-L`。需要 clang 时 `nix-env -iA nixpkgs.clang`。
- **clang-format**：`/opt/sb/store/clang-tools-<18..22>/bin/clang-format`（默认取最高版本；VSCode 指向 18）。`clang-tidy` 未预装。
- **cmake 4.x**（含 `ctest`/`cpack`）`/opt/sb/bin/cmake`；**ninja** `/opt/sb/bin/ninja`。
- **bazel/bazelisk**、`buildifier`、`buildozer`：`/opt/sb/bin/`。
- **protoc**：`/opt/sb/bin/protoc`（另有 `protoc-24.4.0`/`25.9.0`/`28.3.0`）。

### Shell
- **shfmt**：`/opt/sb/bin/shfmt`；**shellcheck** 同在 sb。

## 常驻 CLI（都在 `/opt/sb/bin/`，登录 shell 直接用）
- **VCS**：`git`、`gh`、`git-lfs`、`delta`、`lefthook`、`scalar` 及大量 `git-*`。
- **搜索/浏览**：`rg`、`fd`、`fzf`、`bat`、`eza`/`exa`、`tree`、`yazi`、`jq`。
- **编辑/终端**：`vim`、`tmux`、`zellij`、`starship`、`atuin`。
- **数据/DB**：`sqlite3`、`psql`。
- **诊断**：`gdb`、`strace`、`lsof`、`procs`、`ncdu`/`gdu`、`patchelf`、`cloc`/`scc`。
- **网络/压缩**：`curl`、`wget`、`nc`、`ssh`、`rsync`、`zstd`、`xz`、`zip`/`unzip`、`7za`。

## 装新东西
- 系统级/编译器/运行时 → `nix-env -iA nixpkgs.<pkg>`（装到 `~/.nix-profile/bin`）。
- Python 全局 CLI → `uv tool install <tool>`（装到 `~/.local/bin`）。
- Node 全局工具 → 优先项目内 `pnpm add -D`。
- `apt` 需 `sudo`；`/opt`、`/workspace` 归 uid 5230，`~/.rustup` 等部分目录只读，装前先确认可写。
