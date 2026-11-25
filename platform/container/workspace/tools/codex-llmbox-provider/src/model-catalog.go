package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type model struct {
	Slug        string `json:"slug"`
	DisplayName string `json:"display_name"`
	Visibility  string `json:"visibility"`
}

func fetchModels(ctx context.Context, config connection, token string) ([]model, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, config.BaseURL+"models", nil)
	if err != nil {
		return nil, errors.New("invalid model catalog URL")
	}
	request.Header.Set("X-Source", config.Source)
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("Accept", "application/json")
	client := &http.Client{
		Timeout:       15 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	response, err := client.Do(request)
	if err != nil {
		return nil, errors.New("cannot fetch model catalog")
	}
	defer response.Body.Close() //nolint:errcheck // Closing a read-only response cannot invalidate its decoded result.
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("model catalog request failed: HTTP %d", response.StatusCode)
	}
	var catalog struct {
		Models []model `json:"models"`
	}
	if err := json.NewDecoder(response.Body).Decode(&catalog); err != nil || catalog.Models == nil {
		return nil, errors.New("invalid native model catalog")
	}
	return catalog.Models, nil
}

func writeModels(output io.Writer, items []model, outputJSON bool) error {
	if outputJSON {
		encoder := json.NewEncoder(output)
		encoder.SetIndent("", "  ")
		return encoder.Encode(items)
	}
	var text strings.Builder
	text.WriteString("MODEL\tNAME\tVISIBILITY\n")
	for _, item := range items {
		fmt.Fprintf(&text, "%s\t%s\t%s\n", item.Slug, item.DisplayName, item.Visibility)
	}
	_, err := io.WriteString(output, text.String())
	return err
}
