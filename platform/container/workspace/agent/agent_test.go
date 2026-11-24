package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func executable(t *testing.T, path, content string) {
	t.Helper()
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0755))
	require.NoError(t, os.WriteFile(path, []byte(content), 0755))
}

func setupAgent(t *testing.T, sources []repositorySource, checkoutScript string) *workspaceAgent {
	t.Helper()
	home := t.TempDir()
	checkout := filepath.Join(home, "checkout")
	executable(t, checkout, checkoutScript)
	require.NoError(t, os.MkdirAll(filepath.Join(home, ".ssh"), 0700))
	require.NoError(t, os.WriteFile(filepath.Join(home, ".ssh/git_deploy_key_ed25519.pub"), []byte("ssh-ed25519 PUBLIC\n"), 0600))
	return newAgent(sources, filepath.Join(home, "open path"), home, checkout)
}

func TestBootstrapSuccessAndFailure(t *testing.T) {
	for _, failure := range []bool{false, true} {
		t.Run(fmt.Sprint(failure), func(t *testing.T) {
			script := "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" >checkout-args\n"
			if failure {
				script += "printf 'checkout failed' >&2\nexit 42\n"
			}
			sources := []repositorySource{{Type: "git", CloneURL: "git@example.com:owner/repo.git", CheckoutPath: "/workspace/repo", Args: []string{"--depth=1", "two words"}}}
			worker := setupAgent(t, sources, script)
			worker.bootstrap(t.Context())
			status, err := worker.status()
			require.NoError(t, err)
			if failure {
				require.Equal(t, "failed", status.State)
				require.Contains(t, *status.Error, "checkout failed")
			} else {
				require.Equal(t, "ready", status.State)
				require.DirExists(t, worker.openPath)
			}
			args, err := os.ReadFile(filepath.Join(worker.home, "checkout-args"))
			require.NoError(t, err)
			require.Equal(t, "git@example.com:owner/repo.git\n/workspace/repo\n--depth=1\ntwo words\n", string(args))
		})
	}
}

func TestProviderAuthorizationAndCancellation(t *testing.T) {
	for _, sourceType := range []string{"github", "gitlab"} {
		t.Run(sourceType, func(t *testing.T) {
			worker := setupAgent(t, []repositorySource{{Type: sourceType, CloneURL: "git@example.com:repo.git"}}, "#!/usr/bin/env bash\nexit 0\n")
			executable(t, filepath.Join(worker.home, "bin/git"), "#!/usr/bin/env bash\nprintf 'Permission denied (publickey)' >&2\nexit 128\n")
			t.Setenv("PATH", filepath.Join(worker.home, "bin")+":"+os.Getenv("PATH"))
			require.Error(t, worker.authorizeProvider())
			ctx, cancel := context.WithCancel(t.Context())
			defer cancel()
			done := make(chan struct{})
			go func() { defer close(done); worker.bootstrap(ctx) }()
			require.Eventually(t, func() bool { return worker.snapshot().State == "awaiting-provider" }, time.Second, time.Millisecond)
			status, err := worker.status()
			require.NoError(t, err)
			require.Equal(t, "ssh-ed25519 PUBLIC", *status.PublicKey)
			require.NoError(t, worker.authorizeProvider())
			require.NoError(t, worker.authorizeProvider())
			select {
			case <-done:
			case <-time.After(time.Second):
				t.Fatal("bootstrap did not finish")
			}
			require.Equal(t, "ready", worker.snapshot().State)
			require.NoError(t, worker.authorizeProvider())
		})
	}
	worker := setupAgent(t, []repositorySource{{Type: "github", CloneURL: "git@example.com:repo.git"}}, "#!/usr/bin/env bash\nexit 0\n")
	executable(t, filepath.Join(worker.home, "bin/git"), "#!/usr/bin/env bash\nprintf 'Permission denied (publickey)' >&2\nexit 128\n")
	t.Setenv("PATH", filepath.Join(worker.home, "bin")+":"+os.Getenv("PATH"))
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan struct{})
	go func() { defer close(done); worker.bootstrap(ctx) }()
	require.Eventually(t, func() bool { return worker.snapshot().State == "awaiting-provider" }, time.Second, time.Millisecond)
	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("bootstrap ignored cancellation")
	}
	require.Equal(t, "failed", worker.snapshot().State)
}

