package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"al.essio.dev/pkg/shellescape"
	"github.com/stretchr/testify/require"
)

func executable(t *testing.T, path, content string) {
	t.Helper()
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0755))
	require.NoError(t, os.WriteFile(path, []byte(content), 0755))
}

func setupPackage(t *testing.T, name string, bins any) string {
	t.Helper()
	home := filepath.Join(t.TempDir(), "client's home")
	executable(t, filepath.Join(home, ".local/opt/node/nodejs26/bin/node"), "#!/usr/bin/env bash\nprintf 'bound-node:%s\\n' \"$*\"\n")
	manifest, err := json.Marshal(map[string]any{"version": "1.0.0", "bin": bins})
	require.NoError(t, err)
	project, err := json.Marshal(map[string]any{"private": true, "dependencies": map[string]string{name: "1.0.0"}})
	require.NoError(t, err)
	binDirectory := filepath.Join(t.TempDir(), "bin")
	var commands []string
	switch values := bins.(type) {
	case string:
		commands = []string{filepath.Base(name)}
	case map[string]string:
		for name := range values {
			commands = append(commands, name)
		}
	}
	script := fmt.Sprintf(`#!/usr/bin/env bash
set -euo pipefail
directory="$2"
printf '%%s\n' "$@" >"$directory/pnpm-args"
printf '%%s\n' "$PATH" "$CI" "$NO_UPDATE_NOTIFIER" >"$directory/pnpm-env"
printf '%%s\n' %s >"$directory/package.json"
mkdir -p "$directory/node_modules/"%s "$directory/node_modules/.bin"
printf '%%s\n' %s >"$directory/node_modules/"%s"/package.json"
`, shellescape.Quote(string(project)), shellescape.Quote(name), shellescape.Quote(string(manifest)), shellescape.Quote(name))
	for _, name := range commands {
		script += fmt.Sprintf("printf '%%s\\n' '#!/usr/bin/env bash' 'exec node --from-tool \"$@\"' >\"$directory/node_modules/.bin/\"%s\nchmod 0755 \"$directory/node_modules/.bin/\"%s\n", shellescape.Quote(name), shellescape.Quote(name))
	}
	executable(t, filepath.Join(binDirectory, "pnpm"), script)
	t.Setenv("PATH", binDirectory+string(os.PathListSeparator)+os.Getenv("PATH"))
	return home
}

func invoke(t *testing.T, home string, args ...string) (string, error) {
	t.Helper()
	app := command(home)
	var output bytes.Buffer
	app.SetOut(&output)
	app.SetErr(&output)
	app.SetArgs(args)
	err := app.ExecuteContext(t.Context())
	return output.String(), err
}

func TestInstallBindingAndRelocation(t *testing.T) {
	for _, scoped := range []bool{false, true} {
		t.Run(fmt.Sprint(scoped), func(t *testing.T) {
			name := "sample"
			if scoped {
				name = "@example/sample"
			}
			home := setupPackage(t, name, "cli.js")
			root := filepath.Join(home, ".local/opt/node/tools")
			output, err := invoke(t, home, "install", name+"@1.0.0")
			require.NoError(t, err)
			require.Equal(t, "installed "+name+"@1.0.0: sample\n", output)
			info, err := os.Stat(filepath.Join(root, "envs", name))
			require.NoError(t, err)
			require.Equal(t, os.FileMode(0755), info.Mode().Perm())
			relocated := filepath.Join(t.TempDir(), "relocated tools")
			require.NoError(t, os.Rename(root, relocated))
			cmd := exec.Command(filepath.Join(relocated, "bin/sample"), "two words", "it's quoted", "--version")
			cmd.Env = []string{"PATH=/usr/bin:/bin"}
			result, err := cmd.CombinedOutput()
			require.NoError(t, err, "%s", result)
			require.Equal(t, "bound-node:--from-tool two words it's quoted --version\n", string(result))
		})
	}
}

