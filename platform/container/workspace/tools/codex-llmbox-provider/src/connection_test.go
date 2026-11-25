package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func exampleSecrets(t *testing.T) map[string]string {
	t.Helper()
	return map[string]string{
		"oauth_issuer":    "https://identity.example.com",
		"oauth_client_id": "example-public-client",
		"base_url":        "https://models.example.com/",
		"source":          "example",
	}
}

func writeSecretFiles(t *testing.T, values map[string]string) string {
	t.Helper()
	directory := t.TempDir()
	for key, value := range values {
		if err := os.WriteFile(filepath.Join(directory, "codespace_llmbox_"+key), []byte(value+"\n"), 0o400); err != nil {
			t.Fatal(err)
		}
	}
	return directory
}

func setConnectionEnvironment(t *testing.T) {
	t.Helper()
	t.Setenv("OAUTH_ISSUER", "https://environment.example.com/\n")
	t.Setenv("OAUTH_CLIENT_ID", "fixture-client\n")
	t.Setenv("LLMBOX_BASE_URL", "https://environment-models.example.com/\n")
	t.Setenv("LLMBOX_SOURCE", "environment-source\n")
}

func exampleConnection(t *testing.T) connection {
	t.Helper()
	config, err := loadConnection(writeSecretFiles(t, exampleSecrets(t)), false)
	if err != nil {
		t.Fatal(err)
	}
	return config
}

func TestConnectionNormalizesBaseURLs(t *testing.T) {
	values := exampleSecrets(t)
	values["oauth_issuer"] = "https://custom.example.org/identity/"
	values["base_url"] = "https://custom.example.org/api"
	values["source"] = "fixture"
	config, err := loadConnection(writeSecretFiles(t, values), false)
	if err != nil {
		t.Fatal(err)
	}
	if config.Issuer != "https://custom.example.org/identity" ||
		config.BaseURL != "https://custom.example.org/api/" || config.Source != "fixture" {
		t.Fatalf("Unexpected endpoint configuration: %+v", config)
	}
}

func TestConnectionRejectsInvalidInputWithoutDisclosure(t *testing.T) {
	for _, item := range []struct{ field, value string }{
		{"oauth_client_id", ""},
		{"oauth_issuer", "http://identity.example.org"},
		{"base_url", "https://private-user:private-password@example.org"},
		{"source", ""},
	} {
		t.Run(item.field+item.value, func(t *testing.T) {
			values := exampleSecrets(t)
			values[item.field] = item.value
			_, err := loadConnection(writeSecretFiles(t, values), false)
			if err == nil || strings.Contains(err.Error(), "private") {
				t.Fatalf("Unexpected error: %v", err)
			}
		})
	}
}

func TestConnectionRequiresSecretFiles(t *testing.T) {
	values := exampleSecrets(t)
	delete(values, "oauth_client_id")
	_, err := loadConnection(writeSecretFiles(t, values), false)
	if err == nil || !strings.Contains(err.Error(), "codespace_llmbox_oauth_client_id") {
		t.Fatalf("Unexpected missing secret error: %v", err)
	}
}

func TestConnectionUsesOnlySelectedSource(t *testing.T) {
	setConnectionEnvironment(t)
	directory := writeSecretFiles(t, exampleSecrets(t))
	fromSecrets, err := loadConnection(directory, false)
	if err != nil {
		t.Fatal(err)
	}
	if fromSecrets.Source != "example" || fromSecrets.Issuer != "https://identity.example.com" {
		t.Fatalf("Unexpected secret configuration: %+v", fromSecrets)
	}
	fromEnv, err := loadConnection(filepath.Join(directory, "missing"), true)
	if err != nil {
		t.Fatal(err)
	}
	if fromEnv.Source != "environment-source" || fromEnv.ClientID != "fixture-client" ||
		fromEnv.Issuer != "https://environment.example.com" ||
		fromEnv.BaseURL != "https://environment-models.example.com/" {
		t.Fatalf("Unexpected environment configuration: %+v", fromEnv)
	}
	if err := os.Remove(filepath.Join(directory, "codespace_llmbox_source")); err != nil {
		t.Fatal(err)
	}
	if _, err := loadConnection(directory, false); err == nil {
		t.Fatal("Missing secret was filled from the environment")
	}
	t.Setenv("LLMBOX_SOURCE", "")
	if _, err := loadConnection(writeSecretFiles(t, exampleSecrets(t)), true); err == nil || !strings.Contains(err.Error(), "LLMBOX_SOURCE") {
		t.Fatalf("Unexpected missing environment error: %v", err)
	}
}