func TestProviderNetworkErrorAndBoundedFailure(t *testing.T) {
	worker := setupAgent(t, []repositorySource{{Type: "github", CloneURL: "git@example.com:repo.git"}}, "#!/usr/bin/env bash\nexit 0\n")
	executable(t, filepath.Join(worker.home, "bin/git"), "#!/usr/bin/env bash\nprintf 'Could not resolve hostname' >&2\nexit 128\n")
	t.Setenv("PATH", filepath.Join(worker.home, "bin")+":"+os.Getenv("PATH"))
	worker.bootstrap(t.Context())
	require.Equal(t, "failed", worker.snapshot().State)
	require.Contains(t, *worker.snapshot().Error, "Could not resolve hostname")
	require.Error(t, worker.authorizeProvider())
	executable(t, filepath.Join(worker.home, "bin/git"), "#!/usr/bin/env bash\nprintf '%s' '"+strings.Repeat("long error", 1000)+"' >&2\nexit 128\n")
	worker.bootstrap(t.Context())
	require.Len(t, []rune(*worker.snapshot().Error), 4096)
}

func TestHTTPContract(t *testing.T) {
	worker := setupAgent(t, nil, "#!/usr/bin/env bash\nexit 0\n")
	server := httptest.NewServer(worker.handler())
	defer server.Close()
	response, err := http.Get(server.URL + "/status")
	require.NoError(t, err)
	var status agentStatus
	require.NoError(t, json.NewDecoder(response.Body).Decode(&status))
	require.NoError(t, response.Body.Close())
	require.Equal(t, "starting", status.State)
	for _, endpoint := range []string{"/git-state", "/provider-ready"} {
		method := http.MethodGet
		if endpoint == "/provider-ready" {
			method = http.MethodPost
		}
		request, err := http.NewRequestWithContext(t.Context(), method, server.URL+endpoint, nil)
		require.NoError(t, err)
		response, err := http.DefaultClient.Do(request)
		require.NoError(t, err)
		require.Equal(t, 409, response.StatusCode)
		var detail struct {
			Detail string `json:"detail"`
		}
		require.NoError(t, json.NewDecoder(response.Body).Decode(&detail))
		require.NoError(t, response.Body.Close())
		require.NotEmpty(t, detail.Detail)
	}
	worker.bootstrap(t.Context())
	require.Equal(t, "ready", worker.snapshot().State)
}

func git(t *testing.T, args ...string) string {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Env = append(os.Environ(), "GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=/dev/null")
	output, err := cmd.CombinedOutput()
	require.NoError(t, err, "%s", output)
	return string(output)
}

