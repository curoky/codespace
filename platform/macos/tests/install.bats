#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
}

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  MACOS_HOME="$MACOS_DIR/rootfs/Users/x"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/home"
  TEST_EVENTS="$TEST_ROOT/events"
  export HOME TEST_EVENTS
  mkdir -p "$HOME" "$TEST_ROOT/bin"

  cat >"$TEST_ROOT/bin/swift" <<'EOF'
#!/usr/bin/env bash
printf 'swift %s\n' "$*" >>"$TEST_EVENTS"
EOF
  chmod +x "$TEST_ROOT/bin/"*
  PATH="$TEST_ROOT/bin:$PATH"
  export PATH

  # shellcheck source=platform/macos/install.sh
  source "$MACOS_DIR/install.sh"
}

teardown() {
  rm -rf "$TEST_ROOT"
}

stub_external_provisioning() {
  install_homebrew() {
    printf 'install-homebrew %s %s\n' "$1" "$2" >>"$TEST_EVENTS"
  }
  # shellcheck disable=SC2329 # main invokes this stub unless the failure test replaces it.
  install_binman() {
    printf 'install-binman %s %s\n' "$1" "$2" >>"$TEST_EVENTS"
  }
  load_launch_agent() {
    printf 'launch-agent %s %s/Library/LaunchAgents/%s.plist\n' "$2" "$1" "$2" >>"$TEST_EVENTS"
  }
}

file_mode() {
  if [[ "$(uname -s)" == Darwin ]]; then
    stat -f "%Lp" "$1"
  else
    stat -c "%a" "$1"
  fi
}

@test "installs managed home configuration from matching rootfs paths" {
  run install_home_config "$MACOS_HOME"
  [ "$status" -eq 0 ]

  local relative_path
  for relative_path in \
    .gitconfig \
    .config/git/user.gitconfig \
    .config/git/ignore \
    .ssh/config \
    .ssh/codespace/config \
    .ssh/codespace/login_key \
    .ssh/codespace/known_hosts/codespace \
    .ssh/codespace/proxy; do
    [ -L "$HOME/$relative_path" ]
    [ "$HOME/$relative_path" -ef "$MACOS_HOME/$relative_path" ]
  done

  [ "$(file_mode "$HOME/.ssh/codespace")" = 700 ]
  for relative_path in \
    .gitconfig \
    .config/git/user.gitconfig \
    .ssh/config \
    .ssh/codespace/config \
    .ssh/codespace/login_key \
    .ssh/codespace/known_hosts/codespace; do
    [ "$(file_mode "$MACOS_HOME/$relative_path")" = 600 ]
  done
  [ "$(file_mode "$MACOS_HOME/.ssh/codespace/proxy")" = 700 ]

  [ -L "$HOME/.zshrc" ]
  [ "$HOME/.zshrc" -ef "$MACOS_HOME/.zshrc" ]
  [ -L "$HOME/.warp/settings.toml" ]
  [ "$HOME/.warp/settings.toml" -ef "$MACOS_HOME/.warp/settings.toml" ]
  [ -L "$HOME/.config/zsh/aliases.zsh" ]
  [ "$HOME/.config/zsh/aliases.zsh" -ef "$MACOS_HOME/.config/zsh/aliases.zsh" ]

  local editor
  for editor in Code Trae "Trae CN"; do
    [ -L "$HOME/Library/Application Support/$editor/User/settings.json" ]
    [ "$HOME/Library/Application Support/$editor/User/settings.json" -ef \
      "$MACOS_HOME/Library/Application Support/$editor/User/settings.json" ]
    [ -L "$HOME/Library/Application Support/$editor/User/keybindings.json" ]
    [ -L "$HOME/Library/Application Support/$editor/User/snippets" ]
  done
}

@test "consumes packaged shell integrations" {
  stub_external_provisioning

  run main
  [ "$status" -eq 0 ]

  grep -Eq "^install-homebrew $MACOS_DIR /.*$" "$TEST_EVENTS"
  grep -Eq "^install-binman $MACOS_DIR /.*$" "$TEST_EVENTS"
  grep -Fqx "swift $MACOS_DIR/scripts/set-default-apps.swift" "$TEST_EVENTS"
  grep -Fqx \
    "launch-agent sh.atuin.daemon $MACOS_HOME/Library/LaunchAgents/sh.atuin.daemon.plist" \
    "$TEST_EVENTS"
  run grep -F "launch-agent sh.atuin.server " "$TEST_EVENTS"
  [ "$status" -ne 0 ]

  local temp_dir
  temp_dir="$(awk '$1 == "install-homebrew" { print $3 }' "$TEST_EVENTS")"
  [ -n "$temp_dir" ]
  [ ! -e "$temp_dir" ]

  local zshrc="$MACOS_HOME/.zshrc"
  grep -Fqx 'source "/opt/bm/store/starship/share/starship/init.zsh"' "$zshrc"
  grep -Fqx 'source "/opt/bm/store/atuin/share/atuin/init.zsh"' "$zshrc"
}

@test "enables the local Atuin server explicitly" {
  stub_external_provisioning

  run main --with-atuin-server
  [ "$status" -eq 0 ]

  grep -Fqx \
    "launch-agent sh.atuin.server $MACOS_HOME/Library/LaunchAgents/sh.atuin.server.plist" \
    "$TEST_EVENTS"
}

@test "ships valid Atuin launch agents in the macOS rootfs" {
  local label
  for label in sh.atuin.daemon sh.atuin.server; do
    local plist="$MACOS_HOME/Library/LaunchAgents/$label.plist"
    [ -f "$plist" ]
    grep -Fqx "  <string>$label</string>" "$plist"
    grep -Fq "    <string>/opt/bm/bin/atuin</string>" "$plist"
  done
}

@test "provisioning failure stops later steps and cleans temporary downloads" {
  stub_external_provisioning
  install_binman() {
    printf '%s' "$2" >"$TEST_ROOT/download-dir"
    return 7
  }

  run main

  [ "$status" -eq 7 ]
  [ ! -d "$(<"$TEST_ROOT/download-dir")" ]
  [ ! -e "$HOME/.gitconfig" ]
  run grep -F "launch-agent" "$TEST_EVENTS"
  [ "$status" -ne 0 ]
}

@test "LaunchAgent loading uses the matching rootfs path" {
  launchctl() {
    printf '%s\n' "$*" >>"$TEST_EVENTS"
  }

  run load_launch_agent "$MACOS_HOME" sh.atuin.daemon

  [ "$status" -eq 0 ]
  local target="$HOME/Library/LaunchAgents/sh.atuin.daemon.plist"
  [ "$target" -ef "$MACOS_HOME/Library/LaunchAgents/sh.atuin.daemon.plist" ]
  grep -Fqx "bootstrap gui/$(id -u) $target" "$TEST_EVENTS"
  grep -Fqx "kickstart -k gui/$(id -u)/sh.atuin.daemon" "$TEST_EVENTS"
}

@test "shares editor configuration within the macOS rootfs" {
  local code_user="$MACOS_HOME/Library/Application Support/Code/User"
  local editor editor_user

  for editor in Trae "Trae CN"; do
    editor_user="$MACOS_HOME/Library/Application Support/$editor/User"
    [ -L "$editor_user/settings.json" ]
    [ "$editor_user/settings.json" -ef "$code_user/settings.json" ]
    [ -L "$editor_user/keybindings.json" ]
    [ "$editor_user/keybindings.json" -ef "$code_user/keybindings.json" ]
    [ -L "$editor_user/snippets" ]
    [ "$editor_user/snippets" -ef "$code_user/snippets" ]
  done
}
