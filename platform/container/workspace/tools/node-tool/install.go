package main

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"text/template"

	"al.essio.dev/pkg/shellescape"
)

//go:embed launcher.bash.tmpl
var launcherSource string

var launcherTemplate = template.Must(template.New("launcher").Funcs(template.FuncMap{"quote": shellescape.Quote}).Parse(launcherSource))

type installedTool struct {
	name, version string
	bins          []string
}

type installOptions struct {
	node, root, registry string
	allowBuild           []string
}

func installTool(ctx context.Context, requested string, options installOptions) (installedTool, error) {
	node, err := filepath.Abs(filepath.Join(options.node, "bin/node"))
	if err != nil {
		return installedTool{}, err
	}
	info, err := os.Stat(node)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0 {
		return installedTool{}, fmt.Errorf("node executable not found or not executable: %s", node)
	}
	pnpm, err := exec.LookPath("pnpm")
	if err != nil {
		return installedTool{}, fmt.Errorf("pnpm: %w", err)
	}
	root, err := filepath.Abs(options.root)
	if err != nil {
		return installedTool{}, err
	}
	if err := os.MkdirAll(filepath.Join(root, "store"), 0755); err != nil {
		return installedTool{}, err
	}
	temporary, err := os.MkdirTemp(root, ".node-tool-")
	if err != nil {
		return installedTool{}, err
	}
	defer func() {
		if err := os.RemoveAll(temporary); err != nil {
			fmt.Fprintln(os.Stderr, "cleanup:", err)
		}
	}()
	if err := os.WriteFile(filepath.Join(temporary, "package.json"), []byte("{\"private\":true}\n"), 0644); err != nil {
		return installedTool{}, err
	}
	args := []string{"--dir", temporary, "--store-dir", filepath.Join(root, "store")}
	if options.registry != "" {
		args = append(args, "--registry", options.registry)
	}
	args = append(args, "add", "--save-exact")
	for _, packageName := range options.allowBuild {
		args = append(args, "--allow-build", packageName)
	}
	args = append(args, requested)
	cmd := exec.CommandContext(ctx, pnpm, args...)
	cmd.Env = append(os.Environ(), "PATH="+filepath.Dir(node)+string(os.PathListSeparator)+os.Getenv("PATH"), "CI=true", "NO_UPDATE_NOTIFIER=1")
	cmd.Stdin, cmd.Stdout, cmd.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		return installedTool{}, fmt.Errorf("pnpm failed: %w", err)
	}
	tool, err := installedPackage(temporary)
	if err != nil {
		return installedTool{}, err
	}
	if err := exposeTool(root, temporary, node, tool); err != nil {
		return installedTool{}, err
	}
	return tool, nil
}

func exposeTool(root, temporary, node string, tool installedTool) error {
	// Keep the pnpm project portable, including scoped package names.
	encodedName := url.QueryEscape(tool.name)
	environment := filepath.Join(root, "envs", encodedName)
	if _, err := os.Lstat(environment); !errors.Is(err, os.ErrNotExist) {
		return fmt.Errorf("%s is already installed", tool.name)
	}
	binDir := filepath.Join(root, "bin")
	if err := os.MkdirAll(binDir, 0755); err != nil {
		return err
	}
	for _, bin := range tool.bins {
		if !filepath.IsLocal(bin) || filepath.Base(bin) != bin {
			return fmt.Errorf("cannot expose executable: %s", bin)
		}
		if _, err := os.Lstat(filepath.Join(binDir, bin)); !errors.Is(err, os.ErrNotExist) {
			return fmt.Errorf("cannot expose executable: %s", bin)
		}
		if info, err := os.Stat(filepath.Join(temporary, "node_modules/.bin", bin)); err != nil || !info.Mode().IsRegular() {
			return fmt.Errorf("pnpm did not install executable: %s", bin)
		}
	}
	if err := os.MkdirAll(filepath.Dir(environment), 0755); err != nil {
		return err
	}
	if err := os.Chmod(temporary, 0755); err != nil {
		return err
	}
	if err := os.Rename(temporary, environment); err != nil {
		return err
	}
	for _, bin := range tool.bins {
		target := filepath.Join("envs", encodedName, "node_modules/.bin", bin)
		var content strings.Builder
		if err := launcherTemplate.Execute(&content, struct{ NodeBin, Executable string }{filepath.Dir(node), target}); err != nil {
			return err
		}
		if err := os.WriteFile(filepath.Join(binDir, bin), []byte(content.String()), 0755); err != nil {
			return err
		}
	}
	return nil
}

func installedPackage(directory string) (installedTool, error) {
	data, err := os.ReadFile(filepath.Join(directory, "package.json"))
	if err != nil {
		return installedTool{}, err
	}
	var project struct {
		Dependencies map[string]string `json:"dependencies"`
	}
	if err := json.Unmarshal(data, &project); err != nil {
		return installedTool{}, err
	}
	if len(project.Dependencies) != 1 {
		return installedTool{}, fmt.Errorf("pnpm did not install exactly one dependency")
	}
	var name string
	for name = range project.Dependencies {
	}
	if !filepath.IsLocal(name) || slices.Contains(strings.Split(name, "/"), "..") {
		return installedTool{}, fmt.Errorf("invalid dependency name: %s", name)
	}
	data, err = os.ReadFile(filepath.Join(directory, "node_modules", name, "package.json"))
	if err != nil {
		return installedTool{}, err
	}
	var manifest struct {
		Version string          `json:"version"`
		Bin     json.RawMessage `json:"bin"`
	}
	if err := json.Unmarshal(data, &manifest); err != nil {
		return installedTool{}, err
	}
	if manifest.Version == "" {
		return installedTool{}, fmt.Errorf("%s has no valid version", name)
	}
	var singleBin string
	var packageBins map[string]string
	var bins []string
	if json.Unmarshal(manifest.Bin, &singleBin) == nil && singleBin != "" {
		bins = []string{filepath.Base(name)}
	} else if err := json.Unmarshal(manifest.Bin, &packageBins); err == nil {
		for bin := range packageBins {
			bins = append(bins, bin)
		}
		slices.Sort(bins)
	}
	if len(bins) == 0 {
		return installedTool{}, fmt.Errorf("%s does not expose any executables", name)
	}
	return installedTool{name, manifest.Version, bins}, nil
}
