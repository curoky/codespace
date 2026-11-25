package main

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestCatalogUsesBearerAndSource(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/native-catalog" || r.Header.Get("Authorization") != "Bearer fixture-token" || r.Header.Get("X-Source") != "fixture-source" || r.Header.Get("Accept") != "application/json" {
			t.Error("Missing request headers")
		}
		if _, err := io.WriteString(w, `{"models":[{"slug":"fixture-model","display_name":"Fixture Model","visibility":"list","base_instructions":"not-in-output"}]}`); err != nil {
			t.Error(err)
		}
	}))
	defer server.Close()
	config := exampleConnection(t)
	config.Providers.LLMBox.CatalogURL = server.URL + "/native-catalog"
	config.Providers.LLMBox.Headers.Source = "fixture-source"
	items, err := fetchModels(context.Background(), config, "fixture-token")
	if err != nil || len(items) != 1 || items[0] != (model{"fixture-model", "Fixture Model", "list"}) {
		t.Fatalf("Unexpected catalog: %+v, %v", items, err)
	}
}

func TestCatalogRejectsHTTPAndJSONErrors(t *testing.T) {
	for _, item := range []struct {
		status int
		body   string
	}{
		{401, "private-reflected-credential"}, {503, "private-reflected-credential"},
		{200, `{"data":[{"id":"fixture-model"}]}`},
		{200, `{"models":null}`}, {200, `malformed-json`},
	} {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(item.status)
			if _, err := io.WriteString(w, item.body); err != nil {
				t.Error(err)
			}
		}))
		config := exampleConnection(t)
		config.Providers.LLMBox.CatalogURL = server.URL + "/models"
		_, err := fetchModels(context.Background(), config, "fixture-token")
		server.Close()
		if err == nil || strings.Contains(err.Error(), "private") {
			t.Fatalf("Unexpected error: %v", err)
		}
	}
}

func TestCatalogDoesNotForwardCredentialToRedirects(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { t.Error("Redirect followed") }))
	defer upstream.Close()
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, upstream.URL, http.StatusTemporaryRedirect)
	}))
	defer server.Close()
	config := exampleConnection(t)
	config.Providers.LLMBox.CatalogURL = server.URL + "/models"
	if _, err := fetchModels(context.Background(), config, "fixture-token"); err == nil {
		t.Fatal("Redirect accepted")
	}
}
