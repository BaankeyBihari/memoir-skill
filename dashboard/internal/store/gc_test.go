package store

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

const testRepoID = "github.com__acme__app"

func rootRecordJSON(root, lastSeen string) string {
	if lastSeen == "" {
		return fmt.Sprintf(`{"root":%q}`, root)
	}
	return fmt.Sprintf(`{"root":%q,"last_seen":%q}`, root, lastSeen)
}

func seedGCStoreFixture(t *testing.T, storeRoot, healthyDir, missingCloneDir, missingPinDir string) (wikiIndex, healthyClone, orphanClone string) {
	t.Helper()
	repoBase := filepath.Join(storeRoot, dirRepos, testRepoID)
	wikiIndex = filepath.Join(repoBase, dirWiki, "index.md")
	mustWriteFile(t, wikiIndex, "# Shared Wiki\n")

	healthyClone = filepath.Join(repoBase, dirClones, "app--11111111")
	mustWriteFile(t, filepath.Join(healthyClone, fileCloneJSON), rootRecordJSON(healthyDir, "2026-11-21T00:00:00Z"))
	mustWriteFile(t, filepath.Join(healthyClone, dirPaths, keyMain, dirActive, fileStateCurrent), "# State\n")

	orphanClone = filepath.Join(repoBase, dirClones, "app-old--22222222")
	mustWriteFile(t, filepath.Join(orphanClone, fileCloneJSON), rootRecordJSON(missingCloneDir, "2026-11-20T00:00:00Z"))
	mustWriteFile(t, filepath.Join(orphanClone, dirPaths, keyMain, dirActive, "decision-old.md"), "# Old\n")

	orphanPin := filepath.Join(storeRoot, dirPinned, "notes--33333333")
	mustWriteFile(t, filepath.Join(orphanPin, fileWorkspaceJSON), rootRecordJSON(missingPinDir, "2026-11-19T00:00:00Z"))
	mustWriteFile(t, filepath.Join(orphanPin, dirPaths, keyRoot, dirActive, fileStateCurrent), "# Pin State\n")
	return wikiIndex, healthyClone, orphanClone
}

func assertRejectsInvalidPruneTargets(t *testing.T, storeRoot, missingCloneDir string) {
	t.Helper()
	if err := PruneOrphan(storeRoot, "repos/github.com__acme__app/clones/app--11111111"); !errors.Is(err, ErrNotOrphaned) {
		t.Fatalf("expected ErrNotOrphaned for healthy clone, got %v", err)
	}
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

	outside := t.TempDir()
	mustWriteFile(t, filepath.Join(outside, fileCloneJSON), rootRecordJSON(missingCloneDir, ""))
	symlinkClone := filepath.Join(storeRoot, dirRepos, testRepoID, dirClones, "linked--99999999")
	if err := os.Symlink(outside, symlinkClone); err != nil {
		t.Fatalf("symlink: %v", err)
	}
	if err := PruneOrphan(storeRoot, "repos/github.com__acme__app/clones/linked--99999999"); !errors.Is(err, ErrInvalidPath) {
		t.Fatalf("expected ErrInvalidPath for symlinked clone, got %v", err)
	}
	if _, err := os.Stat(filepath.Join(outside, fileCloneJSON)); err != nil {
		t.Fatalf("outside target should never be touched: %v", err)
	}
}

func TestGCListAndPruneOrphansSafely(t *testing.T) {
	storeRoot := t.TempDir()
	healthyDir := t.TempDir()
	missingCloneDir := filepath.Join(t.TempDir(), "deleted-clone")
	missingPinDir := filepath.Join(t.TempDir(), "deleted-pin")
	wikiIndex, healthyClone, orphanClone := seedGCStoreFixture(t, storeRoot, healthyDir, missingCloneDir, missingPinDir)

	tree, err := Scan(storeRoot)
	if err != nil {
		t.Fatalf("Scan failed: %v", err)
	}
	if tree.Repos[0].Clones[0].Orphaned || !tree.Repos[0].Clones[1].Orphaned || !tree.Pinned[0].Orphaned {
		t.Fatalf("unexpected orphan flags: clones=%+v pinned=%+v", tree.Repos[0].Clones, tree.Pinned[0])
	}
	orphans, err := ListOrphans(storeRoot)
	if err != nil || len(orphans) != 2 {
		t.Fatalf("ListOrphans got (%+v, %v), want 2", orphans, err)
	}

	assertRejectsInvalidPruneTargets(t, storeRoot, missingCloneDir)

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
	orphan := filepath.Join(storeRoot, dirStandalone, "gone--44444444")
	healthy := filepath.Join(storeRoot, dirStandalone, "here--55555555")
	mustWriteFile(t, filepath.Join(orphan, fileScopeJSON), rootRecordJSON(missing, ""))
	mustWriteFile(t, filepath.Join(orphan, dirActive, "decision-x.md"), "# X\n")
	mustWriteFile(t, filepath.Join(healthy, fileScopeJSON), rootRecordJSON(t.TempDir(), ""))

	orphans, err := ListOrphans(storeRoot)
	if err != nil {
		t.Fatalf("ListOrphans failed: %v", err)
	}
	if len(orphans) != 1 || orphans[0].Scope != dirStandalone || orphans[0].RelPath != "standalone/gone--44444444" {
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
