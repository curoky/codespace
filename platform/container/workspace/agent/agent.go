package main

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type repositorySource struct {
	Type         string   `json:"type"`
	CloneURL     string   `json:"clone_url"`
	CheckoutPath string   `json:"checkout_path"`
	Args         []string `json:"args"`
}

type agentStatus struct {
	State     string  `json:"state"`
	PublicKey *string `json:"public_key"`
	Error     *string `json:"error"`
}

type workspaceAgent struct {
	sources                  []repositorySource
	openPath, home, checkout string
	mu                       sync.Mutex
	current                  agentStatus
	providerReady            chan struct{}
	providerAuthorized       bool
}

func newAgent(sources []repositorySource, openPath, home, checkout string) *workspaceAgent {
	return &workspaceAgent{
		sources: sources, openPath: openPath, home: home, checkout: checkout,
		current: agentStatus{State: "starting"}, providerReady: make(chan struct{}),
	}
}

func (agent *workspaceAgent) bootstrap(ctx context.Context) {
	if err := agent.checkoutSources(ctx); err != nil {
		detail := strings.TrimSpace(err.Error())
		if detail == "" {
			detail = "workspace bootstrap failed"
		}
		detail = string([]rune(detail)[:min(len([]rune(detail)), 4096)])
		agent.mu.Lock()
		agent.current = agentStatus{State: "failed", Error: &detail}
		agent.mu.Unlock()
		return
	}
	agent.mu.Lock()
	agent.current = agentStatus{State: "ready"}
	agent.mu.Unlock()
}

func (agent *workspaceAgent) checkoutSources(ctx context.Context) error {
	needsAuthorization := false
	for _, source := range agent.sources {
		if source.Type != "github" && source.Type != "gitlab" {
			continue
		}
		_, err := agent.run(ctx, 60*time.Second, "git", "ls-remote", source.CloneURL)
		if err == nil {
			continue
		}
		if !strings.Contains(strings.ToLower(err.Error()), "permission denied (publickey)") {
			return err
		}
		needsAuthorization = true
	}
	if needsAuthorization {
		agent.mu.Lock()
		agent.current = agentStatus{State: "awaiting-provider"}
		agent.mu.Unlock()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-agent.providerReady:
		}
		agent.mu.Lock()
		agent.current = agentStatus{State: "starting"}
		agent.mu.Unlock()
	}
	for _, source := range agent.sources {
		args := append([]string{source.CloneURL, source.CheckoutPath}, source.Args...)
		if _, err := agent.run(ctx, 900*time.Second, agent.checkout, args...); err != nil {
			return err
		}
	}
	return os.MkdirAll(agent.openPath, 0755)
}

func (agent *workspaceAgent) authorizeProvider() error {
	agent.mu.Lock()
	defer agent.mu.Unlock()
	if agent.current.State == "failed" || (agent.current.State != "awaiting-provider" && !agent.providerAuthorized) {
		return fmt.Errorf("agent state is '%s'", agent.current.State)
	}
	if !agent.providerAuthorized {
		agent.providerAuthorized = true
		close(agent.providerReady)
	}
	return nil
}

func (agent *workspaceAgent) snapshot() agentStatus {
	agent.mu.Lock()
	defer agent.mu.Unlock()
	return agent.current
}

func (agent *workspaceAgent) status() (agentStatus, error) {
	status := agent.snapshot()
	for _, source := range agent.sources {
		if source.Type == "github" || source.Type == "gitlab" {
			key, err := os.ReadFile(filepath.Join(agent.home, ".ssh/git_deploy_key_ed25519.pub"))
			if err != nil {
				return status, err
			}
			publicKey := strings.TrimSpace(string(key))
			status.PublicKey = &publicKey
			break
		}
	}
	return status, nil
}

func (agent *workspaceAgent) run(ctx context.Context, timeout time.Duration, command string, args ...string) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, command, args...)
	cmd.Dir = agent.home
	cmd.WaitDelay = time.Second
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		detail := strings.TrimSpace(stderr.String())
		if detail == "" {
			detail = strings.TrimSpace(stdout.String())
		}
		return "", fmt.Errorf("%s failed (%w): %s", filepath.Base(command), err, detail)
	}
	return stdout.String(), nil
}
