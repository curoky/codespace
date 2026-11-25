package main

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/pelletier/go-toml/v2"
)

func TestTokenCommandNeedsNoSecrets(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	directory := filepath.Join(home, ".codex")
	if err := saveCredential(directory, credential{"fixture-token", time.Now().Add(time.Hour)}); err != nil {
		t.Fatal(err)
	}
	for _, flags := range [][]string{nil, {"--env"}} {
		var stdout, stderr bytes.Buffer
		args := append([]string{"token"}, flags...)
		if err := run(context.Background(), args, &stdout, &stderr); err != nil {
			t.Fatal(err)
		}
		if stdout.String() != "at-fixture-token\n" || stderr.Len() != 0 {
			t.Fatalf("Invalid helper output: %q, %q", stdout.String(), stderr.String())
		}
	}
}

func TestConfigureEnvironmentFlagAndFixedPaths(t *testing.T) {
	setConnectionEnvironment(t)
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	ignoredHome := t.TempDir()
	t.Setenv("CODEX_HOME", ignoredHome)
	var stdout, stderr bytes.Buffer
	if err := run(context.Background(), []string{"configure", "--env"}, &stdout, &stderr); err != nil {
		t.Fatal(err)
	}
	var config map[string]any
	if err := toml.Unmarshal(stdout.Bytes(), &config); err != nil {
		t.Fatal(err)
	}
	provider := config["model_providers"].(map[string]any)["llmbox"].(map[string]any)
	if provider["http_headers"].(map[string]any)["X-Source"] != "environment-source" {
		t.Fatalf("Environment settings were not applied: %s", stdout.String())
	}
	args := provider["auth"].(map[string]any)["args"].([]any)
	if len(args) != 1 || args[0] != "token" {
		t.Fatalf("Unexpected helper arguments: %v", args)
	}
	rendered := stdout.String()
	stdout.Reset()
	if err := run(context.Background(), []string{"configure", "--env", "--write"}, &stdout, &stderr); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join(home, ".codex", "llmbox.config.toml"))
	if err != nil || string(data) != rendered || stdout.Len() != 0 {
		t.Fatalf("Unexpected written profile: %s, %v", data, err)
	}
	if _, err := os.Stat(filepath.Join(ignoredHome, "llmbox.config.toml")); !os.IsNotExist(err) {
		t.Fatalf("Profile used CODEX_HOME: %v", err)
	}
}
