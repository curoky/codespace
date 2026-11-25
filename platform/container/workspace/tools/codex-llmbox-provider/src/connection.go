package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/pelletier/go-toml/v2"
)

type connection struct {
	OAuth struct {
		Issuer   string `toml:"issuer"`
		ClientID string `toml:"client_id"`
	} `toml:"_llmbox"`
	Providers struct {
		LLMBox struct {
			CatalogURL string `toml:"model_catalog_url"`
			Headers    struct {
				Source string `toml:"X-Source"`
			} `toml:"http_headers"`
		} `toml:"llmbox"`
	} `toml:"model_providers"`
}

func loadConnection(directory string) (connection, error) {
	var config connection
	data, err := os.ReadFile(filepath.Join(directory, "llmbox.config.toml"))
	if err != nil {
		return config, fmt.Errorf("cannot read provider configuration: %w", err)
	}
	if err := toml.Unmarshal(data, &config); err != nil {
		return config, errors.New("invalid TOML configuration: llmbox.config.toml")
	}
	return config, nil
}
