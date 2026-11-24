package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

func main() {
	socketPath := flag.String("socket", "/run/codespace-control/agent.sock", "Unix socket path")
	checkout := flag.String("checkout", "/opt/codespace/bin/checkout", "Checkout helper executable")
	flag.Parse()
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	if err := serve(ctx, *socketPath, *checkout); err != nil {
		slog.Error("workspace agent failed", "error", err)
		os.Exit(1)
	}
}

func serve(ctx context.Context, socketPath, checkout string) error {
	home, err := os.UserHomeDir()
	if err != nil {
		return err
	}
	var sources []repositorySource
	decoder := json.NewDecoder(strings.NewReader(os.Getenv("CODESPACE_SOURCES")))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&sources); err != nil {
		return fmt.Errorf("CODESPACE_SOURCES: %w", err)
	}
	if sources == nil || decoder.Decode(&struct{}{}) != io.EOF {
		return fmt.Errorf("CODESPACE_SOURCES must contain one JSON array")
	}
	for _, source := range sources {
		if source.Type != "git" && source.Type != "github" && source.Type != "gitlab" {
			return fmt.Errorf("invalid repository source type: %q", source.Type)
		}
	}
	openPath, ok := os.LookupEnv("CODESPACE_OPEN_PATH")
	if !ok {
		return fmt.Errorf("CODESPACE_OPEN_PATH is required")
	}
	if err := os.Remove(socketPath); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	listener, err := net.Listen("unix", socketPath)
	if err != nil {
		return err
	}
	defer func() {
		if err := listener.Close(); err != nil && !errors.Is(err, net.ErrClosed) {
			slog.Error("close agent socket failed", "error", err)
		}
	}()
	// Host-side OpenSSH access is restricted by the mounted parent directory, not the socket UID.
	if err := os.Chmod(socketPath, 0666); err != nil {
		return err
	}
	worker := newAgent(sources, openPath, home, checkout)
	bootstrapCtx, stopBootstrap := context.WithCancel(ctx)
	defer stopBootstrap()
	bootstrapDone := make(chan struct{})
	go func() {
		defer close(bootstrapDone)
		worker.bootstrap(bootstrapCtx)
	}()
	server := &http.Server{
		Handler: worker.handler(), ReadHeaderTimeout: 5 * time.Second,
		BaseContext: func(net.Listener) context.Context { return bootstrapCtx },
	}
	shutdownDone := make(chan struct{})
	go func() {
		defer close(shutdownDone)
		<-bootstrapCtx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdownCtx); err != nil {
			slog.Error("agent shutdown failed", "error", err)
			if err := server.Close(); err != nil {
				slog.Error("agent close failed", "error", err)
			}
		}
	}()
	err = server.Serve(listener)
	stopBootstrap()
	<-bootstrapDone
	<-shutdownDone
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}

func (agent *workspaceAgent) handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /status", func(w http.ResponseWriter, r *http.Request) {
		status, err := agent.status()
		if err != nil {
			writeJSON(w, 500, apiError{"cannot read deploy public key"})
			return
		}
		writeJSON(w, 200, status)
	})
	mux.HandleFunc("GET /git-state", func(w http.ResponseWriter, r *http.Request) {
		if len(agent.sources) == 0 {
			writeJSON(w, 409, apiError{"empty workspace has no Git state"})
			return
		}
		state := agent.snapshot().State
		if state != "ready" {
			writeJSON(w, 409, apiError{fmt.Sprintf("agent state is '%s'", state)})
			return
		}
		stateResult, err := agent.gitState(r.Context())
		if err != nil {
			writeJSON(w, 500, apiError{"cannot inspect repository Git state"})
			return
		}
		writeJSON(w, 200, stateResult)
	})
	mux.HandleFunc("POST /provider-ready", func(w http.ResponseWriter, r *http.Request) {
		if err := agent.authorizeProvider(); err != nil {
			writeJSON(w, 409, apiError{err.Error()})
			return
		}
		writeJSON(w, 200, nil)
	})
	return mux
}

type apiError struct {
	Detail string `json:"detail"`
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(value); err != nil {
		slog.Error("write agent response failed", "error", err)
	}
}
