package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"testing"

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
			archive := makeArchive(t, format, []string{"sample-1.0/bin/sample"})
			output, err := invoke(t, home, "install", "sample@1.0", archive, "--extract", "--executable", "sample=bin/sample")
			require.NoError(t, err)
			require.Equal(t, "installed sample@1.0: sample\n", output)
			root := filepath.Join(home, ".local/opt/java/tools")
			info, err := os.Stat(filepath.Join(root, "envs/sample"))
			require.NoError(t, err)
			require.Equal(t, os.FileMode(0755), info.Mode().Perm())
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

func TestJarLaunchers(t *testing.T) {
	for _, inherit := range []bool{false, true} {
		t.Run(fmt.Sprint(inherit), func(t *testing.T) {
			home := setupJava(t)
			source := filepath.Join(t.TempDir(), "language server.jar")
			require.NoError(t, os.WriteFile(source, []byte("jar payload"), 0600))
			args := []string{"install", "server@1", source, "--jar", "server=language server.jar"}
			if inherit {
				args = append(args, "--inherit-java")
			}
			_, err := invoke(t, home, args...)
			require.NoError(t, err)
			root := filepath.Join(home, ".local/opt/java/tools")
			jar := filepath.Join(root, "envs/server/payload/language server.jar")
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
			require.Equal(t, "java-home:"+java+"\nargs:-jar "+jar+" --stdio\n", string(result))
		})
	}
}

func TestExecutableDirectoryAndInheritance(t *testing.T) {
	home := setupJava(t)
	archive := makeArchive(t, "zip", []string{"sample/support/analyze", "sample/support/inspect"})
	output, err := invoke(t, home, "install", "sample@1", archive, "--extract", "--inherit-java", "--executable-dir", "sample-=support")
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
	_, err := invoke(t, home, "install", "sample@1", archive, "--extract", "--executable", "sample=bin/sample", "--java", alias)
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
			_, err := invoke(t, home, "install", "sample@1", archive, "--extract", "--executable", "sample=bin/sample")
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
			_, err = invoke(t, home, "install", "sample@1", source, "--extract", "--executable", "sample=link")
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
			args := []string{"install", "sample@1", archive, "--extract", "--executable", "sample=bin/sample"}
			switch failure {
			case "package":
				require.NoError(t, os.MkdirAll(filepath.Join(root, "envs/sample"), 0755))
			case "launcher":
				executable(t, filepath.Join(root, "bin/sample"), "original")
			case "duplicate":
				args = append(args, "--jar", "sample=bin/sample")
			case "path":
				args = append(args, "--jar", "other=../outside")
			case "nonexistent":
				args = append(args, "--jar", "other=missing.jar")
			case "runtime":
				args = append(args, "--java", "/missing", "--inherit-java")
			}
			_, err := invoke(t, home, args...)
			require.Error(t, err)
			require.NoFileExists(t, filepath.Join(root, "envs/sample/payload/bin/sample"))
		})
	}
}