func TestScopedPackagesShareNamespace(t *testing.T) {
	root := filepath.Join(t.TempDir(), "tools")
	for _, name := range []string{"@example/first", "@example/second"} {
		home := setupPackage(t, name, "cli.js")
		_, err := invoke(t, home, "install", name, "--root", root)
		require.NoError(t, err)
		require.FileExists(t, filepath.Join(root, "envs", name, "package.json"))
		cmd := exec.Command(filepath.Join(root, "bin", filepath.Base(name)), "--version")
		result, err := cmd.CombinedOutput()
		require.NoError(t, err, "%s", result)
		require.Equal(t, "bound-node:--from-tool --version\n", string(result))
	}
	entries, err := os.ReadDir(filepath.Join(root, "envs"))
	require.NoError(t, err)
	require.Len(t, entries, 1)
	require.Equal(t, "@example", entries[0].Name())
}

func TestPnpmInputsAndMultipleBins(t *testing.T) {
	home := setupPackage(t, "sample", map[string]string{"second": "second.js", "first": "first.js"})
	output, err := invoke(t, home, "install", "sample@1.0.0", "--registry", "https://registry.example.com", "--allow-build", "@example/cli", "--allow-build", "protobufjs")
	require.NoError(t, err)
	require.Equal(t, "installed sample@1.0.0: first, second\n", output)
	environment := filepath.Join(home, ".local/opt/node/tools/envs/sample")
	arguments, err := os.ReadFile(filepath.Join(environment, "pnpm-args"))
	require.NoError(t, err)
	require.True(t, strings.HasSuffix(string(arguments), "--registry\nhttps://registry.example.com\nadd\n--save-exact\n--allow-build\n@example/cli\n--allow-build\nprotobufjs\nsample@1.0.0\n"))
	env, err := os.ReadFile(filepath.Join(environment, "pnpm-env"))
	require.NoError(t, err)
	require.True(t, strings.HasPrefix(string(env), filepath.Join(home, ".local/opt/node/nodejs26/bin")+":"))
	require.True(t, strings.HasSuffix(string(env), "\ntrue\n1\n"))
}

func TestExplicitRuntimePreservesSymlinkBinding(t *testing.T) {
	home := setupPackage(t, "sample", "cli.js")
	alias := filepath.Join(t.TempDir(), "selected node")
	require.NoError(t, os.Symlink(filepath.Join(home, ".local/opt/node/nodejs26"), alias))
	_, err := invoke(t, home, "install", "sample", "--node", alias)
	require.NoError(t, err)
	launcher, err := os.ReadFile(filepath.Join(home, ".local/opt/node/tools/bin/sample"))
	require.NoError(t, err)
	require.Contains(t, string(launcher), shellescape.Quote(filepath.Join(alias, "bin")))
}

func TestRejectExistingPackageAndLauncher(t *testing.T) {
	for _, test := range []struct{ name, existing string }{
		{"sample", "envs/sample"},
		{"sample", "bin/sample"},
		{"@example/sample", "envs/@example/sample"},
		{"@example/sample", "bin/sample"},
	} {
		t.Run(test.name+"/"+test.existing, func(t *testing.T) {
			home := setupPackage(t, test.name, "cli.js")
			root := filepath.Join(home, ".local/opt/node/tools")
			path := filepath.Join(root, test.existing)
			executable(t, path, "original")
			_, err := invoke(t, home, "install", test.name)
			require.Error(t, err)
			contents, err := os.ReadFile(path)
			require.NoError(t, err)
			require.Equal(t, "original", string(contents))
			if test.existing == "bin/sample" {
				require.NoFileExists(t, filepath.Join(root, "envs", test.name, "package.json"))
			}
			entries, err := os.ReadDir(root)
			require.NoError(t, err)
			for _, entry := range entries {
				require.False(t, strings.HasPrefix(entry.Name(), ".node-tool-"))
			}
		})
	}
}

func TestRejectMissingDependenciesAndEmptyBins(t *testing.T) {
	for _, failure := range []string{"node", "pnpm", "bins"} {
		t.Run(failure, func(t *testing.T) {
			home := setupPackage(t, "sample", map[string]string{})
			if failure == "node" {
				require.NoError(t, os.Remove(filepath.Join(home, ".local/opt/node/nodejs26/bin/node")))
			}
			if failure == "pnpm" {
				t.Setenv("PATH", t.TempDir())
			}
			_, err := invoke(t, home, "install", "sample")
			require.Error(t, err)
			require.NoFileExists(t, filepath.Join(home, ".local/opt/node/tools/envs/sample/package.json"))
		})
	}
}
