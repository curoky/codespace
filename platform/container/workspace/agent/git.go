package main

import (
	"context"
	"strings"
	"time"
)

type gitState struct {
	Unpushed    bool     `json:"unpushed"`
	Uncommitted bool     `json:"uncommitted"`
	Detail      []string `json:"detail"`
}

func (agent *workspaceAgent) gitState(ctx context.Context) (gitState, error) {
	result := gitState{Detail: []string{}}
	for _, source := range agent.sources {
		dirty, unpushed, err := agent.repositoryState(ctx, source.CheckoutPath)
		if err != nil {
			return result, err
		}
		result.Uncommitted = result.Uncommitted || len(dirty) != 0
		result.Unpushed = result.Unpushed || len(unpushed) != 0
		for _, line := range append(dirty, unpushed...) {
			if len(result.Detail) < 20 {
				result.Detail = append(result.Detail, source.CheckoutPath+": "+line)
			}
		}
	}
	return result, nil
}

func (agent *workspaceAgent) repositoryState(ctx context.Context, path string) ([]string, []string, error) {
	git := func(args ...string) (string, error) {
		return agent.run(ctx, 60*time.Second, "git", append([]string{"-C", path}, args...)...)
	}
	status, err := git("status", "--porcelain")
	if err != nil {
		return nil, nil, err
	}
	// Checkpoint refs are not user work; detached HEAD commits still are.
	revs := []string{"log", "--branches", "--tags"}
	if _, err := git("rev-parse", "--verify", "--quiet", "HEAD"); err == nil {
		revs = append(revs, "HEAD")
	}
	log, err := git(append(revs, "--not", "--remotes", "--oneline")...)
	if err != nil {
		return nil, nil, err
	}
	var dirty, unpushed []string
	if status != "" {
		dirty = strings.Split(strings.TrimSuffix(status, "\n"), "\n")
	}
	if log != "" {
		unpushed = strings.Split(strings.TrimSuffix(log, "\n"), "\n")
	}
	return dirty, unpushed, nil
}
