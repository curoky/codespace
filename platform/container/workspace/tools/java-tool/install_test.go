package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"al.essio.dev/pkg/shellescape"
	"github.com/stretchr/testify/require"
)

func executable(t *testing.T, path, content string) {
	t.Helper()
	require.NoError(t, os.MkdirAll(filepath.Dir(path), 0755))
	require.NoError(t, os.WriteFile(path, []byte(content), 0755))
}

func setupJava(t *testing.T) string {
	t.Helper()
	home := filepath.Join(t.TempDir(), "client's home")
	executable(t, filepath.Join(home, ".local/opt/java/openjdk27/bin/java"), "#!/usr/bin/env bash\nprintf 'java-home:%s\\nargs:%s\\n' \"$JAVA_HOME\" \"$*\"\n")
	return home
}

func artifacts(t *testing.T, files ...string) string {
	t.Helper()
	directory := t.TempDir()
	listing := filepath.Join(directory, "files")
	require.NoError(t, os.WriteFile(listing, []byte(strings.Join(files, "\n")+"\n"), 0644))
	executable(t, filepath.Join(directory, "cs"), "#!/usr/bin/env bash\nset -euo pipefail\ncat "+shellescape.Quote(listing)+"\n")
	t.Setenv("PATH", directory+string(os.PathListSeparator)+os.Getenv("PATH"))
	return "org.example:distribution:1"
}

func makeArchive(t *testing.T, format string, names []string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "distribution."+format)
	output, err := os.Create(path)
	require.NoError(t, err)
	content := "#!/usr/bin/env bash\nprintf 'java-home:%s\\nargs:%s\\n' \"${JAVA_HOME:-}\" \"$*\"\n"
	if format == "zip" {
		archive := zip.NewWriter(output)
		for _, name := range names {
			header := &zip.FileHeader{Name: name, Method: zip.Deflate}
			header.SetMode(0755)
			entry, err := archive.CreateHeader(header)
			require.NoError(t, err)
			_, err = entry.Write([]byte(content))
			require.NoError(t, err)
		}
		require.NoError(t, archive.Close())
	} else {
		compressed := gzip.NewWriter(output)
		archive := tar.NewWriter(compressed)
		for _, name := range names {
			require.NoError(t, archive.WriteHeader(&tar.Header{Name: name, Mode: 0755, Size: int64(len(content)), Typeflag: tar.TypeReg}))
			_, err := archive.Write([]byte(content))
			require.NoError(t, err)
		}
		require.NoError(t, archive.Close())
		require.NoError(t, compressed.Close())
	}
	require.NoError(t, output.Close())
	return path
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

func TestArchiveBindingAndRelocation(t *testing.T) {
	for _, format := range []string{"zip", "tar.gz"} {
		t.Run(format, func(t *testing.T) {
			home := setupJava(t)
			archive := makeArchive(t, format, []string{"payload/bin/sample"})
			output, err := invoke(t, home, "install", "sample@1.0", artifacts(t, archive), "--extract", "--executable", "sample=bin/sample")
			require.NoError(t, err)
			require.Equal(t, "installed sample@1.0: sample\n", output)
			root := filepath.Join(home, ".local/opt/java/tools")
			info, err := os.Stat(filepath.Join(root, "envs/sample"))
			require.NoError(t, err)
			require.Equal(t, os.FileMode(0755), info.Mode().Perm())
			entries, err := os.ReadDir(filepath.Join(root, "envs/sample"))
			require.NoError(t, err)
			require.Len(t, entries, 1)
			require.Equal(t, "payload", entries[0].Name())
			relocated := filepath.Join(t.TempDir(), "relocated tools")
			require.NoError(t, os.Rename(root, relocated))
			cmd := exec.Command(filepath.Join(relocated, "bin/sample"), "two words", "it's quoted")
			cmd.Env = []string{"PATH=/usr/bin:/bin", "JAVA_HOME=/missing"}
			result, err := cmd.CombinedOutput()
			require.NoError(t, err, "%s", result)
			require.Equal(t, "java-home:"+filepath.Join(home, ".local/opt/java/openjdk27")+"\nargs:two words it's quoted\n", string(result))
		})
	}
}

