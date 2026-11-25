package main

import (
	"errors"
	"fmt"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

type connection struct {
	Issuer   string
	ClientID string
	BaseURL  string
	Source   string
}

func loadConnection(directory string, fromEnv bool) (connection, error) {
	var config connection
	for _, field := range []struct {
		secret, environment string
		value               *string
	}{
		{"oauth_issuer", "OAUTH_ISSUER", &config.Issuer},
		{"oauth_client_id", "OAUTH_CLIENT_ID", &config.ClientID},
		{"base_url", "LLMBOX_BASE_URL", &config.BaseURL},
		{"source", "LLMBOX_SOURCE", &config.Source},
	} {
		name := "codespace_llmbox_" + field.secret
		if fromEnv {
			name = field.environment
			*field.value = os.Getenv(name)
		} else {
			data, err := os.ReadFile(filepath.Join(directory, name))
			if err != nil {
				return config, fmt.Errorf("cannot read secret %s: %w", name, err)
			}
			*field.value = string(data)
		}
		*field.value = strings.TrimSpace(*field.value)
		if *field.value == "" {
			return config, fmt.Errorf("%s is empty", name)
		}
	}
	for _, address := range []string{config.Issuer, config.BaseURL} {
		parsed, err := url.Parse(address)
		if err != nil || parsed.Hostname() == "" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || (parsed.Scheme != "http" && parsed.Scheme != "https") {
			return config, errors.New("service base URLs must be HTTP(S) URLs without credentials, query or fragment")
		}
	}
	if !strings.HasPrefix(config.Issuer, "https://") {
		return config, errors.New("OAuth issuer requires HTTPS")
	}
	config.Issuer = strings.TrimRight(config.Issuer, "/")
	config.BaseURL = strings.TrimRight(config.BaseURL, "/") + "/"
	return config, nil
}
