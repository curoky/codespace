#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
}

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  REPO_ROOT="$(cd "$MACOS_DIR/../.." && pwd -P)"
  MACOS_HOME="$MACOS_DIR/rootfs/Users/x"
  WORKSPACE_HOME="$REPO_ROOT/platform/container/workspace/rootfs/home/x"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/home"
  XDG_CACHE_HOME="$TEST_ROOT/cache"
  TEST_EVENTS="$TEST_ROOT/events"
  export HOME XDG_CACHE_HOME TEST_EVENTS
  mkdir -p "$HOME" "$TEST_ROOT/bin"

  cat >"$TEST_ROOT/bin/conda" <<'EOF'
#!/usr/bin/env bash
printf 'conda %s\n' "$*" >>"$TEST_EVENTS"
printf '# conda plugin\n'
EOF
  cat >"$TEST_ROOT/bin/starship" <<'EOF'
#!/usr/bin/env bash
printf 'starship %s\n' "$*" >>"$TEST_EVENTS"
printf '# starship plugin\n'
EOF
  cat >"$TEST_ROOT/bin/atuin" <<'EOF'
#!/usr/bin/env bash
printf 'atuin %s\n' "$*" >>"$TEST_EVENTS"
printf '# atuin plugin\n'
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

@test "installs managed home configuration from rootfs sources" {
  run install_home_config "$MACOS_HOME" "$WORKSPACE_HOME"
  [ "$status" -eq 0 ]

  [ ! -L "$HOME/.gitconfig" ]
  cmp "$MACOS_HOME/.gitconfig" "$HOME/.gitconfig"
  [ ! -L "$HOME/.ssh/config" ]
  cmp "$MACOS_HOME/.ssh/config" "$HOME/.ssh/config"

  [ -L "$HOME/.config/git/ignore" ]
  [ "$HOME/.config/git/ignore" -ef "$MACOS_HOME/.config/git/ignore" ]
  [ -L "$HOME/.zshrc" ]
  [ "$HOME/.zshrc" -ef "$MACOS_HOME/.zshrc" ]
  [ -L "$HOME/.config/zsh/aliases.zsh" ]
  [ "$HOME/.config/zsh/aliases.zsh" -ef "$WORKSPACE_HOME/.config/zsh/aliases.zsh" ]

  local editor
  for editor in Code Trae "Trae CN"; do
    [ -L "$HOME/Library/Application Support/$editor/User/settings.json" ]
    [ "$HOME/Library/Application Support/$editor/User/settings.json" -ef \
      "$MACOS_HOME/Library/Application Support/$editor/User/settings.json" ]
    [ -L "$HOME/Library/Application Support/$editor/User/keybindings.json" ]
    [ -L "$HOME/Library/Application Support/$editor/User/snippets" ]
  done
}

@test "generates shell plugins during installation" {
  run main
  [ "$status" -eq 0 ]

  [ "$(<"$XDG_CACHE_HOME/conda.plugin.zsh")" = "# conda plugin" ]
  [ "$(<"$XDG_CACHE_HOME/starship.plugin.zsh")" = "# starship plugin" ]
  [ "$(<"$XDG_CACHE_HOME/atuin.plugin.zsh")" = "# atuin plugin" ]
  grep -qx "conda shell.zsh hook" "$TEST_EVENTS"
  grep -qx "starship init zsh" "$TEST_EVENTS"
  grep -qx "atuin init zsh --disable-up-arrow" "$TEST_EVENTS"

  local zshrc="$MACOS_HOME/.zshrc"
  grep -Fqx "source \"\$XDG_CACHE_HOME/conda.plugin.zsh\"" "$zshrc"
  grep -Fqx "source \"\$XDG_CACHE_HOME/starship.plugin.zsh\"" "$zshrc"
  grep -Fqx "source \"\$XDG_CACHE_HOME/atuin.plugin.zsh\"" "$zshrc"
  run ! grep -Eq 'command -v (conda|starship|atuin)' "$zshrc"
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
