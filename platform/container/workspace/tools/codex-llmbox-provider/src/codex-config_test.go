package main

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/pelletier/go-toml/v2"
)

func TestProfileSerializesNativeProviderAndHelper(t *testing.T) {
	config := exampleConnection(t)
	executable := "/path with spaces/codex-llmbox-provider"
	config.Source = "value\"\\fixture\nline"
	data, err := renderProfile(config, executable)
	if err != nil {
		t.Fatal(err)
	}
	var profile struct {
		Model           string `toml:"model"`
		ReasoningEffort string `toml:"model_reasoning_effort"`
		Provider        string `toml:"model_provider"`
		Providers       map[string]struct {
			BaseURL            string            `toml:"base_url"`
			CatalogURL         string            `toml:"model_catalog_url"`
			WireAPI            string            `toml:"wire_api"`
			RequiresOpenAIAuth bool              `toml:"requires_openai_auth"`
			Headers            map[string]string `toml:"http_headers"`
			Auth               struct {
				Command string   `toml:"command"`
				Args    []string `toml:"args"`
			} `toml:"auth"`
		} `toml:"model_providers"`
	}
	if err := toml.Unmarshal(data, &profile); err != nil {
		t.Fatal(err)
	}
	provider := profile.Providers["llmbox"]
	if profile.Model != "gpt-6.1-sol" || profile.ReasoningEffort != "high" || profile.Provider != "llmbox" || provider.WireAPI != "responses" || provider.RequiresOpenAIAuth || provider.BaseURL != config.BaseURL || provider.CatalogURL != config.BaseURL+"models" || provider.Auth.Command != executable ||
		len(provider.Headers) != 1 || provider.Headers["X-Source"] != config.Source || !reflect.DeepEqual(provider.Auth.Args, []string{"token"}) {
		t.Fatalf("Invalid serialized profile: %s", data)
	}
}

func TestProfileWritesAreIdempotentAndPreserveExistingContent(t *testing.T) {
	directory := t.TempDir()
	base := filepath.Join(directory, "config.toml")
	path := filepath.Join(directory, "llmbox.config.toml")
	if err := os.WriteFile(base, []byte("base-user-config"), 0o600); err != nil {
		t.Fatal(err)
	}
	data := []byte("generated-profile")
	for range 2 {
		if err := writeProfile(path, data); err != nil {
			t.Fatal(err)
		}
	}
	if err := writeProfile(path, []byte("different-profile")); err == nil {
		t.Fatal("Existing profile overwritten")
	}
	actual, err := os.ReadFile(path)
	if err != nil || string(actual) != string(data) {
		t.Fatal("Existing content changed")
	}
	actual, err = os.ReadFile(base)
	if err != nil || string(actual) != "base-user-config" {
		t.Fatal("Base config changed")
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatal("Invalid profile permissions")
	}
}
