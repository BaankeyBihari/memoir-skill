package main

import (
	"path/filepath"
	"testing"
)

func TestResolveStoreRoot(t *testing.T) {
	t.Setenv("MEMOIR_STORE", "/tmp/env-memoir-store")

	got, err := resolveStoreRoot("")
	if err != nil {
		t.Fatalf("resolveStoreRoot env: %v", err)
	}
	want, _ := filepath.Abs("/tmp/env-memoir-store")
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}

	gotExplicit, err := resolveStoreRoot("/tmp/explicit-store")
	if err != nil {
		t.Fatalf("resolveStoreRoot explicit: %v", err)
	}
	wantExplicit, _ := filepath.Abs("/tmp/explicit-store")
	if gotExplicit != wantExplicit {
		t.Fatalf("got %q, want %q", gotExplicit, wantExplicit)
	}
}

func TestDefaultVersion(t *testing.T) {
	if version == "" {
		t.Fatal("expected non-empty default version")
	}
	if version != "dev" {
		t.Fatalf("expected default version 'dev', got %q", version)
	}
}
