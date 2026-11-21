package store

import (
	"path/filepath"
	"sync"
	"testing"
)

func TestSearchIndexQueryFiltersAndConcurrency(t *testing.T) {
	root := t.TempDir()

	mustWriteFile(t, filepath.Join(root, "repos", "github.com__acme__app", "wiki", "decisions", "use-go.md"),
		"# Use Go\nType: decision\nUpdated: 2026-11-21\n\nSingle binary HTTP server using goldmark.\n")
	mustWriteFile(t, filepath.Join(root, "repos", "github.com__acme__app", "clones", "app--11111111", "paths", "_main", "active", "decision-use-sse.md"),
		"# Use SSE\nDate: 2026-11-21\nDecision: Push live reload over Server-Sent Events.\n")
	mustWriteFile(t, filepath.Join(root, "repos", "github.com__acme__app", "clones", "app--11111111", "paths", "_main", "archive", "20261110-decision-old-polling.md"),
		"# Old Polling\nDate: 2026-11-10\nDecision: Replaced short polling with SSE live reload.\n")
	mustWriteFile(t, filepath.Join(root, "pinned", "notes--22222222", "paths", "_root", "active", "feedback-style.md"),
		"# Concise Style\nDate: 2026-11-21\nFeedback: Keep SSE payloads minimal.\n")
	mustWriteFile(t, filepath.Join(root, "standalone", "scratch--33333333", "active", "log-sse-check.md"),
		"# SSE Check\nDate: 2026-11-21\nEvent: Verified SSE stream.\n")

	idx := NewSearchIndex(root)
	if err := idx.Rebuild(); err != nil {
		t.Fatalf("Rebuild failed: %v", err)
	}

	// Full-text multi-token AND search.
	res := idx.Query("live reload", "", "", 20)
	if len(res) != 2 {
		t.Fatalf("expected 2 results for 'live reload', got %d: %+v", len(res), res)
	}
	// Active decision should rank above archived decision.
	if res[0].Archived || !res[1].Archived {
		t.Fatalf("expected active decision ranked ahead of archived: %+v", res)
	}

	// Scope filter.
	pinnedRes := idx.Query("sse", "pinned", "", 20)
	if len(pinnedRes) != 1 || pinnedRes[0].Scope != "pinned" {
		t.Fatalf("expected 1 pinned result, got %+v", pinnedRes)
	}

	// Type filter.
	wikiRes := idx.Query("goldmark", "", "wiki", 20)
	if len(wikiRes) != 1 || wikiRes[0].Type != "wiki" {
		t.Fatalf("expected 1 wiki result, got %+v", wikiRes)
	}

	// Filter-only (empty query).
	logRes := idx.Query("", "standalone", "log", 20)
	if len(logRes) != 1 || logRes[0].Type != "log" {
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
