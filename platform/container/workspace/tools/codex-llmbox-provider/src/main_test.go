package main

import (
	"bytes"
	"context"
	"path/filepath"
	"testing"
	"time"
)

func TestTokenCommandNeedsNoConfiguration(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("XDG_STATE_HOME", t.TempDir())
	t.Setenv("CODEX_HOME", t.TempDir())
	directory := filepath.Join(home, ".codex")
	if err := saveCredential(directory, credential{"fixture-token", time.Now().Add(time.Hour)}); err != nil {
		t.Fatal(err)
	}
	var stdout, stderr bytes.Buffer
	if err := run(context.Background(), []string{"token"}, &stdout, &stderr); err != nil {
		t.Fatal(err)
	}
	if stdout.String() != "at-fixture-token\n" || stderr.Len() != 0 {
		t.Fatalf("Invalid helper output: %q, %q", stdout.String(), stderr.String())
	}
}
