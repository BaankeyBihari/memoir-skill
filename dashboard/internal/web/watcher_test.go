package web

import (
	"context"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

func TestWatcherDetectsFileAndDynamicSubdir(t *testing.T) {
	store := t.TempDir()
	hub := NewHub()
	defer hub.Close()

	ch, unsub := hub.Subscribe()
	defer unsub()

	w, err := NewWatcher(store, hub, 30*time.Millisecond, nil)
	if err != nil {
		t.Fatalf("NewWatcher failed: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go w.Start(ctx)

	// Give fsnotify goroutine a brief moment to enter select loop.
	time.Sleep(40 * time.Millisecond)

	// 1. Direct file creation.
	firstFile := filepath.Join(store, "pinned.json")
	if err := os.WriteFile(firstFile, []byte("[]\n"), 0o644); err != nil {
		t.Fatalf("write pinned.json: %v", err)
	}

	ev := waitForEvent(t, ch, 2*time.Second)
	if ev.Path != "pinned.json" {
		t.Fatalf("expected path pinned.json, got %q", ev.Path)
	}

	// 2. Dynamically created nested subdirectory should be watched automatically.
	nestedDir := filepath.Join(store, "repos", "r1", "wiki", "decisions")
	if err := os.MkdirAll(nestedDir, 0o755); err != nil {
		t.Fatalf("mkdir nested: %v", err)
	}

	// Drain the directory creation event before writing the file inside it.
	_ = waitForEvent(t, ch, 2*time.Second)
	time.Sleep(50 * time.Millisecond)

	nestedFile := filepath.Join(nestedDir, "store-location.md")
	if err := os.WriteFile(nestedFile, []byte("# Store Location\n"), 0o644); err != nil {
		t.Fatalf("write nested md: %v", err)
	}

	ev = waitForEventUntil(t, ch, 2*time.Second, func(e Event) bool {
		return e.Path == "repos/r1/wiki/decisions/store-location.md"
	})
	if ev.Op == "" {
		t.Fatalf("expected non-empty op on nested file event")
	}
}

func TestWatcherDebouncesRapidWrites(t *testing.T) {
	store := t.TempDir()
	hub := NewHub()
	defer hub.Close()

	var count atomic.Int32
	fired := make(chan struct{}, 16)
	w, err := NewWatcher(store, hub, 250*time.Millisecond, func(ev Event) {
		count.Add(1)
		select {
		case fired <- struct{}{}:
		default:
		}
	})
	if err != nil {
		t.Fatalf("NewWatcher failed: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go w.Start(ctx)

	time.Sleep(40 * time.Millisecond)

	target := filepath.Join(store, "notes.md")
	for i := 0; i < 8; i++ {
		if err := os.WriteFile(target, []byte("update\n"), 0o644); err != nil {
			t.Fatalf("write %d: %v", i, err)
		}
	}

	select {
	case <-fired:
	case <-time.After(2 * time.Second):
		t.Fatal("timed out waiting for debounced watcher event")
	}

	time.Sleep(150 * time.Millisecond)
	got := count.Load()
	if got != 1 {
		t.Fatalf("expected 1 debounced event for rapid writes, got %d", got)
	}
}

func TestWatcherMissingStoreDoesNotFail(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "does-not-exist")
	hub := NewHub()
	defer hub.Close()

	w, err := NewWatcher(missing, hub, 30*time.Millisecond, nil)
	if err != nil {
		t.Fatalf("expected missing store to succeed, got error: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		w.Start(ctx)
		close(done)
	}()

	time.Sleep(40 * time.Millisecond)
	cancel()

	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("watcher did not stop cleanly on cancel")
	}
}

func waitForEvent(t *testing.T, ch <-chan Event, timeout time.Duration) Event {
	t.Helper()
	select {
	case ev := <-ch:
		return ev
	case <-time.After(timeout):
		t.Fatalf("timed out waiting for watcher event after %v", timeout)
		return Event{}
	}
}

func waitForEventUntil(t *testing.T, ch <-chan Event, timeout time.Duration, pred func(Event) bool) Event {
	t.Helper()
	deadline := time.After(timeout)
	for {
		select {
		case ev := <-ch:
			if pred(ev) {
				return ev
			}
		case <-deadline:
			t.Fatalf("timed out waiting for matching watcher event after %v", timeout)
			return Event{}
		}
	}
}
