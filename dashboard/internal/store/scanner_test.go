package store

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

const (
	testIndexMD = "index.md"
	testPinID   = "w--11111111"
)

func mustWriteFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		t.Fatalf("mkdir %s: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
}

func seedFullHierarchyFixture(t *testing.T, root string) {
	t.Helper()
	workspaces := t.TempDir()

	// Repo with meta.json, wiki, clones, and worktrees.
	repoBase := filepath.Join(root, dirRepos, testRepoID)
	mustWriteFile(t, filepath.Join(repoBase, fileMetaJSON), `{"remote":"https://github.com/acme/app","sync_to_repo":true}`)
	mustWriteFile(t, filepath.Join(repoBase, dirWiki, ".ingest-state.json"), `{"version":1,"fragments":{}}`)
	mustWriteFile(t, filepath.Join(repoBase, dirWiki, "conventions.md"), "# Conventions\n")
	mustWriteFile(t, filepath.Join(repoBase, dirWiki, "log.md"), "# Wiki Log\n")
	mustWriteFile(t, filepath.Join(repoBase, dirWiki, testIndexMD), "# Wiki Index\n")
	mustWriteFile(t, filepath.Join(repoBase, dirWiki, "decisions", "store-location.md"), "# Store Location\n")
	mustWriteFile(t, filepath.Join(repoBase, dirWiki, "architecture", "overview.md"), "# Architecture Overview\n")

	cloneBase := filepath.Join(repoBase, dirClones, "app--a1b2c3d4")
	mustWriteFile(t, filepath.Join(cloneBase, fileCloneJSON), rootRecordJSON(filepath.Join(workspaces, "app"), "2026-11-21T00:00:00Z"))
	mustWriteFile(t, filepath.Join(cloneBase, dirPaths, keyMain, dirActive, fileStateCurrent), "# Session State\n")
	mustWriteFile(t, filepath.Join(cloneBase, dirPaths, keyMain, dirActive, "decision-use-go.md"), "# Use Go\n")
	mustWriteFile(t, filepath.Join(cloneBase, dirPaths, keyMain, dirActive, "log-build-ok.md"), "# Build OK\n")
	mustWriteFile(t, filepath.Join(cloneBase, dirPaths, keyMain, dirArchive, "20261119-decision-old.md"), "# Old Decision\n")
	mustWriteFile(t, filepath.Join(cloneBase, dirPaths, keyMain, dirArchive, "20261121-decision-mid.md"), "# Mid Decision\n")
	mustWriteFile(t, filepath.Join(cloneBase, dirPaths, "Worktrees__wt-ui", dirActive, "reference-spec.md"), "# Spec Ref\n")

	// Pinned workspace with wiki and subpath.
	pinBase := filepath.Join(root, dirPinned, "research--4d5e6f7a")
	mustWriteFile(t, filepath.Join(pinBase, fileWorkspaceJSON), rootRecordJSON(filepath.Join(workspaces, "research"), "2026-11-21T00:00:00Z"))
	mustWriteFile(t, filepath.Join(pinBase, dirWiki, testIndexMD), "# Research Index\n")
	mustWriteFile(t, filepath.Join(pinBase, dirPaths, keyRoot, dirActive, "feedback-concise.md"), "# Concise Output\n")
	mustWriteFile(t, filepath.Join(pinBase, dirPaths, "notes__sub", dirActive, fileStateCurrent), "# Subpath State\n")

	// Standalone flat workspace.
	mustWriteFile(t, filepath.Join(root, dirStandalone, "scratch--8b9c0d1e", dirActive, fileStateCurrent), "# Scratch State\n")
	mustWriteFile(t, filepath.Join(root, dirStandalone, "scratch--8b9c0d1e", dirArchive, "20261101-log-init.md"), "# Init Log\n")
}

