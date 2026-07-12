---
description: 在本 dev 容器里执行 shell 命令、查找 python/java/nodejs/go/rust/c++ 等工具链，或遇到「command not found」时使用
alwaysApply: true
---

# Dev 容器工具链地图（给 AI Agent）

本文件告诉 Agent：这个 dev 容器里各语言工具链装在哪里、怎么调用。**目标是在跑命令前就知道去哪儿找工具，避免 `command not found`。**

## ⚠️ 最重要的一条：PATH 只在登录/交互式 shell 里完整

工具链的 `PATH` 是在 zsh 的 dotfiles（`/opt/devspace/dotfiles/zsh/lib/110-path.sh`）里拼出来的，**只在登录/交互式 shell 生效**。Agent 通过工具执行命令时通常是**非登录、非交互 shell**，此时 `PATH` 只有系统默认的 `/usr/bin:/bin:...`，`python`/`go`/`node`/`cargo` 等**一律找不到**。

因此运行工具链命令时，二选一（**推荐第 1 种**）：

1. **走登录 shell**，让 dotfiles 补全 PATH：
   ```bash
   zsh -lic 'go version'
   zsh -lic 'uv run pytest'
   ```
2. **直接用绝对路径**（见下表），最稳、不依赖 shell 初始化。

> 登录 shell 补全后的 `PATH` 顺序：`/opt/sb/bin` → 系统路径 → `~/.local/bin` → `~/.nix-profile/bin` → `/opt/conda/condabin` → `/opt/rust/cargo/bin` → `~/devspace/tools`。

## 工具链总览：装在哪、怎么调

### Python —— 用 `uv` 管理（首选）
- **uv / uvx**：`/opt/sb/bin/uv`（登录 shell 里直接 `uv`）。管虚拟环境、装依赖、跑脚本一律用它：`uv venv` / `uv sync` / `uv run <cmd>` / `uv python install`。
- **多版本 CPython**（uv 预装 3.9–3.14）：`/home/x/.local/share/uv/python/cpython-3.<N>-linux-x86_64-gnu/bin/python3`（`N` = 9/10/11/12/13/14）。
- **conda**：`conda` 在 `/opt/conda/condabin/conda`；base 环境 Python 3.13 在 `/opt/conda/bin/python3`。需要时 `conda activate <env>`（仅在需要 conda 生态时用，普通项目优先 uv）。
- **uv tool 全局工具**：`/home/x/.local/bin/`，已装 `licenseheaders`、`tensorboard`。
- **ruff**（lint+format）：`/opt/sb/bin/ruff`。

### Java
- **JDK 25**（默认）：bin `/nix/var/nix/profiles/jdk25/bin`，`JAVA_HOME=/nix/var/nix/profiles/jdk25/lib/openjdk`。
- **JDK 8**：bin `/nix/var/nix/profiles/jdk8/bin`，`JAVA_HOME=/nix/var/nix/profiles/jdk8/lib/openjdk`。
- **Maven 3.9.x**：`/home/x/.nix-profile/bin/mvn`。
- ⚠️ `java`/`javac` **默认不在 PATH 上**。要么用绝对路径，要么先设好环境：
  ```bash
  export JAVA_HOME=/nix/var/nix/profiles/jdk25/lib/openjdk
  export PATH=$JAVA_HOME/bin:$PATH
  ```
- XML language server `lemminx`：`/home/x/.nix-profile/bin/lemminx`。

### Node.js —— Node 24
- **node / npm / npx / corepack**：`/home/x/.nix-profile/bin/`（等价 `/nix/var/nix/profiles/nodejs-24/bin`），版本 v24.x。
- **pnpm / pnpx**（首选包管理器）：`/opt/sb/bin/pnpm`、`/opt/sb/bin/pnpx`。
- **prettier**：`/opt/sb/bin/prettier`；**markdownlint-cli2**：`/opt/sb/bin/markdownlint-cli2`。

### Go —— Go 1.26
- **go / gofmt**：`/home/x/.nix-profile/bin/go`（等价 `/nix/var/nix/profiles/go-1_26/bin`）。
- **周边工具装在 sb store，但没软链进 `/opt/sb/bin`，PATH 上默认没有**，需用绝对路径：
  - `gopls`：`/opt/sb/store/gopls/bin/gopls`
  - `golangci-lint`：`/opt/sb/store/golangci-lint/bin/golangci-lint`
  - `gofumpt`：`/opt/sb/store/gofumpt/bin/gofumpt`
  - 还有 `gotests`、`gomodifytags`、`go-outline`、`impl`、`dlv`(delve) 在 `/opt/sb/store/<name>/bin/`。
