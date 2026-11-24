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
		Use: "node-tool", Short: "Install isolated npm CLI packages",
		SilenceErrors: true, SilenceUsage: true,
		CompletionOptions: cobra.CompletionOptions{DisableDefaultCmd: true},
	}
	install := &cobra.Command{
		Use: "install PACKAGE", Short: "Install one npm CLI package",
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			tool, err := installTool(cmd.Context(), args[0], options)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintf(cmd.OutOrStdout(), "installed %s@%s: %s\n", tool.name, tool.version, strings.Join(tool.bins, ", "))
			return err
		},
	}
	install.Flags().StringVar(&options.node, "node", filepath.Join(home, ".local/opt/node/nodejs26"), "Node.js installation root")
	install.Flags().StringVar(&options.root, "root", filepath.Join(home, ".local/opt/node/tools"), "Isolated environments and launchers root")
	install.Flags().StringVar(&options.registry, "registry", "", "Registry URL passed to pnpm")
	install.Flags().StringArrayVar(&options.allowBuild, "allow-build", nil, "Package allowed to run lifecycle scripts (repeatable)")
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
