package main

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"github.com/spf13/cobra"
)

func run(ctx context.Context, args []string, stdout, stderr io.Writer) error {
	var outputJSON bool
	app := &cobra.Command{
		Use: "codex-llmbox-provider", Short: "Connect native Codex to an OAuth Responses provider",
		SilenceErrors: true, SilenceUsage: true,
		CompletionOptions: cobra.CompletionOptions{DisableDefaultCmd: true},
	}
	app.SetArgs(args)
	app.SetOut(stdout)
	app.SetErr(stderr)
	execute := func(cmd *cobra.Command, _ []string) error {
		home, err := os.UserHomeDir()
		if err != nil {
			return err
		}
		codexDir := filepath.Join(home, ".codex")
		if cmd.Name() == "token" {
			token, err := readToken(codexDir)
			if err != nil {
				return err
			}
			_, err = fmt.Fprintln(cmd.OutOrStdout(), token)
			return err
		}
		config, err := loadConnection(codexDir)
		if err != nil {
			return err
		}
		if cmd.Name() == "login" {
			return login(cmd.Context(), config, codexDir, cmd.ErrOrStderr())
		}
		token, err := readToken(codexDir)
		if err != nil {
			return err
		}
		items, err := fetchModels(cmd.Context(), config, token)
		if err != nil {
			return err
		}
		return writeModels(cmd.OutOrStdout(), items, outputJSON)
	}
	for _, name := range []string{"login", "token", "models"} {
		child := &cobra.Command{Use: name, Args: cobra.NoArgs, RunE: execute}
		if name == "models" {
			child.Flags().BoolVar(&outputJSON, "json", false, "Output JSON")
		}
		app.AddCommand(child)
	}
	return app.ExecuteContext(ctx)
}

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, os.Args[1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
