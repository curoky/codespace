#!/usr/bin/env bats

# shellcheck disable=SC2016 # Tests match literal runtime expansion in zshrc.

setup_file() {
  bats_require_minimum_version 1.5.0
}

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  MACOS_HOME="$MACOS_DIR/rootfs/Users/x"
  WORKSPACE_HOME="$(cd "$MACOS_DIR/../container/workspace/rootfs/home/x" && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/home"
  TEST_EVENTS="$TEST_ROOT/events"
  export HOME TEST_EVENTS TEST_ROOT
  mkdir -p "$HOME" "$TEST_ROOT/bin"

  cat >"$TEST_ROOT/bin/swift" <<'EOF'
#!/usr/bin/env bash
printf 'swift %s\n' "$*" >>"$TEST_EVENTS"
EOF
  cat >"$TEST_ROOT/bin/launchctl" <<'EOF'
#!/usr/bin/env bash
printf 'launchctl %s\n' "$*" >>"$TEST_EVENTS"
case "$1" in
  bootout)
    rm -f "$TEST_ROOT/launchctl-loaded" "$HOME/.local/share/atuin/atuin.sock"
    ;;
  bootstrap)
    touch "$TEST_ROOT/launchctl-loaded"
    mkdir -p "$HOME/.local/share/atuin"
    python3 - "$HOME/.local/share/atuin/atuin.sock" <<'PY'
import socket
import sys

server = socket.socket(socket.AF_UNIX)
server.bind(sys.argv[1])
server.close()
PY
    ;;
  print)
    [[ -f "$TEST_ROOT/launchctl-loaded" ]]
    ;;
esac
EOF
  chmod +x "$TEST_ROOT/bin/"*
  PATH="$TEST_ROOT/bin:$PATH"
  export PATH
}

teardown() {
  rm -rf "$TEST_ROOT"
}

file_mode() {
  if [[ "$(uname -s)" == Darwin ]]; then
    /usr/bin/stat -L -f "%Lp" "$1"
  else
    stat -L -c "%a" "$1"
  fi
}

@test "maintenance operations are standalone executable scripts" {
  local script
  for script in \
    atuin-daemon \
    binman \
    default-apps \
    go \
    home-links \
    homebrew \
    node-runtime \
    node-tools \
    uv; do
    [ -x "$MACOS_DIR/maintenance/$script.sh" ]
  done

  run grep -R -nE '(^|[[:space:]])source[[:space:]].*maintenance/' \
    "$MACOS_DIR/maintenance"
  [ "$status" -eq 1 ]
}

@test "home links converge independently" {
  mkdir -p \
    "$HOME/.codex/skills/manage-software" \
    "$HOME/.trae-cn/skills/manage-software"
  touch \
    "$HOME/.codex/skills/manage-software/stale" \
    "$HOME/.trae-cn/skills/manage-software/stale"

  run "$MACOS_DIR/maintenance/home-links.sh"
  [ "$status" -eq 0 ]

  local relative_path
  for relative_path in \
    .gitconfig \
    .gitignore_global \
    .config/zsh/aliases.zsh \
    .config/zsh/functions.zsh \
    .config/zsh/git.zsh \
    .config/atuin/config.toml \
    .config/bat/config \
    .config/nixpkgs/config.nix \
    .config/starship.toml \
    .config/tmux/tmux.conf \
    .local/bin/eza-wrapper \
    .vimrc; do
    [ -L "$HOME/$relative_path" ]
    [ "$HOME/$relative_path" -ef "$WORKSPACE_HOME/$relative_path" ]
  done

  for relative_path in \
    .config/git/user.gitconfig \
    .ssh/config \
    .ssh/codespace/config \
    .ssh/codespace/known_hosts/codespace \
    .zshrc \
    .codex/AGENTS.md \
    .warp/settings.toml; do
    [ -L "$HOME/$relative_path" ]
    [ "$HOME/$relative_path" -ef "$MACOS_HOME/$relative_path" ]
  done

  [ "$HOME/.ssh/codespace/workspace_login_key_ed25519" -ef \
    "$WORKSPACE_HOME/.ssh/workspace_login_key_ed25519" ]
  [ ! -e "$HOME/.codex/skills/manage-software" ]
  [ ! -e "$HOME/.trae-cn/skills/manage-software" ]

  for relative_path in \
    .trae/sandbox.json \
    .trae/traecli.toml \
    .trae-cn/sandbox.json \
    .trae-cn/traecli.toml; do
    [ ! -L "$HOME/$relative_path" ]
    cmp "$HOME/$relative_path" "$WORKSPACE_HOME/$relative_path"
  done

  [ "$(file_mode "$HOME/.ssh/codespace")" = 700 ]
  [ "$(file_mode "$WORKSPACE_HOME/.local/bin/eza-wrapper")" = 755 ]
}

@test "editor links converge independently" {
  run "$MACOS_DIR/maintenance/home-links.sh"
  [ "$status" -eq 0 ]

  local code_user="$MACOS_HOME/Library/Application Support/Code/User"
  local editor editor_user
  for editor in Code Trae "Trae CN"; do
    editor_user="$HOME/Library/Application Support/$editor/User"
    [ "$editor_user/settings.json" -ef "$code_user/settings.json" ]
    [ "$editor_user/keybindings.json" -ef "$code_user/keybindings.json" ]
    [ "$editor_user/snippets" -ef "$code_user/snippets" ]
  done
}

@test "default apps operation invokes the Swift setup" {
  run "$MACOS_DIR/maintenance/default-apps.sh"

  [ "$status" -eq 0 ]
  grep -Fqx "swift $MACOS_DIR/scripts/set-default-apps.swift" "$TEST_EVENTS"
}

@test "Atuin daemon operation installs and reloads only its plist" {
  run "$MACOS_DIR/maintenance/atuin-daemon.sh"

  [ "$status" -eq 0 ]
  local target="$HOME/Library/LaunchAgents/sh.atuin.daemon.plist"
  [ ! -L "$target" ]
  cmp "$target" "$MACOS_HOME/Library/LaunchAgents/sh.atuin.daemon.plist"
  grep -Fqx "launchctl bootstrap gui/$(id -u) $target" "$TEST_EVENTS"
  grep -Fqx "launchctl kickstart -k gui/$(id -u)/sh.atuin.daemon" "$TEST_EVENTS"
  run grep -F "sh.atuin.server" "$TEST_EVENTS"
  [ "$status" -eq 1 ]
}

@test "user-local shell paths match maintenance outputs" {
  local zshrc="$MACOS_HOME/.zshrc"

  grep -Fqx '  "$HOME/.local/bin"' "$zshrc"
  grep -Fqx '  "$HOME/.local/share/uv/bin"' "$zshrc"
  grep -Fqx '  "$HOME/.local/share/node/tools/bin"' "$zshrc"
  grep -Fqx '  "$HOME/.local/share/node/nodejs24/bin"' "$zshrc"
  grep -Fqx '  "$HOME/.local/share/go/go1.27.1/bin"' "$zshrc"
  grep -Fqx '  "$HOME/.local/profile/go/bin"' "$zshrc"
}