func TestClasspathLaunchers(t *testing.T) {
	for _, inherit := range []bool{false, true} {
		t.Run(fmt.Sprint(inherit), func(t *testing.T) {
			home := setupJava(t)
			source := filepath.Join(t.TempDir(), "language server.jar")
			require.NoError(t, os.WriteFile(source, []byte("jar payload"), 0600))
			args := []string{"install", "server@1", artifacts(t, source), "--main", "server=org.example.Main"}
			if inherit {
				args = append(args, "--inherit-java")
			}
			_, err := invoke(t, home, args...)
			require.NoError(t, err)
			root := filepath.Join(home, ".local/opt/java/tools")
			jar := filepath.Join(root, "envs/server/lib/0/language server.jar")
			info, err := os.Stat(jar)
			require.NoError(t, err)
			require.Equal(t, os.FileMode(0644), info.Mode().Perm())
			jar, err = filepath.EvalSymlinks(jar)
			require.NoError(t, err)
			linkedRoot := filepath.Join(t.TempDir(), "linked tools")
			require.NoError(t, os.Symlink(root, linkedRoot))
			cmd := exec.Command(filepath.Join(linkedRoot, "bin/server"), "--stdio")
			java := filepath.Join(home, ".local/opt/java/openjdk27")
			cmd.Env = []string{"PATH=" + filepath.Join(java, "bin") + ":/usr/bin:/bin", "JAVA_HOME=/project/jdk"}
			result, err := cmd.CombinedOutput()
			require.NoError(t, err, "%s", result)
			if inherit {
				java = "/project/jdk"
			}
			require.Equal(t, "java-home:"+java+"\nargs:-cp "+jar+" org.example.Main --stdio\n", string(result))
			if !inherit {
				require.NoError(t, os.Remove(filepath.Join(java, "bin/java")))
				fallback := t.TempDir()
				executable(t, filepath.Join(fallback, "java"), "#!/usr/bin/env bash\nexit 0\n")
				cmd = exec.Command(filepath.Join(linkedRoot, "bin/server"))
				cmd.Env = []string{"PATH=" + fallback + ":/usr/bin:/bin"}
				require.Error(t, cmd.Run())
			}
		})
	}
}

func TestExecutableDirectoryAndInheritance(t *testing.T) {
	home := setupJava(t)
	archive := makeArchive(t, "zip", []string{"sample/support/analyze", "sample/support/inspect"})
	output, err := invoke(t, home, "install", "sample@1", artifacts(t, archive), "--extract", "--inherit-java", "--executable-dir", "sample-=support")
	require.NoError(t, err)
	require.Equal(t, "installed sample@1: sample-analyze, sample-inspect\n", output)
	cmd := exec.Command(filepath.Join(home, ".local/opt/java/tools/bin/sample-analyze"), "build")
	cmd.Env = []string{"PATH=/usr/bin:/bin", "JAVA_HOME=/project/jdk"}
	result, err := cmd.CombinedOutput()
	require.NoError(t, err, "%s", result)
	require.Equal(t, "java-home:/project/jdk\nargs:build\n", string(result))
}

func TestExplicitRuntimePreservesSymlinkBinding(t *testing.T) {
	home := setupJava(t)
	alias := filepath.Join(t.TempDir(), "selected java")
	require.NoError(t, os.Symlink(filepath.Join(home, ".local/opt/java/openjdk27"), alias))
	archive := makeArchive(t, "zip", []string{"sample/bin/sample"})
	_, err := invoke(t, home, "install", "sample@1", artifacts(t, archive), "--extract", "--executable", "sample=bin/sample", "--java", alias)
	require.NoError(t, err)
	launcher, err := os.ReadFile(filepath.Join(home, ".local/opt/java/tools/bin/sample"))
	require.NoError(t, err)
	require.Contains(t, string(launcher), "JAVA_HOME="+shellescape.Quote(alias))
}

func TestRejectUnsafePathsAndInvalidLayout(t *testing.T) {
	for _, path := range []string{"../escape", "/absolute", "sample/../escape", "flat-file"} {
		t.Run(path, func(t *testing.T) {
			home := setupJava(t)
			archive := makeArchive(t, "zip", []string{path})
			_, err := invoke(t, home, "install", "sample@1", artifacts(t, archive), "--extract", "--executable", "sample=bin/sample")
			require.Error(t, err)
			require.NoFileExists(t, filepath.Join(home, ".local/opt/java/tools/envs/sample/payload"))
		})
	}
}

func TestRejectArchiveLinks(t *testing.T) {
	for _, kind := range []byte{tar.TypeSymlink, tar.TypeLink} {
		t.Run(fmt.Sprint(kind), func(t *testing.T) {
			home := setupJava(t)
			source := filepath.Join(t.TempDir(), "unsafe.tar")
			file, err := os.Create(source)
			require.NoError(t, err)
			archive := tar.NewWriter(file)
			require.NoError(t, archive.WriteHeader(&tar.Header{Name: "sample/link", Typeflag: kind, Linkname: "/tmp/escape"}))
			require.NoError(t, archive.Close())
			require.NoError(t, file.Close())
			_, err = invoke(t, home, "install", "sample@1", artifacts(t, source), "--extract", "--executable", "sample=link")
			require.ErrorContains(t, err, "unsupported entry")
		})
	}
}

