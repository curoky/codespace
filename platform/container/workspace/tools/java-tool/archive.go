package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"github.com/mholt/archives"
)

func validateRelativePath(value string) error {
	if !filepath.IsLocal(value) || filepath.Clean(value) == "." || slices.Contains(strings.Split(value, "/"), "..") {
		return fmt.Errorf("path must stay inside the distribution: %q", value)
	}
	return nil
}

func extractArchive(ctx context.Context, source, payload string) (err error) {
	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, input.Close()) }()
	format, stream, err := archives.Identify(ctx, "", input)
	if err != nil {
		return fmt.Errorf("identify archive: %w", err)
	}
	// The installer accepts ZIP and TAR, not every format supported by the library.
	switch value := format.(type) {
	case archives.Zip, archives.Tar:
	case archives.CompressedArchive:
		if _, ok := value.Extraction.(archives.Tar); !ok {
			return fmt.Errorf("source is not a ZIP or TAR archive")
		}
	default:
		return fmt.Errorf("source is not a ZIP or TAR archive")
	}
	unpacked := filepath.Dir(payload)
	root, err := os.OpenRoot(unpacked)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, root.Close()) }()
	extractor := format.(archives.Extractor)
	err = extractor.Extract(ctx, stream, func(_ context.Context, entry archives.FileInfo) error {
		return extractEntry(root, entry)
	})
	if err != nil {
		return fmt.Errorf("extract archive: %w", err)
	}
	entries, err := os.ReadDir(unpacked)
	if err != nil {
		return err
	}
	if len(entries) != 1 || !entries[0].IsDir() {
		return fmt.Errorf("archive must contain one top-level directory")
	}
	if entries[0].Name() == filepath.Base(payload) {
		return nil
	}
	return os.Rename(filepath.Join(unpacked, entries[0].Name()), payload)
}

func extractEntry(root *os.Root, entry archives.FileInfo) (err error) {
	if err := validateRelativePath(entry.NameInArchive); err != nil {
		return err
	}
	if entry.LinkTarget != "" || (!entry.IsDir() && !entry.Mode().IsRegular()) {
		return fmt.Errorf("archive contains an unsupported entry: %q", entry.NameInArchive)
	}
	if entry.IsDir() {
		return root.MkdirAll(entry.NameInArchive, 0755)
	}
	if err := root.MkdirAll(filepath.Dir(entry.NameInArchive), 0755); err != nil {
		return err
	}
	input, err := entry.Open()
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, input.Close()) }()
	mode := entry.Mode().Perm()
	if mode == 0 {
		mode = 0644
	}
	output, err := root.OpenFile(entry.NameInArchive, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	_, copyErr := io.Copy(output, input)
	return errors.Join(copyErr, output.Close())
}
