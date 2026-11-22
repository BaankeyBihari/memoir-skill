package store

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func mustWriteFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatalf("mkdir %s: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
}

func TestScanFullStoreHierarchy(t *testing.T) {
	root := t.TempDir()

	// Repo with meta.json, wiki (top pages + categories + .ingest-state.json), clones, and worktrees.
	repoBase := filepath.Join(root, "repos", "github.com__acme__app")
	mustWriteFile(t, filepath.Join(repoBase, "meta.json"), `{"remote":"https://github.com/acme/app","sync_to_repo":true}`)
	mustWriteFile(t, filepath.Join(repoBase, "wiki", ".ingest-state.json"), `{"version":1,"fragments":{}}`)
	mustWriteFile(t, filepath.Join(repoBase, "wiki", "conventions.md"), "# Conventions\n")
	mustWriteFile(t, filepath.Join(repoBase, "wiki", "log.md"), "# Wiki Log\n")
	mustWriteFile(t, filepath.Join(repoBase, "wiki", "index.md"), "# Wiki Index\n")
	mustWriteFile(t, filepath.Join(repoBase, "wiki", "decisions", "store-location.md"), "# Store Location\n")
	mustWriteFile(t, filepath.Join(repoBase, "wiki", "architecture", "overview.md"), "# Architecture Overview\n")

	cloneBase := filepath.Join(repoBase, "clones", "app--a1b2c3d4")
	mustWriteFile(t, filepath.Join(cloneBase, "clone.json"), `{"root":"/tmp/app","last_seen":"2026-11-21T00:00:00Z"}`)
	mustWriteFile(t, filepath.Join(cloneBase, "paths", "_main", "active", "state-current.md"), "# Session State\n")
	mustWriteFile(t, filepath.Join(cloneBase, "paths", "_main", "active", "decision-use-go.md"), "# Use Go\n")
	mustWriteFile(t, filepath.Join(cloneBase, "paths", "_main", "active", "log-build-ok.md"), "# Build OK\n")
	mustWriteFile(t, filepath.Join(cloneBase, "paths", "_main", "archive", "20261119-decision-old.md"), "# Old Decision\n")
	mustWriteFile(t, filepath.Join(cloneBase, "paths", "_main", "archive", "20261121-decision-mid.md"), "# Mid Decision\n")
	mustWriteFile(t, filepath.Join(cloneBase, "paths", "Worktrees__wt-ui", "active", "reference-spec.md"), "# Spec Ref\n")

	// Pinned workspace with wiki and subpath.
	pinBase := filepath.Join(root, "pinned", "research--4d5e6f7a")
	mustWriteFile(t, filepath.Join(pinBase, "workspace.json"), `{"root":"/tmp/research","last_seen":"2026-11-21T00:00:00Z"}`)
	mustWriteFile(t, filepath.Join(pinBase, "wiki", "index.md"), "# Research Index\n")
	mustWriteFile(t, filepath.Join(pinBase, "paths", "_root", "active", "feedback-concise.md"), "# Concise Output\n")
	mustWriteFile(t, filepath.Join(pinBase, "paths", "notes__sub", "active", "state-current.md"), "# Subpath State\n")

	// Standalone flat workspace.
	mustWriteFile(t, filepath.Join(root, "standalone", "scratch--8b9c0d1e", "active", "state-current.md"), "# Scratch State\n")
	mustWriteFile(t, filepath.Join(root, "standalone", "scratch--8b9c0d1e", "archive", "20261101-log-init.md"), "# Init Log\n")

	tree, err := Scan(root)
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}

	if len(tree.Repos) != 1 || len(tree.Pinned) != 1 || len(tree.Standalone) != 1 {
		t.Fatalf("unexpected top-level counts: repos=%d pinned=%d standalone=%d",
			len(tree.Repos), len(tree.Pinned), len(tree.Standalone))
	}

	repo := tree.Repos[0]
	if repo.Label != "github.com/acme/app" {
		t.Fatalf("repo label = %q", repo.Label)
	}
	if repo.Meta == nil || !repo.Meta.SyncToRepo {
		t.Fatalf("expected repo meta.sync_to_repo=true, got %+v", repo.Meta)
	}
	if repo.Wiki == nil || len(repo.Wiki.TopPages) != 3 {
		t.Fatalf("expected 3 wiki top pages (excluding .ingest-state.json), got %+v", repo.Wiki)
	}
	if repo.Wiki.TopPages[0].Name != "index.md" || repo.Wiki.TopPages[1].Name != "log.md" || repo.Wiki.TopPages[2].Name != "conventions.md" {
		t.Fatalf("unexpected wiki top page ordering: %+v", repo.Wiki.TopPages)
	}
	if len(repo.Wiki.Categories) != 2 || repo.Wiki.Categories[0].Name != "architecture" || repo.Wiki.Categories[1].Name != "decisions" {
		t.Fatalf("unexpected wiki category ordering: %+v", repo.Wiki.Categories)
	}

	clone := repo.Clones[0]
	if len(clone.Paths) != 2 {
		t.Fatalf("expected 2 clone paths, got %d", len(clone.Paths))
	}
	if clone.Paths[0].Key != "_main" || clone.Paths[0].Label != "main" {
		t.Fatalf("expected _main path first, got %+v", clone.Paths[0])
	}
	if clone.Paths[1].Label != "Worktrees/wt-ui" {
		t.Fatalf("expected Worktrees/wt-ui label, got %q", clone.Paths[1].Label)
	}
	mainPath := clone.Paths[0]
	if mainPath.State == nil || mainPath.State.Kind != "state" {
		t.Fatalf("expected state-current.md in State field")
	}
	if len(mainPath.Active) != 2 || mainPath.Active[0].Kind != "decision" || mainPath.Active[1].Kind != "log" {
		t.Fatalf("unexpected active fragments: %+v", mainPath.Active)
	}
	if len(mainPath.Archive) != 2 || mainPath.Archive[0].Name != "20261121-decision-mid.md" || !mainPath.Archive[0].Archived {
		t.Fatalf("expected newest archived item first, got %+v", mainPath.Archive)
	}

	pin := tree.Pinned[0]
	if pin.Wiki == nil || len(pin.Paths) != 2 || pin.Paths[0].Key != "_root" || pin.Paths[0].Label != "root" {
		t.Fatalf("unexpected pinned workspace structure: %+v", pin)
	}
	if pin.Paths[0].Active[0].Kind != "feedback" {
		t.Fatalf("expected feedback kind, got %q", pin.Paths[0].Active[0].Kind)
	}

	st := tree.Standalone[0]
	if st.State == nil || len(st.Archive) != 1 || st.Archive[0].Kind != "log" {
		t.Fatalf("unexpected standalone workspace structure: %+v", st)
	}
}

