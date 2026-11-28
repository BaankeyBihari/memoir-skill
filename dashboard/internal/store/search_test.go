package store

import (
	"path/filepath"
	"sync"
	"testing"
)

func TestSearchIndexQueryFiltersAndConcurrency(t *testing.T) {
	root := t.TempDir()

	mustWriteFile(t, filepath.Join(root, dirRepos, testRepoID, dirWiki, "decisions", "use-go.md"),
		"# Use Go\nType: decision\nUpdated: 2026-11-21\n\nSingle binary HTTP server using goldmark.\n")
	mustWriteFile(t, filepath.Join(root, dirRepos, testRepoID, dirClones, "app--11111111", dirPaths, keyMain, dirActive, "decision-use-sse.md"),
		"# Use SSE\nDate: 2026-11-21\nDecision: Push live reload over Server-Sent Events.\n")
	mustWriteFile(t, filepath.Join(root, dirRepos, testRepoID, dirClones, "app--11111111", dirPaths, keyMain, dirArchive, "20261110-decision-old-polling.md"),
		"# Old Polling\nDate: 2026-11-10\nDecision: Replaced short polling with SSE live reload.\n")
	mustWriteFile(t, filepath.Join(root, dirPinned, "notes--22222222", dirPaths, keyRoot, dirActive, "feedback-style.md"),
		"# Concise Style\nDate: 2026-11-21\nFeedback: Keep SSE payloads minimal.\n")
	mustWriteFile(t, filepath.Join(root, dirStandalone, "scratch--33333333", dirActive, "log-sse-check.md"),
		"# SSE Check\nDate: 2026-11-21\nEvent: Verified SSE stream.\n")

	mustWriteFile(t, filepath.Join(root, dirStandalone, "scratch--33333333", dirArchive, "20261110-task-follow-up.md"), "# Follow up\nStatus: done\n")

	idx := NewSearchIndex(root)
	if err := idx.Rebuild(); err != nil {
		t.Fatalf("Rebuild failed: %v", err)
	}

	// Full-text multi-token AND search.
	res := idx.Query("live reload", "", "", 20)
	if len(res) != 2 || res[0].Archived || !res[1].Archived {
		t.Fatalf("expected active decision ranked ahead of archived: %+v", res)
	}

	// Scope filter.
	if pinnedRes := idx.Query("sse", dirPinned, "", 20); len(pinnedRes) != 1 || pinnedRes[0].Scope != dirPinned {
		t.Fatalf("expected 1 pinned result, got %+v", pinnedRes)
	}

	if tasks := idx.Query("follow", dirStandalone, "task", 20); len(tasks) != 1 || !tasks[0].Archived {
		t.Fatalf("expected archived task in task filter: %+v", tasks)
	}

	// Type filter.
	if wikiRes := idx.Query("goldmark", "", dirWiki, 20); len(wikiRes) != 1 || wikiRes[0].Type != dirWiki {
		t.Fatalf("expected 1 wiki result, got %+v", wikiRes)
	}

	// Filter-only (empty query).
	const wantLog = "log"
	if logRes := idx.Query("", dirStandalone, wantLog, 20); len(logRes) != 1 || logRes[0].Type != wantLog {
		t.Fatalf("expected 1 standalone log result, got %+v", logRes)
	}

	// Concurrent Rebuild + Query under -race.
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(2)
		go func() {
			defer wg.Done()
			_ = idx.Rebuild()
		}()
		go func() {
			defer wg.Done()
			_ = idx.Query("sse", "", "", 10)
		}()
	}
	wg.Wait()
}

func TestSearchIndexTagsGroupMembersAsPinned(t *testing.T) {
	root := t.TempDir()
	mustWriteFile(t, filepath.Join(root, filePinnedJSON), `["/w"]`)
	mustWriteFile(t, filepath.Join(root, dirPinned, testPinID, fileWorkspaceJSON), `{"root":"/w"}`)
	mustWriteFile(t, filepath.Join(root, dirStandalone, "a--22222222", fileScopeJSON), `{"root":"/w/a"}`)
	mustWriteFile(t, filepath.Join(root, dirStandalone, "a--22222222", dirActive, "log-member.md"), "# Member\nEvent: grouped note.\n")
	mustWriteFile(t, filepath.Join(root, dirStandalone, "x--33333333", fileScopeJSON), `{"root":"/x"}`)
	mustWriteFile(t, filepath.Join(root, dirStandalone, "x--33333333", dirActive, "log-loose.md"), "# Loose\nEvent: loose note.\n")

	idx := NewSearchIndex(root)
	if err := idx.Rebuild(); err != nil {
		t.Fatalf("Rebuild failed: %v", err)
	}
	pinned := idx.Query("note", dirPinned, "", 20)
	if len(pinned) != 1 || pinned[0].Name != "log-member.md" || pinned[0].ScopeID != testPinID ||
		pinned[0].Path != "standalone/a--22222222/active/log-member.md" {
		t.Fatalf("expected member note under pinned group, got %+v", pinned)
	}
	if loose := idx.Query("note", dirStandalone, "", 20); len(loose) != 1 || loose[0].Name != "log-loose.md" {
		t.Fatalf("expected only the ungrouped note under standalone, got %+v", loose)
	}
}
