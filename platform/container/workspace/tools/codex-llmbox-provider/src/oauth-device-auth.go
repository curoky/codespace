package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/renameio/v2"
	"golang.org/x/oauth2"
)

type credential struct {
	AccessToken string    `json:"access_token"`
	ExpiresAt   time.Time `json:"expires_at"`
}

func (value credential) valid() bool {
	return value.AccessToken != "" &&
		value.ExpiresAt.After(time.Now().Add(2*time.Minute))
}

func saveCredential(directory string, value credential) error {
	if !value.valid() {
		return errors.New("invalid OAuth credentials or expiry. Existing credentials were not replaced")
	}
	value.ExpiresAt = value.ExpiresAt.UTC()
	data, err := json.Marshal(value)
	if err != nil {
		return errors.New("cannot encode OAuth credentials")
	}
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return err
	}
	if err := os.Chmod(directory, 0o700); err != nil {
		return err
	}
	// WriteFile preserves existing permissions; credentials require an explicit 0600 replacement.
	pending, err := renameio.NewPendingFile(filepath.Join(directory, "llmbox.auth.json"),
		renameio.WithTempDir(directory), renameio.WithStaticPermissions(0o600))
	if err != nil {
		return err
	}
	defer pending.Cleanup() //nolint:errcheck // Keep the write error; cleanup is a no-op after a successful publish.
	if _, err := pending.Write(append(data, '\n')); err != nil {
		return err
	}
	return pending.CloseAtomicallyReplace()
}

func readToken(directory string) (string, error) {
	data, err := os.ReadFile(filepath.Join(directory, "llmbox.auth.json"))
	if err != nil {
		return "", errors.New("cannot read OAuth credentials. Run the login command")
	}
	var value credential
	if err := json.Unmarshal(data, &value); err != nil || !value.valid() {
		return "", errors.New("stored OAuth credentials are invalid, expired or will expire soon. Run the login command")
	}
	return "at-" + strings.TrimPrefix(value.AccessToken, "at-"), nil
}

func login(ctx context.Context, config connection, directory string, output io.Writer) error {
	client := &http.Client{
		Timeout:       15 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	if ctx.Value(oauth2.HTTPClient) == nil {
		ctx = context.WithValue(ctx, oauth2.HTTPClient, client)
	}
	oauth := oauth2.Config{
		ClientID: config.ClientID, Scopes: []string{"read", "ciam.device.read"},
		Endpoint: oauth2.Endpoint{
			DeviceAuthURL: config.Issuer + "/oauth2/device/code", TokenURL: config.Issuer + "/oauth2/access_token",
			AuthStyle: oauth2.AuthStyleInParams,
		},
	}
	handle, err := oauth.DeviceAuth(ctx)
	if err != nil {
		return errors.New("device authorization failed. Check your connection and try again")
	}
	if handle.DeviceCode == "" || !handle.Expiry.After(time.Now()) {
		return errors.New("the OAuth service returned incomplete device authorization information")
	}
	verification := handle.VerificationURIComplete
	if verification == "" {
		verification = handle.VerificationURI
	}
	if _, err := fmt.Fprintf(output, "Complete OAuth authorization in your browser: %s\nUser code: %s\n", verification, handle.UserCode); err != nil {
		return err
	}
	token, err := oauth.DeviceAccessToken(ctx, handle)
	if err != nil {
		return errors.New("device authorization failed or was cancelled. Run the login command again")
	}
	if err := saveCredential(directory, credential{AccessToken: token.AccessToken, ExpiresAt: token.Expiry}); err != nil {
		return err
	}
	_, err = fmt.Fprintf(output, "OAuth credentials saved: %s\n", filepath.Join(directory, "llmbox.auth.json"))
	return err
}