func TestScanMissingStoreReturnsEmptyTree(t *testing.T) {
	tree, err := Scan(filepath.Join(t.TempDir(), "missing"))
	if err != nil {
		t.Fatalf("Scan missing store failed: %v", err)
	}
	if tree.Repos == nil || tree.Pinned == nil || tree.Standalone == nil {
		t.Fatalf("expected non-nil empty slices in Tree")
	}
}

func TestResolveSafeFileSecurityAndErrors(t *testing.T) {
	root := t.TempDir()
	outside := filepath.Join(t.TempDir(), "secret.md")
	mustWriteFile(t, outside, "# Secret\n")

	target := filepath.Join(root, "repos", "r1", "wiki", "index.md")
	mustWriteFile(t, target, "# Index\n")
	mustWriteFile(t, filepath.Join(root, "repos", "r1", "wiki", ".ingest-state.json"), "{}")

	symlinkPath := filepath.Join(root, "repos", "r1", "wiki", "escape.md")
	if err := os.Symlink(outside, symlinkPath); err != nil {
		t.Fatalf("create symlink: %v", err)
	}

	got, err := ResolveSafeFile(root, "repos/r1/wiki/index.md")
	if err != nil {
		t.Fatalf("valid file failed: %v", err)
	}
	if filepath.Base(got) != "index.md" {
		t.Fatalf("unexpected resolved path: %q", got)
	}

	invalidPaths := []string{
		"",
		"/etc/passwd",
		"../secret.md",
		"repos/r1/wiki/../../secret.md",
		"repos/r1/wiki/.ingest-state.json",
		"repos/r1/wiki/escape.md",
		"repos/r1/wiki",
		"repos/r1/meta.json",
		"repos\\r1\\wiki\\index.md",
	}
	for _, p := range invalidPaths {
		if _, err := ResolveSafeFile(root, p); !errors.Is(err, ErrInvalidPath) {
			t.Fatalf("ResolveSafeFile(%q) err = %v, want ErrInvalidPath", p, err)
		}
	}

	if _, err := ResolveSafeFile(root, "repos/r1/wiki/missing.md"); !errors.Is(err, ErrNotFound) {
		t.Fatalf("missing file err = %v, want ErrNotFound", err)
	}
}