func TestRejectConflictsAndInvalidLaunchers(t *testing.T) {
	for _, failure := range []string{"package", "launcher", "duplicate", "path", "nonexistent", "runtime"} {
		t.Run(failure, func(t *testing.T) {
			home := setupJava(t)
			archive := makeArchive(t, "zip", []string{"sample/bin/sample"})
			root := filepath.Join(home, ".local/opt/java/tools")
			args := []string{"install", "sample@1", artifacts(t, archive), "--extract", "--executable", "sample=bin/sample"}
			switch failure {
			case "package":
				require.NoError(t, os.MkdirAll(filepath.Join(root, "envs/sample"), 0755))
			case "launcher":
				executable(t, filepath.Join(root, "bin/sample"), "original")
			case "duplicate":
				args = append(args, "--executable", "sample=bin/sample")
			case "path":
				args = append(args, "--executable", "other=../outside")
			case "nonexistent":
				args = append(args, "--executable", "other=missing")
			case "runtime":
				args = append(args, "--java", "/missing", "--inherit-java")
			}
			_, err := invoke(t, home, args...)
			require.Error(t, err)
			require.NoFileExists(t, filepath.Join(root, "envs/sample/payload/bin/sample"))
		})
	}
}

func TestLibrariesPreserveOrderWithoutCacheDependency(t *testing.T) {
	home := setupJava(t)
	var files []string
	for _, content := range []string{"app", "dependency"} {
		path := filepath.Join(t.TempDir(), "same-name.jar")
		require.NoError(t, os.WriteFile(path, []byte(content), 0644))
		files = append(files, path)
	}
	_, err := invoke(t, home, "install", "app@1", artifacts(t, files...), "--main", "app=org.example.Main")
	require.NoError(t, err)
	root := filepath.Join(home, ".local/opt/java/tools")
	relocated := filepath.Join(t.TempDir(), "relocated tools")
	require.NoError(t, os.Rename(root, relocated))
	var classpath []string
	for index, file := range files {
		path := filepath.Join(relocated, "envs/app/lib", fmt.Sprint(index), "same-name.jar")
		data, err := os.ReadFile(path)
		require.NoError(t, err)
		require.Equal(t, []byte([]string{"app", "dependency"}[index]), data)
		require.NoError(t, os.Remove(file))
		path, err = filepath.EvalSymlinks(path)
		require.NoError(t, err)
		classpath = append(classpath, path)
	}
	cmd := exec.Command(filepath.Join(relocated, "bin/app"), "two words", "it's quoted")
	cmd.Env = []string{"PATH=/usr/bin:/bin", "JAVA_HOME=/missing"}
	result, err := cmd.CombinedOutput()
	require.NoError(t, err, "%s", result)
	require.Equal(t, "java-home:"+filepath.Join(home, ".local/opt/java/openjdk27")+"\nargs:-cp "+strings.Join(classpath, ":")+" org.example.Main two words it's quoted\n", string(result))
}

func TestURLChecksumBeforePublishing(t *testing.T) {
	for _, valid := range []bool{true, false} {
		t.Run(fmt.Sprint(valid), func(t *testing.T) {
			home := setupJava(t)
			archive := makeArchive(t, "zip", []string{"sample/bin/sample"})
			artifacts(t, archive)
			data, err := os.ReadFile(archive)
			require.NoError(t, err)
			checksum := fmt.Sprintf("sha256:%x", sha256.Sum256(data))
			if !valid {
				checksum = "sha256:" + strings.Repeat("0", 64)
			}
			_, err = invoke(t, home, "install", "sample@1", "https://example.com/sample.zip", "--checksum", checksum, "--extract", "--executable", "sample=bin/sample")
			if valid {
				require.NoError(t, err)
			} else {
				require.ErrorContains(t, err, "checksum mismatch")
				require.NoDirExists(t, filepath.Join(home, ".local/opt/java/tools/envs/sample"))
			}
		})
	}
}

func TestFetchCancellation(t *testing.T) {
	home := setupJava(t)
	directory := t.TempDir()
	executable(t, filepath.Join(directory, "cs"), "#!/usr/bin/env bash\nexec sleep 30\n")
	t.Setenv("PATH", directory+string(os.PathListSeparator)+os.Getenv("PATH"))
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Millisecond)
	defer cancel()
	app := command(home)
	app.SetArgs([]string{"install", "sample@1", "org.example:sample:1", "--main", "sample=org.example.Main"})
	require.Error(t, app.ExecuteContext(ctx))
	require.NoDirExists(t, filepath.Join(home, ".local/opt/java/tools"))
}
