package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/pelletier/go-toml/v2"
)

func exampleSettings() map[string]string {
	return map[string]string{
		"issuer":      "https://identity.example.com",
		"client_id":   "example-public-client",
		"catalog_url": "https://models.example.com/models",
		"source":      "example",
	}
}

func writeConnectionFile(t *testing.T, values map[string]string) string {
	t.Helper()
	directory := t.TempDir()
	data, err := toml.Marshal(map[string]any{
		"_llmbox": map[string]string{"issuer": values["issuer"], "client_id": values["client_id"]},
		"model_providers": map[string]any{
			"llmbox": map[string]any{"model_catalog_url": values["catalog_url"], "http_headers": map[string]string{"X-Source": values["source"]}},
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(directory, "llmbox.config.toml"), data, 0o600); err != nil {
		t.Fatal(err)
	}
	return directory
}

func exampleConnection(t *testing.T) connection {
	t.Helper()
	config, err := loadConnection(writeConnectionFile(t, exampleSettings()))
	if err != nil {
		t.Fatal(err)
	}
	return config
}

func TestConnectionReadsFileAndIgnoresEnvironment(t *testing.T) {
	t.Setenv("OAUTH_ISSUER", "https://ignored.example.org")
	t.Setenv("OAUTH_CLIENT_ID", "ignored-client")
	t.Setenv("LLMBOX_BASE_URL", "https://ignored-models.example.org")
	t.Setenv("LLMBOX_SOURCE", "ignored-source")
	values := exampleSettings()
	values["issuer"] = "https://custom.example.org/identity"
	values["catalog_url"] = "https://custom.example.org/native-catalog"
	values["source"] = "fixture"
	config, err := loadConnection(writeConnectionFile(t, values))
	if err != nil {
		t.Fatal(err)
	}
	if config.OAuth.Issuer != "https://custom.example.org/identity" || config.OAuth.ClientID != "example-public-client" ||
		config.Providers.LLMBox.CatalogURL != "https://custom.example.org/native-catalog" || config.Providers.LLMBox.Headers.Source != "fixture" {
		t.Fatalf("Unexpected endpoint configuration: %+v", config)
	}
}

func TestConnectionRequiresValidFile(t *testing.T) {
	directory := writeConnectionFile(t, exampleSettings())
	path := filepath.Join(directory, "llmbox.config.toml")
	if err := os.WriteFile(path, []byte("private-malformed-TOML"), 0o600); err != nil {
		t.Fatal(err)
	}
	_, err := loadConnection(directory)
	if err == nil || strings.Contains(err.Error(), "private") {
		t.Fatalf("Unexpected malformed configuration error: %v", err)
	}
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	_, err = loadConnection(directory)
	if err == nil || !strings.Contains(err.Error(), "llmbox.config.toml") {
		t.Fatalf("Unexpected missing configuration error: %v", err)
	}
}