func TestScanGroupsStandaloneMembersUnderLongestPin(t *testing.T) {
	root := t.TempDir()
	mustWriteFile(t, filepath.Join(root, "pinned.json"), `["/w","/w/inner"]`)
	mustWriteFile(t, filepath.Join(root, "pinned", "w--11111111", "workspace.json"), `{"root":"/w"}`)
	mustWriteFile(t, filepath.Join(root, "pinned", "w--11111111", "paths", "_root", "active", "log-legacy.md"), "# Legacy\n")
	mustWriteFile(t, filepath.Join(root, "pinned", "inner--22222222", "workspace.json"), `{"root":"/w/inner"}`)
	// Unpinned group: its workspace.json survives but pinned.json no longer lists it.
	mustWriteFile(t, filepath.Join(root, "pinned", "old--33333333", "workspace.json"), `{"root":"/old"}`)

	member := func(id, dir string) {
		mustWriteFile(t, filepath.Join(root, "standalone", id, "scope.json"), `{"root":"`+dir+`"}`)
		mustWriteFile(t, filepath.Join(root, "standalone", id, "active", "decision-x.md"), "# X\n")
	}
	member("w--aaaaaaaa", "/w")
	member("b--bbbbbbbb", "/w/a/b")
	member("deep--cccccccc", "/w/inner/deep")
	member("wx--dddddddd", "/wx")     // sibling prefix, not inside /w
	member("old--eeeeeeee", "/old/x") // under an unpinned group

	tree, err := Scan(root)
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}

	paths := map[string][]PathScope{}
	for _, pin := range tree.Pinned {
		paths[pin.ID] = pin.Paths
	}
	w := paths["w--11111111"]
	if len(w) != 3 || w[0].Key != "_root" || w[1].Key != "w--aaaaaaaa" || w[1].Label != "root" ||
		w[2].Key != "b--bbbbbbbb" || w[2].Label != "a/b" || len(w[2].Active) != 1 {
		t.Fatalf("unexpected /w group paths: %+v", w)
	}
	if inner := paths["inner--22222222"]; len(inner) != 1 || inner[0].Key != "deep--cccccccc" || inner[0].Label != "deep" {
		t.Fatalf("unexpected /w/inner group paths: %+v", inner)
	}
	if old := paths["old--33333333"]; len(old) != 0 {
		t.Fatalf("unpinned group must have no members: %+v", old)
	}

	var ids []string
	for _, st := range tree.Standalone {
		ids = append(ids, st.ID)
	}
	if len(ids) != 2 || ids[0] != "old--eeeeeeee" || ids[1] != "wx--dddddddd" {
		t.Fatalf("Standalone must list only ungrouped scopes, got %v", ids)
	}
}
