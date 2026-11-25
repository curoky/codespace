package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"os/exec"
	"strings"
)

func fetchArtifacts(ctx context.Context, requested, source string, options installOptions) ([]string, error) {
	cs, err := exec.LookPath("cs")
	if err != nil {
		return nil, fmt.Errorf("coursier: %w", err)
	}
	if strings.Contains(source, "://") {
		name, version, _ := strings.Cut(requested, "@")
		source = "codespace.distributions:" + name + ":" + version + ",url=" + url.QueryEscape(source)
	}
	args := []string{"fetch", "--no-default", "--classpath-order"}
	for _, repository := range options.repositories {
		args = append(args, "--repository", repository)
	}
	args = append(args, "--repository", "https://repo.maven.apache.org/maven2")
	if options.artifactType != "" {
		source += ",type=" + options.artifactType
		args = append(args, "--artifact-type", options.artifactType)
	}
	if options.classifier != "" {
		source += ",classifier=" + options.classifier
	}
	if options.extract {
		args = append(args, "--intransitive", source)
	} else {
		args = append(args, "--", source)
	}
	cmd := exec.CommandContext(ctx, cs, args...)
	cmd.Stdin, cmd.Stderr = os.Stdin, os.Stderr
	output, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("coursier fetch: %w", err)
	}
	listing := strings.TrimSpace(string(output))
	if listing == "" {
		return nil, fmt.Errorf("coursier returned no artifacts")
	}
	files := strings.Split(listing, "\n")
	for _, file := range files {
		info, err := os.Stat(file)
		if err != nil || !info.Mode().IsRegular() {
			return nil, fmt.Errorf("coursier returned an invalid artifact: %s", file)
		}
	}
	if options.checksum != "" {
		if len(files) != 1 {
			return nil, fmt.Errorf("checksum requires exactly one artifact")
		}
		if err := verifyChecksum(files[0], options.checksum); err != nil {
			return nil, err
		}
	}
	return files, nil
}

func verifyChecksum(path, expected string) (err error) {
	input, err := os.Open(path)
	if err != nil {
		return err
	}
	defer func() { err = errors.Join(err, input.Close()) }()
	hash := sha256.New()
	if _, err := io.Copy(hash, input); err != nil {
		return err
	}
	if "sha256:"+hex.EncodeToString(hash.Sum(nil)) != expected {
		return fmt.Errorf("artifact checksum mismatch: %s", path)
	}
	return nil
}
