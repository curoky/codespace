package main

import (
	"context"
	_ "embed"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"text/template"

	"al.essio.dev/pkg/shellescape"
)

var namePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._+-]*$`)

//go:embed launcher.bash.tmpl
var launcherSource string

var launcherTemplate = template.Must(template.New("launcher").Funcs(template.FuncMap{"quote": shellescape.Quote}).Parse(launcherSource))

type installOptions struct {
	java, root                        string
	inheritJava, extract              bool
	executables, jars, executableDirs []string
}

type launcher struct {
	command, target string
	isJar           bool
}

func installTool(ctx context.Context, requested, source string, options installOptions) ([]string, error) {
	packageName, version, ok := strings.Cut(requested, "@")
	if !ok || !namePattern.MatchString(packageName) || version == "" {
		return nil, fmt.Errorf("package must be NAME@VERSION")
	}
	var err error
	if options.java != "" {
		options.java, err = filepath.Abs(options.java)
		if err != nil {
			return nil, err
		}
		info, err := os.Stat(filepath.Join(options.java, "bin/java"))
		if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0 {
			return nil, fmt.Errorf("java executable not found under: %s", options.java)
		}
	}
	root, err := filepath.Abs(options.root)
	if err != nil {
		return nil, err
	}
	environments := filepath.Join(root, "envs")
	target := filepath.Join(environments, packageName)
	if _, err := os.Lstat(target); !errors.Is(err, os.ErrNotExist) {
		return nil, fmt.Errorf("package is already installed: %s", packageName)
	}
	if err := os.MkdirAll(environments, 0755); err != nil {
		return nil, err
	}
	temporary, err := os.MkdirTemp(environments, "."+packageName+"-")
	if err != nil {
		return nil, err
	}
	defer func() {
		if err := os.RemoveAll(temporary); err != nil {
			fmt.Fprintln(os.Stderr, "cleanup:", err)
		}
	}()
	payload := filepath.Join(temporary, "payload")
	if err := preparePayload(ctx, source, payload, options.extract); err != nil {
		return nil, err
	}
	launchers, err := discoverLaunchers(payload, options)
	if err != nil {
		return nil, err
	}
	binDir := filepath.Join(root, "bin")
	if err := os.MkdirAll(binDir, 0755); err != nil {
		return nil, err
	}
	for _, item := range launchers {
		if _, err := os.Lstat(filepath.Join(binDir, item.command)); !errors.Is(err, os.ErrNotExist) {
			return nil, fmt.Errorf("launcher already exists: %s", item.command)
		}
	}
	if err := os.Chmod(temporary, 0755); err != nil {
		return nil, err
	}
	if err := os.Rename(temporary, target); err != nil {
		return nil, err
	}
	bins := make([]string, 0, len(launchers))
	for _, item := range launchers {
		if err := writeLauncher(filepath.Join(binDir, item.command), packageName, options.java, item); err != nil {
			return nil, err
		}
		bins = append(bins, item.command)
	}
	return bins, nil
}

func discoverLaunchers(payload string, options installOptions) ([]launcher, error) {
	var launchers []launcher
	for _, group := range []struct {
		values []string
		isJar  bool
	}{{options.executables, false}, {options.jars, true}} {
		for _, value := range group.values {
			command, target, ok := strings.Cut(value, "=")
			if !ok || !namePattern.MatchString(command) {
				return nil, fmt.Errorf("launcher must be COMMAND=RELATIVE_PATH: %q", value)
			}
			if err := validateRelativePath(target); err != nil {
				return nil, err
			}
			launchers = append(launchers, launcher{command, target, group.isJar})
		}
	}
	for _, value := range options.executableDirs {
		prefix, directory, ok := strings.Cut(value, "=")
		if !ok || !namePattern.MatchString(prefix) {
			return nil, fmt.Errorf("executable directory must be PREFIX=RELATIVE_PATH: %q", value)
		}
		if err := validateRelativePath(directory); err != nil {
			return nil, err
		}
		entries, err := os.ReadDir(filepath.Join(payload, directory))
		if err != nil {
			return nil, err
		}
		for _, entry := range entries {
			info, err := entry.Info()
			if err != nil {
				return nil, err
			}
			if info.Mode().IsRegular() && info.Mode().Perm()&0111 != 0 {
				launchers = append(launchers, launcher{prefix + entry.Name(), filepath.Join(directory, entry.Name()), false})
			}
		}
	}
	if len(launchers) == 0 {
		return nil, fmt.Errorf("at least one launcher is required")
	}
	seen := make(map[string]bool)
	for _, item := range launchers {
		if seen[item.command] {
			return nil, fmt.Errorf("launcher names must be unique: %s", item.command)
		}
		seen[item.command] = true
		info, err := os.Stat(filepath.Join(payload, item.target))
		if err != nil || !info.Mode().IsRegular() {
			return nil, fmt.Errorf("launcher target does not exist: %s", item.target)
		}
		if !item.isJar && info.Mode().Perm()&0111 == 0 {
			return nil, fmt.Errorf("launcher target is not executable: %s", item.target)
		}
	}
	return launchers, nil
}

func writeLauncher(path, packageName, java string, item launcher) error {
	data := struct {
		JavaRoot, JavaBin, JavaExecutable, Target string
		IsJar                                     bool
	}{
		JavaRoot: java, JavaExecutable: "java", IsJar: item.isJar,
		Target: filepath.Join("envs", packageName, "payload", item.target),
	}
	if java != "" {
		data.JavaBin = filepath.Join(java, "bin")
		data.JavaExecutable = filepath.Join(data.JavaBin, "java")
	}
	var content strings.Builder
	if err := launcherTemplate.Execute(&content, data); err != nil {
		return err
	}
	return os.WriteFile(path, []byte(content.String()), 0755)
}
