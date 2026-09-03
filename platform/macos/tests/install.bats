#!/usr/bin/env bats

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  REPO_ROOT="$(cd "$MACOS_DIR/../.." && pwd -P)"
  MACOS_HOME="$MACOS_DIR/rootfs/Users/x"
  WORKSPACE_HOME="$REPO_ROOT/platform/container/workspace/rootfs/home/x"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/home"
  export HOME
  mkdir -p "$HOME"

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
  [ -L "$HOME/.config/zsh/environment.zsh" ]
  [ "$HOME/.config/zsh/environment.zsh" -ef "$WORKSPACE_HOME/.config/zsh/environment.zsh" ]

  local editor
  for editor in Code Trae "Trae CN"; do
    [ -L "$HOME/Library/Application Support/$editor/User/settings.json" ]
    [ "$HOME/Library/Application Support/$editor/User/settings.json" -ef \
      "$MACOS_HOME/Library/Application Support/$editor/User/settings.json" ]
    [ -L "$HOME/Library/Application Support/$editor/User/keybindings.json" ]
    [ -L "$HOME/Library/Application Support/$editor/User/snippets" ]
  done
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