- **go-task**（`task`）：`/opt/sb/bin/task`。

### Rust —— 1.96（stable，固定）
- **rustc / cargo / clippy / rustfmt / rust-analyzer**：`/opt/rust/cargo/bin/`。
- 环境变量：`CARGO_HOME=/opt/rust/cargo`、`RUSTUP_HOME=/opt/rust/rustup`。**这俩要设好** cargo/rustc 才能正常跑（否则会去写只读的 `~/.rustup` 报错）；登录 shell 里已设好，非登录 shell 需自行 export。工具链是固定的 `stable`，不要 `rustup update`（rustup home 只读）。

### C / C++ / 构建系统
- **gcc / g++**（GCC 15，nix-env 预装）：`/home/x/.nix-profile/bin/gcc`、`/home/x/.nix-profile/bin/g++`。登录 shell PATH 上已有 `~/.nix-profile/bin`，可直接 `gcc`/`g++`；非登录 shell 用绝对路径。基础编译开箱即用；链接其他 nix 依赖时需手动 `-I`/`-L`。需要 clang 时 `nix-env -iA nixpkgs.clang`。
- **clang-format**：`/opt/sb/store/clang-tools-<18..22>/bin/clang-format`（默认用最高版本 21/22；VSCode 配置里指向 18）。`clang-tidy` 未预装。
- **cmake 4.x**：`/opt/sb/bin/cmake`（含 `ctest`/`cpack`）。**ninja**：`/opt/sb/bin/ninja`。
- **Bazel / bazelisk**：`/opt/sb/bin/bazel`（→ bazelisk）；`buildifier`/`buildozer` 也在 `/opt/sb/bin`。
- **protoc**：`/opt/sb/bin/protoc`（另有多版本 `protoc-24.4.0` / `protoc-25.9.0` / `protoc-28.3.0`）。

### Shell / 其它
- **shfmt / shellcheck**：`shfmt` 在 `/opt/sb/bin/shfmt`。

## 通用工具与常驻 CLI

`/opt/sb/bin/`（登录 shell PATH 首位）里已备齐大量 CLI，直接用即可：

- **VCS/协作**：`git`、`gh`、`git-lfs`、`git-delta`(delta)、`lefthook`、`scalar`，以及大量 `git-*` 扩展。
- **搜索/浏览**：`rg`(ripgrep)、`fd`、`fzf`、`bat`、`eza`/`exa`、`tree`、`yazi`、`jq`。
- **编辑/终端**：`vim`、`tmux`、`zellij`、`starship`、`atuin`。
- **数据/DB**：`sqlite3`、`psql`。
- **诊断**：`gdb`、`strace`、`lsof`、`procs`、`ncdu`/`gdu`、`patchelf`、`cloc`/`scc`。
- **网络/压缩**：`curl`、`wget`、`nc`、`ssh`、`rsync`、`zstd`、`xz`、`zip`/`unzip`、`7za`。

## 需要装新东西时
- **系统级/编译器/语言运行时** → 用 nix：`nix-env -iA nixpkgs.<pkg>`（装到 `~/.nix-profile/bin`）。
- **Python 全局命令行工具** → `uv tool install <tool>`（装到 `~/.local/bin`）。
- **Node 全局工具** → 优先项目内 `pnpm add -D`，避免全局污染。
- `apt` 需要 `sudo`，`/opt`、`/workspace` 归当前用户（uid 5230），home 下的 `~/.rustup` 等部分目录为只读，装东西前先确认可写。

## 速用 checklist（Agent 跑命令前自检）
1. 要用工具链命令？→ 用 `zsh -lic '<cmd>'` **或**绝对路径，别裸跑。
2. Java？→ 记得 `JAVA_HOME`；Go 周边工具走 `/opt/sb/store/*/bin`；Rust 记得 `CARGO_HOME`/`RUSTUP_HOME`。
3. 要编译 C/C++？→ 已预装 GCC 15（`~/.nix-profile/bin/gcc`）；链接第三方 nix 库时记得手动 `-I`/`-L`。
4. Python 项目？→ 一律 `uv`，别直接找 `python`。