func TestActualGitState(t *testing.T) {
	for _, state := range []string{"missing", "not-repository", "empty", "orphan", "detached", "dirty", "checkpoint", "pushed"} {
		t.Run(state, func(t *testing.T) {
			worker := setupAgent(t, nil, "#!/usr/bin/env bash\nexit 0\n")
			checkout := filepath.Join(worker.home, "repository")
			if state != "missing" {
				require.NoError(t, os.Mkdir(checkout, 0755))
			}
			if state != "missing" && state != "not-repository" {
				git(t, "init", "-q", checkout)
			}
			if state == "orphan" || state == "detached" || state == "checkpoint" || state == "pushed" {
				git(t, "-C", checkout, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-qm", "unpublished commit")
			}
			if state == "orphan" {
				git(t, "-C", checkout, "checkout", "--orphan", "new-branch")
			}
			if state == "detached" {
				git(t, "-C", checkout, "checkout", "--detach")
				for ref := range strings.SplitSeq(strings.TrimSpace(git(t, "-C", checkout, "for-each-ref", "--format=%(refname)", "refs/heads")), "\n") {
					git(t, "-C", checkout, "update-ref", "-d", ref)
				}
			}
			if state == "checkpoint" || state == "pushed" {
				git(t, "-C", checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
				if state == "checkpoint" {
					cmd := exec.Command("git", "-C", checkout, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "checkpoint")
					output, err := cmd.CombinedOutput()
					require.NoError(t, err, "%s", output)
					git(t, "-C", checkout, "update-ref", "refs/agents/checkpoints/test", strings.TrimSpace(string(output)))
				}
			}
			if state == "dirty" {
				require.NoError(t, os.WriteFile(filepath.Join(checkout, "untracked.txt"), []byte("local work"), 0644))
			}
			worker.sources = []repositorySource{{Type: "git", CheckoutPath: checkout}}
			result, err := worker.gitState(t.Context())
			if state == "missing" || state == "not-repository" {
				require.Error(t, err)
				return
			}
			require.NoError(t, err)
			require.Equal(t, state == "dirty", result.Uncommitted)
			require.Equal(t, state == "orphan" || state == "detached", result.Unpushed)
		})
	}
}

func TestCommandTimeout(t *testing.T) {
	worker := setupAgent(t, nil, "#!/usr/bin/env bash\nexit 0\n")
	_, err := worker.run(t.Context(), time.Millisecond, "sleep", "10")
	require.Error(t, err)
}

func TestInvalidBootstrapInputDoesNotCreateSocket(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("CODESPACE_OPEN_PATH", t.TempDir())
	for _, source := range []string{"null", "{}", "[] {}", `[{"type":"unsupported"}]`, `[{"type":"git","extra":true}]`} {
		t.Run(source, func(t *testing.T) {
			t.Setenv("CODESPACE_SOURCES", source)
			socket := filepath.Join(t.TempDir(), "agent.sock")
			require.Error(t, serve(t.Context(), socket, "/missing"))
			require.NoFileExists(t, socket)
		})
	}
}

func TestUnixSocketPermissionsAndShutdown(t *testing.T) {
	// macOS Unix socket paths must fit within 103 bytes.
	t.Setenv("TMPDIR", "/tmp")
	t.Setenv("HOME", t.TempDir())
	t.Setenv("CODESPACE_SOURCES", "[]")
	t.Setenv("CODESPACE_OPEN_PATH", t.TempDir())
	socket := filepath.Join(t.TempDir(), "agent.sock")
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan error, 1)
	go func() { done <- serve(ctx, socket, "/missing") }()
	defer func() {
		cancel()
		require.NoError(t, <-done)
		require.NoFileExists(t, socket)
	}()
	require.Eventually(t, func() bool {
		info, err := os.Stat(socket)
		return err == nil && info.Mode().Perm() == 0666
	}, time.Second, time.Millisecond)
}

func TestMultipleRepositoriesAndDetailLimit(t *testing.T) {
	worker := setupAgent(t, nil, "#!/usr/bin/env bash\nexit 0\n")
	for index := range 2 {
		checkout := filepath.Join(worker.home, fmt.Sprint(index))
		git(t, "init", "-q", checkout)
		worker.sources = append(worker.sources, repositorySource{Type: "git", CheckoutPath: checkout})
		if index == 0 {
			for file := range 25 {
				require.NoError(t, os.WriteFile(filepath.Join(checkout, fmt.Sprint(file)), nil, 0644))
			}
		} else {
			git(t, "-C", checkout, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "--allow-empty", "-qm", "unpublished")
		}
	}
	result, err := worker.gitState(t.Context())
	require.NoError(t, err)
	require.True(t, result.Uncommitted)
	require.True(t, result.Unpushed)
	require.Len(t, result.Detail, 20)
}
