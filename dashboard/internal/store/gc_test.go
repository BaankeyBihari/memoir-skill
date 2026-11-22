package store

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestGCListAndPruneOrphansSafely(t *testing.T) {
	storeRoot := t.TempDir()
	healthyDir := t.TempDir()
	missingCloneDir := filepath.Join(t.TempDir(), "deleted-clone")
	missingPinDir := filepath.Join(t.TempDir(), "deleted-pin")

	repoBase := filepath.Join(storeRoot, "repos", "github.com__acme__app")
	wikiIndex := filepath.Join(repoBase, "wiki", "index.md")
	mustWriteFile(t, wikiIndex, "# Shared Wiki\n")

	// Healthy clone.
	healthyClone := filepath.Join(repoBase, "clones", "app--11111111")
	mustWriteFile(t, filepath.Join(healthyClone, "clone.json"), `{"root":"`+healthyDir+`","last_seen":"2026-11-21T00:00:00Z"}`)
	mustWriteFile(t, filepath.Join(healthyClone, "paths", "_main", "active", "state-current.md"), "# State\n")

	// Orphaned clone.
	orphanClone := filepath.Join(repoBase, "clones", "app-old--22222222")
	mustWriteFile(t, filepath.Join(orphanClone, "clone.json"), `{"root":"`+missingCloneDir+`","last_seen":"2026-11-20T00:00:00Z"}`)
	mustWriteFile(t, filepath.Join(orphanClone, "paths", "_main", "active", "decision-old.md"), "# Old\n")

	// Orphaned pinned workspace.
	orphanPin := filepath.Join(storeRoot, "pinned", "notes--33333333")
	mustWriteFile(t, filepath.Join(orphanPin, "workspace.json"), `{"root":"`+missingPinDir+`","last_seen":"2026-11-19T00:00:00Z"}`)
	mustWriteFile(t, filepath.Join(orphanPin, "paths", "_root", "active", "state-current.md"), "# Pin State\n")

	// Scan should reflect Orphaned flag on clones and pinned workspaces.
	tree, err := Scan(storeRoot)
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}
	if tree.Repos[0].Clones[0].Orphaned || !tree.Repos[0].Clones[1].Orphaned {
		t.Fatalf("unexpected clone orphan flags: %+v", tree.Repos[0].Clones)
	}
	if !tree.Pinned[0].Orphaned {
		t.Fatalf("expected pinned workspace to be marked orphaned")
	}

	orphans, err := ListOrphans(storeRoot)
	if err != nil {
		t.Fatalf("ListOrphans failed: %v", err)
	}
	if len(orphans) != 2 {
		t.Fatalf("expected 2 orphans, got %d: %+v", len(orphans), orphans)
	}

	// Refuse pruning healthy clone.
	if err := PruneOrphan(storeRoot, "repos/github.com__acme__app/clones/app--11111111"); !errors.Is(err, ErrNotOrphaned) {
		t.Fatalf("expected ErrNotOrphaned for healthy clone, got %v", err)
	}

	// Refuse invalid paths (repo root, wiki, nested standalone, traversal).
	for _, bad := range []string{
		"../outside",
		"repos/github.com__acme__app",
		"repos/github.com__acme__app/wiki",
		"standalone/scratch--44444444/active",
		"repos/github.com__acme__app/clones/app--11111111/paths/_main",
	} {
		if err := PruneOrphan(storeRoot, bad); !errors.Is(err, ErrInvalidPath) {
			t.Fatalf("PruneOrphan(%q) = %v, want ErrInvalidPath", bad, err)
		}
	}

	// Refuse symlinked clone directory pointing outside store.
	outside := t.TempDir()
	mustWriteFile(t, filepath.Join(outside, "clone.json"), `{"root":"`+missingCloneDir+`"}`)
	symlinkClone := filepath.Join(repoBase, "clones", "linked--99999999")
	if err := os.Symlink(outside, symlinkClone); err != nil {
		t.Fatalf("symlink: %v", err)
	}
	if err := PruneOrphan(storeRoot, "repos/github.com__acme__app/clones/linked--99999999"); !errors.Is(err, ErrInvalidPath) {
		t.Fatalf("expected ErrInvalidPath for symlinked clone, got %v", err)
	}
	if _, err := os.Stat(filepath.Join(outside, "clone.json")); err != nil {
		t.Fatalf("outside target should never be touched: %v", err)
	}

	// Prune valid orphaned clone and verify shared wiki & healthy clone remain intact.
	if err := PruneOrphan(storeRoot, "repos/github.com__acme__app/clones/app-old--22222222"); err != nil {
		t.Fatalf("PruneOrphan valid clone failed: %v", err)
	}
	if _, err := os.Stat(orphanClone); !os.IsNotExist(err) {
		t.Fatalf("expected orphan clone dir removed")
	}
	if _, err := os.Stat(wikiIndex); err != nil {
		t.Fatalf("shared wiki must remain intact: %v", err)
	}
	if _, err := os.Stat(healthyClone); err != nil {
		t.Fatalf("healthy clone must remain intact: %v", err)
	}
}

func TestGCListAndPruneOrphanedStandalone(t *testing.T) {
	storeRoot := t.TempDir()
	missing := filepath.Join(t.TempDir(), "gone")
	orphan := filepath.Join(storeRoot, "standalone", "gone--44444444")
	healthy := filepath.Join(storeRoot, "standalone", "here--55555555")
	mustWriteFile(t, filepath.Join(orphan, "scope.json"), `{"root":"`+missing+`"}`)
	mustWriteFile(t, filepath.Join(orphan, "active", "decision-x.md"), "# X\n")
	mustWriteFile(t, filepath.Join(healthy, "scope.json"), `{"root":"`+t.TempDir()+`"}`)

	orphans, err := ListOrphans(storeRoot)
	if err != nil {
		t.Fatalf("ListOrphans failed: %v", err)
	}
	if len(orphans) != 1 || orphans[0].Scope != "standalone" || orphans[0].RelPath != "standalone/gone--44444444" {
		t.Fatalf("unexpected orphans: %+v", orphans)
	}
	if err := PruneOrphan(storeRoot, "standalone/here--55555555"); !errors.Is(err, ErrNotOrphaned) {
		t.Fatalf("expected ErrNotOrphaned for healthy standalone, got %v", err)
	}
	if err := PruneOrphan(storeRoot, "standalone/gone--44444444"); err != nil {
		t.Fatalf("PruneOrphan standalone failed: %v", err)
	}
	if _, err := os.Stat(orphan); !os.IsNotExist(err) {
		t.Fatalf("expected orphaned standalone dir removed")
	}
	if _, err := os.Stat(healthy); err != nil {
		t.Fatalf("healthy standalone must remain: %v", err)
	}
}
