package main

import (
	"context"
	_ "embed"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
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
	java, root, artifactType, classifier, checksum string
	inheritJava, extract                           bool
	executables, mainClasses, executableDirs       []string
	repositories                                   []string
}

type launcher struct {
	command, target, mainClass string
}

func installTool(ctx context.Context, requested, source string, options installOptions) ([]string, error) {
	packageName, version, ok := strings.Cut(requested, "@")
	if !ok || !namePattern.MatchString(packageName) || version == "" {
		return nil, fmt.Errorf("package must be NAME@VERSION")
	}
	if source == "" {
		return nil, fmt.Errorf("artifact source is required")
	}
	if strings.Contains(source, "://") && options.checksum == "" {
		return nil, fmt.Errorf("URL artifacts require --checksum")
	}
	if options.checksum != "" {
		digest, err := hex.DecodeString(strings.TrimPrefix(options.checksum, "sha256:"))
		if !strings.HasPrefix(options.checksum, "sha256:") || err != nil || len(digest) != 32 {
			return nil, fmt.Errorf("checksum must be sha256:HASH")
		}
	}
	if options.extract {
		if len(options.mainClasses) != 0 || len(options.executables)+len(options.executableDirs) == 0 {
			return nil, fmt.Errorf("archives require executable launchers")
		}
	} else if len(options.mainClasses) == 0 || len(options.executables)+len(options.executableDirs) != 0 {
		return nil, fmt.Errorf("JVM applications require --main launchers")
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
	files, err := fetchArtifacts(ctx, requested, source, options)
	if err != nil {
		return nil, err
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
	var classpath []string
	if options.extract {
		if len(files) != 1 {
			return nil, fmt.Errorf("archive installation requires exactly one artifact")
		}
		if err := extractArchive(ctx, files[0], payload); err != nil {
			return nil, err
		}
	} else {
		classpath, err = prepareLibraries(ctx, temporary, files)
		if err != nil {
			return nil, err
		}
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
		if err := writeLauncher(filepath.Join(binDir, item.command), packageName, options.java, item, classpath); err != nil {
			return nil, err
		}
		bins = append(bins, item.command)
	}
	return bins, nil
}

func discoverLaunchers(payload string, options installOptions) ([]launcher, error) {
	var launchers []launcher
	for _, value := range options.executables {
		command, target, ok := strings.Cut(value, "=")
		if !ok || !namePattern.MatchString(command) {
			return nil, fmt.Errorf("launcher must be COMMAND=RELATIVE_PATH: %q", value)
		}
		if err := validateRelativePath(target); err != nil {
			return nil, err
		}
		launchers = append(launchers, launcher{command: command, target: target})
	}
	for _, value := range options.mainClasses {
		command, class, ok := strings.Cut(value, "=")
		if !ok || !namePattern.MatchString(command) || class == "" {
			return nil, fmt.Errorf("main launcher must be COMMAND=MAIN_CLASS: %q", value)
		}
		launchers = append(launchers, launcher{command: command, mainClass: class})
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
				launchers = append(launchers, launcher{command: prefix + entry.Name(), target: filepath.Join(directory, entry.Name())})
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
		if item.mainClass != "" {
			continue
		}
		info, err := os.Stat(filepath.Join(payload, item.target))
		if err != nil || !info.Mode().IsRegular() {
			return nil, fmt.Errorf("launcher target does not exist: %s", item.target)
		}
		if info.Mode().Perm()&0111 == 0 {
			return nil, fmt.Errorf("launcher target is not executable: %s", item.target)
		}
	}
	return launchers, nil
}

func writeLauncher(path, packageName, java string, item launcher, classpath []string) error {
	data := struct {
		JavaRoot, Target, MainClass string
		ClassPath                   []string
	}{
		JavaRoot: java, MainClass: item.mainClass,
		Target: filepath.Join("envs", packageName, "payload", item.target),
	}
	for _, entry := range classpath {
		data.ClassPath = append(data.ClassPath, filepath.Join("envs", packageName, entry))
	}
	var content strings.Builder
	if err := launcherTemplate.Execute(&content, data); err != nil {
		return err
	}
	return os.WriteFile(path, []byte(content.String()), 0755)
}

func prepareLibraries(ctx context.Context, directory string, files []string) ([]string, error) {
	var classpath []string
	for index, file := range files {
		if filepath.Ext(file) != ".jar" {
			return nil, fmt.Errorf("classpath artifact is not a JAR: %s", file)
		}
		// Preserve resolver order without colliding on equal filenames from different groups.
		relative := filepath.Join("lib", fmt.Sprint(index), filepath.Base(file))
		parent := filepath.Dir(filepath.Join(directory, relative))
		if err := os.MkdirAll(parent, 0755); err != nil {
			return nil, err
		}
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		input, err := os.Open(file)
		if err != nil {
			return nil, err
		}
		output, err := os.OpenFile(filepath.Join(directory, relative), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0644)
		if err != nil {
			return nil, errors.Join(err, input.Close())
		}
		_, err = io.Copy(output, input)
		if err := errors.Join(err, input.Close(), output.Close()); err != nil {
			return nil, err
		}
		classpath = append(classpath, relative)
	}
	return classpath, nil
}
