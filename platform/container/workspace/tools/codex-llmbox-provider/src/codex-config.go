package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"

	"github.com/pelletier/go-toml/v2"
)

func configure(config connection, write bool, output io.Writer) error {
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	data, err := renderProfile(config, executable)
	if err != nil {
		return err
	}
	if !write {
		_, err = output.Write(data)
		return err
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	path := filepath.Join(home, ".codex", "llmbox.config.toml")
	if err := writeProfile(path, data); err != nil {
		return err
	}
	_, err = fmt.Fprintf(output, "Codex profile ready: %s\nRun codex -p llmbox to start.\n", path)
	return err
}

func renderProfile(config connection, executable string) ([]byte, error) {
	return toml.Marshal(map[string]any{
		"model": "gpt-6.1-sol", "model_reasoning_effort": "high",
		"model_provider": "llmbox",
		"model_providers": map[string]any{
			"llmbox": map[string]any{
				"name": "LLMBox", "base_url": config.BaseURL,
				"wire_api": "responses", "supports_websockets": false, "requires_openai_auth": false,
				"model_catalog_url": config.BaseURL + "models", "http_headers": map[string]string{"X-Source": config.Source},
				"auth": map[string]any{
					"command":    executable,
					"args":       []string{"token"},
					"timeout_ms": 5000, "refresh_interval_ms": 300000,
				},
			},
		},
	})
}

func writeProfile(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if errors.Is(err, os.ErrExist) {
		existing, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if bytes.Equal(existing, data) {
			return nil
		}
		return fmt.Errorf("the profile already exists with different content and was not overwritten: %s. Review the default stdout output first", path)
	}
	if err != nil {
		return err
	}
	_, writeErr := file.Write(data)
	if writeErr == nil {
		writeErr = file.Sync()
	}
	return errors.Join(writeErr, file.Close())
}