func assertScannedRepo(t *testing.T, repo RepoScope) {
	t.Helper()
	if repo.Label != "github.com/acme/app" || repo.Meta == nil || !repo.Meta.SyncToRepo {
		t.Fatalf("unexpected repo metadata: label=%q meta=%+v", repo.Label, repo.Meta)
	}
	if repo.Wiki == nil || len(repo.Wiki.TopPages) != 3 {
		t.Fatalf("expected 3 wiki top pages (excluding .ingest-state.json), got %+v", repo.Wiki)
	}
	if repo.Wiki.TopPages[0].Name != testIndexMD || repo.Wiki.TopPages[1].Name != "log.md" || repo.Wiki.TopPages[2].Name != "conventions.md" {
		t.Fatalf("unexpected wiki top page ordering: %+v", repo.Wiki.TopPages)
	}
	if len(repo.Wiki.Categories) != 2 || repo.Wiki.Categories[0].Name != "architecture" || repo.Wiki.Categories[1].Name != "decisions" {
		t.Fatalf("unexpected wiki category ordering: %+v", repo.Wiki.Categories)
	}
}

func assertScannedClone(t *testing.T, clone CloneScope) {
	t.Helper()
	if len(clone.Paths) != 2 || clone.Paths[0].Key != keyMain || clone.Paths[0].Label != "main" {
		t.Fatalf("unexpected clone paths: %+v", clone.Paths)
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
}

func TestScanFullStoreHierarchy(t *testing.T) {
	root := t.TempDir()
	seedFullHierarchyFixture(t, root)

	tree, err := Scan(root)
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}
	if len(tree.Repos) != 1 || len(tree.Pinned) != 1 || len(tree.Standalone) != 1 {
		t.Fatalf("unexpected top-level counts: repos=%d pinned=%d standalone=%d",
			len(tree.Repos), len(tree.Pinned), len(tree.Standalone))
	}

	assertScannedRepo(t, tree.Repos[0])
	assertScannedClone(t, tree.Repos[0].Clones[0])

	pin := tree.Pinned[0]
	if pin.Wiki == nil || len(pin.Paths) != 2 || pin.Paths[0].Key != keyRoot || pin.Paths[0].Label != labelRoot {
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

	target := filepath.Join(root, dirRepos, "r1", dirWiki, testIndexMD)
	mustWriteFile(t, target, "# Index\n")
	mustWriteFile(t, filepath.Join(root, dirRepos, "r1", dirWiki, ".ingest-state.json"), "{}")

	symlinkPath := filepath.Join(root, dirRepos, "r1", dirWiki, "escape.md")
	if err := os.Symlink(outside, symlinkPath); err != nil {
		t.Fatalf("create symlink: %v", err)
	}

	got, err := ResolveSafeFile(root, "repos/r1/wiki/index.md")
	if err != nil {
		t.Fatalf("valid file failed: %v", err)
	}
	if filepath.Base(got) != testIndexMD {
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
	mustWriteFile(t, filepath.Join(root, filePinnedJSON), `["/w","/w/inner"]`)
	mustWriteFile(t, filepath.Join(root, dirPinned, testPinID, fileWorkspaceJSON), `{"root":"/w"}`)
	mustWriteFile(t, filepath.Join(root, dirPinned, testPinID, dirPaths, keyRoot, dirActive, "log-legacy.md"), "# Legacy\n")
	mustWriteFile(t, filepath.Join(root, dirPinned, "inner--22222222", fileWorkspaceJSON), `{"root":"/w/inner"}`)
	// Unpinned group: its workspace.json survives but pinned.json no longer lists it.
	mustWriteFile(t, filepath.Join(root, dirPinned, "old--33333333", fileWorkspaceJSON), `{"root":"/old"}`)

	member := func(id, dir string) {
		mustWriteFile(t, filepath.Join(root, dirStandalone, id, fileScopeJSON), rootRecordJSON(dir, ""))
		mustWriteFile(t, filepath.Join(root, dirStandalone, id, dirActive, "decision-x.md"), "# X\n")
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
	w := paths[testPinID]
	if len(w) != 3 || w[0].Key != keyRoot || w[1].Key != "w--aaaaaaaa" || w[1].Label != labelRoot ||
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
