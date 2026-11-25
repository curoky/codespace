package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"
)

func command(home string) *cobra.Command {
	options := installOptions{}
	app := &cobra.Command{
		Use: "java-tool", Short: "Install Java CLI distributions",
		SilenceErrors: true, SilenceUsage: true,
		CompletionOptions: cobra.CompletionOptions{DisableDefaultCmd: true},
	}
	install := &cobra.Command{
		Use: "install NAME@VERSION SOURCE", Short: "Install a Maven dependency or a distribution URL",
		Args: cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			if options.inheritJava {
				options.java = ""
			}
			bins, err := installTool(cmd.Context(), args[0], args[1], options)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintf(cmd.OutOrStdout(), "installed %s: %s\n", args[0], strings.Join(bins, ", "))
			return err
		},
	}
	install.Flags().StringVar(&options.java, "java", filepath.Join(home, ".local/opt/java/openjdk27"), "JDK installation root")
	install.Flags().BoolVar(&options.inheritJava, "inherit-java", false, "Use the caller's Java environment")
	install.MarkFlagsMutuallyExclusive("java", "inherit-java")
	install.Flags().StringVar(&options.root, "root", filepath.Join(home, ".local/opt/java/tools"), "Distributions and launchers root")
	install.Flags().BoolVar(&options.extract, "extract", false, "Extract a ZIP or TAR archive")
	install.Flags().StringArrayVar(&options.repositories, "repository", nil, "Additional Maven repository (repeatable)")
	install.Flags().StringVar(&options.artifactType, "type", "", "Artifact type to fetch")
	install.Flags().StringVar(&options.classifier, "classifier", "", "Artifact classifier to fetch")
	install.Flags().StringVar(&options.checksum, "checksum", "", "Expected sha256:HASH for a single artifact (required for URLs)")
	install.Flags().StringArrayVar(&options.executables, "executable", nil, "COMMAND=RELATIVE_PATH (repeatable)")
	install.Flags().StringArrayVar(&options.mainClasses, "main", nil, "COMMAND=MAIN_CLASS (repeatable)")
	install.Flags().StringArrayVar(&options.executableDirs, "executable-dir", nil, "PREFIX=RELATIVE_DIRECTORY (repeatable)")
	app.AddCommand(install)
	return app
}

func main() {
	home, err := os.UserHomeDir()
	if err == nil {
		err = command(home).Execute()
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
