package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"golang.org/x/oauth2"
)

func TestCredentialsKeepOnlyTokenAndUTCExpiry(t *testing.T) {
	directory := t.TempDir()
	value := credential{"fixture-token", time.Now().Add(time.Hour)}
	if err := saveCredential(directory, value); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(directory, "llmbox.auth.json")
	if err := os.Chmod(path, 0o644); err != nil {
		t.Fatal(err)
	}
	value.AccessToken = "at-new-fixture"
	if err := saveCredential(directory, value); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		t.Fatal(err)
	}
	if len(fields) != 2 || fields["access_token"] == nil || fields["expires_at"] == nil || !strings.Contains(string(fields["expires_at"]), "Z") {
		t.Fatalf("Unexpected fields: %s", data)
	}
	for path, mode := range map[string]os.FileMode{directory: 0o700, path: 0o600} {
		info, err := os.Stat(path)
		if err != nil || info.Mode().Perm() != mode {
			t.Fatalf("Invalid permissions for %s: %v", path, err)
		}
	}
	entries, err := os.ReadDir(directory)
	if err != nil || len(entries) != 1 {
		t.Fatalf("Temporary files remain: %v, %v", entries, err)
	}
	token, err := readToken(directory)
	if err != nil || token != "at-new-fixture" {
		t.Fatalf("Unexpected token: %s, %v", token, err)
	}
	if err := saveCredential(directory, credential{"invalid-new", time.Time{}}); err == nil {
		t.Fatal("Invalid credential accepted")
	}
	token, err = readToken(directory)
	if err != nil || token != "at-new-fixture" {
		t.Fatal("Existing credential was replaced")
	}
}

func TestDeviceFlowUsesPublicClientAndPreservesCredentialsOnFailure(t *testing.T) {
	for _, result := range []string{"success", "no-expiry", "denied"} {
		t.Run(result, func(t *testing.T) {
			directory := t.TempDir()
			if err := saveCredential(directory, credential{"existing-fixture", time.Now().Add(time.Hour)}); err != nil {
				t.Fatal(err)
			}
			polls := 0
			server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if err := r.ParseForm(); err != nil {
					t.Error(err)
				}
				if r.Method != http.MethodPost || r.Form.Get("client_id") != "example-public-client" || r.Form.Has("client_secret") || r.Header.Get("Authorization") != "" {
					t.Errorf("Unexpected OAuth request: %s %s, %v", r.Method, r.URL.Path, r.Form)
				}
				w.Header().Set("Content-Type", "application/json")
				var body string
				switch r.URL.Path {
				case "/oauth2/device/code":
					if r.Form.Get("scope") != "read ciam.device.read" {
						t.Error("Missing scope")
					}
					body = `{"device_code":"fixture-device","user_code":"ABCD","verification_uri":"https://identity.example.org/verify","expires_in":60,"interval":1}`
				case "/oauth2/access_token":
					polls++
					if r.Form.Get("grant_type") != "urn:ietf:params:oauth:grant-type:device_code" || r.Form.Get("device_code") != "fixture-device" {
						t.Error("Invalid device grant")
					}
					if polls == 1 {
						w.WriteHeader(http.StatusBadRequest)
						body = `{"error":"authorization_pending"}`
					} else if result == "denied" {
						w.WriteHeader(http.StatusBadRequest)
						body = `{"error":"access_denied","error_description":"private-upstream-value"}`
					} else if result == "no-expiry" {
						body = `{"access_token":"new-fixture","token_type":"Bearer"}`
					} else {
						body = `{"access_token":"new-fixture","token_type":"Bearer","expires_in":3600,"refresh_token":"not-retained","scope":"not-retained"}`
					}
				default:
					t.Errorf("Unexpected path: %s", r.URL.Path)
				}
				if _, err := io.WriteString(w, body); err != nil {
					t.Error(err)
				}
			}))
			defer server.Close()
			values := exampleSettings()
			values["issuer"] = server.URL
			config, err := loadConnection(writeConnectionFile(t, values))
			if err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			ctx = context.WithValue(ctx, oauth2.HTTPClient, server.Client())
			err = login(ctx, config, directory, io.Discard)
			if result == "success" && err != nil {
				t.Fatal(err)
			}
			if result != "success" && (err == nil || strings.Contains(err.Error(), "private")) {
				t.Fatalf("Unexpected authorization result: %v", err)
			}
			token, readErr := readToken(directory)
			want := "at-existing-fixture"
			if result == "success" {
				want = "at-new-fixture"
			}
			if readErr != nil || token != want {
				t.Fatalf("Unexpected stored token: %s, %v", token, readErr)
			}
			data, err := os.ReadFile(filepath.Join(directory, "llmbox.auth.json"))
			if err != nil {
				t.Fatal(err)
			}
			if strings.Contains(string(data), "refresh_token") || strings.Contains(string(data), "scope") {
				t.Fatal("Unused OAuth fields persisted")
			}
		})
	}
}

func TestTokenErrorsDoNotDiscloseCache(t *testing.T) {
	for _, data := range []string{
		"private-malformed-cache",
		`{"access_token":"private-expired-token","expires_at":"1970-01-01T00:00:00Z"}`,
		`{"access_token":"private-token","expires_at":123456789}`,
	} {
		directory := t.TempDir()
		if err := os.WriteFile(filepath.Join(directory, "llmbox.auth.json"), []byte(data), 0o600); err != nil {
			t.Fatal(err)
		}
		token, err := readToken(directory)
		if token != "" || err == nil || strings.Contains(err.Error(), "private") {
			t.Fatalf("Credential disclosed: %s, %v", token, err)
		}
	}
}
