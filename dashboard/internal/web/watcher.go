package web

import (
	"context"
	"io/fs"
	"log"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
)

// Event represents a server-sent event delivered to connected clients.
type Event struct {
	Type      string `json:"type"`
	Op        string `json:"op,omitempty"`
	Path      string `json:"path,omitempty"`
	Timestamp string `json:"timestamp"`
}

// Hub broadcasts store change events to all active SSE subscribers.
type Hub struct {
	mu     sync.Mutex
	subs   map[chan Event]struct{}
	done   chan struct{}
	closed bool
}

// NewHub initializes a broadcast hub for SSE clients.
func NewHub() *Hub {
	return &Hub{
		subs: make(map[chan Event]struct{}),
		done: make(chan struct{}),
	}
}

// Subscribe registers a listener channel and returns an unsubscribe function.
func (h *Hub) Subscribe() (<-chan Event, func()) {
	h.mu.Lock()
	defer h.mu.Unlock()

	ch := make(chan Event, 64)
	if h.closed {
		return ch, func() {}
	}
	h.subs[ch] = struct{}{}

	var once sync.Once
	unsub := func() {
		once.Do(func() {
			h.mu.Lock()
			delete(h.subs, ch)
			h.mu.Unlock()
		})
	}
	return ch, unsub
}

// Broadcast delivers an event to all subscribers without blocking on slow readers.
func (h *Hub) Broadcast(ev Event) {
	h.mu.Lock()
	defer h.mu.Unlock()

	if h.closed {
		return
	}
	for ch := range h.subs {
		select {
		case ch <- ev:
		default:
		}
	}
}

// Close shuts down the hub and signals all connected subscribers to exit.
func (h *Hub) Close() {
	h.mu.Lock()
	defer h.mu.Unlock()

	if h.closed {
		return
	}
	h.closed = true
	clear(h.subs)
	close(h.done)
}

// Done is closed when the hub shuts down.
func (h *Hub) Done() <-chan struct{} {
	return h.done
}

// Watcher monitors the store directory tree recursively and emits debounced events.
type Watcher struct {
	root     string
	evalRoot string
	fsw      *fsnotify.Watcher
	hub      *Hub
	debounce time.Duration
	onChange func(Event)
}

// NewWatcher creates a recursive fsnotify watcher rooted at root.
// If root does not exist yet, NewWatcher succeeds and idles cleanly.
func NewWatcher(root string, hub *Hub, debounce time.Duration, onChange func(Event)) (*Watcher, error) {
	if debounce <= 0 {
		debounce = 100 * time.Millisecond
	}
	fsw, err := fsnotify.NewWatcher()
	if err != nil {
		return nil, err
	}

	absRoot, err := filepath.Abs(root)
	if err != nil {
		absRoot = filepath.Clean(root)
	}
	evalRoot := absRoot
	if resolved, err := filepath.EvalSymlinks(absRoot); err == nil {
		evalRoot = resolved
	}

	w := &Watcher{
		root:     absRoot,
		evalRoot: evalRoot,
		fsw:      fsw,
		hub:      hub,
		debounce: debounce,
		onChange: onChange,
	}

	info, err := os.Stat(absRoot)
	if err != nil {
		if os.IsNotExist(err) {
			log.Printf("memoir-ui: store directory %s does not exist yet; live watch inactive until restart after creation", absRoot)
			return w, nil
		}
		_ = fsw.Close()
		return nil, err
	}
	if !info.IsDir() {
		_ = fsw.Close()
		return nil, os.ErrInvalid
	}

	if err := w.addDirRecursive(absRoot); err != nil {
		_ = fsw.Close()
		return nil, err
	}
	return w, nil
}

// Start runs the event loop until ctx is canceled.
func (w *Watcher) Start(ctx context.Context) {
	defer func() { _ = w.fsw.Close() }()

	var (
		timer   *time.Timer
		timerCh <-chan time.Time
		pending *Event
	)

	flushPending := func() {
		if pending == nil {
			return
		}
		ev := *pending
		pending = nil
		if w.onChange != nil {
			w.onChange(ev)
		}
		if w.hub != nil {
			w.hub.Broadcast(ev)
		}
	}

	stopTimer := func() {
		if timer != nil {
			if !timer.Stop() {
				select {
				case <-timer.C:
				default:
				}
			}
		}
		timerCh = nil
	}

	for {
		select {
		case <-ctx.Done():
			stopTimer()
			return

		case err, ok := <-w.fsw.Errors:
			if !ok {
				return
			}
			log.Printf("memoir-ui: watcher error: %v", err)

		case ev, ok := <-w.fsw.Events:
			if !ok {
				return
			}
			if ev.Op == fsnotify.Chmod {
				continue
			}
			if shouldIgnorePath(ev.Name) {
				continue
			}

			if ev.Has(fsnotify.Create) {
				if info, err := os.Stat(ev.Name); err == nil && info.IsDir() {
					if err := w.addDirRecursive(ev.Name); err != nil {
						log.Printf("memoir-ui: watch subdir %s: %v", ev.Name, err)
					}
				}
			}

			changeEv := Event{
				Type:      "change",
				Op:        opString(ev.Op),
				Path:      w.relPath(ev.Name),
				Timestamp: time.Now().UTC().Format(time.RFC3339),
			}
			pending = &changeEv
			if timer == nil {
				timer = time.NewTimer(w.debounce)
			} else {
				if !timer.Stop() {
					select {
					case <-timer.C:
					default:
					}
				}
				timer.Reset(w.debounce)
			}
			timerCh = timer.C

		case <-timerCh:
			timerCh = nil
			flushPending()
		}
	}
}

func (w *Watcher) addDirRecursive(dir string) error {
	return filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			// Tolerate transient or unreadable subdirectories without aborting.
			return nil
		}
		if !d.IsDir() {
			return nil
		}
		if path != w.root && shouldIgnoreDir(d.Name()) {
			return filepath.SkipDir
		}
		if addErr := w.fsw.Add(path); addErr != nil && !os.IsNotExist(addErr) {
			log.Printf("memoir-ui: failed to watch %s: %v", path, addErr)
		}
		return nil
	})
}

func (w *Watcher) relPath(absPath string) string {
	if rel, err := filepath.Rel(w.root, absPath); err == nil && !strings.HasPrefix(rel, "..") {
		return filepath.ToSlash(rel)
	}
	if rel, err := filepath.Rel(w.evalRoot, absPath); err == nil && !strings.HasPrefix(rel, "..") {
		return filepath.ToSlash(rel)
	}
	return filepath.ToSlash(absPath)
}

func opString(op fsnotify.Op) string {
	switch {
	case op.Has(fsnotify.Create):
		return "create"
	case op.Has(fsnotify.Remove):
		return "remove"
	case op.Has(fsnotify.Rename):
		return "rename"
	case op.Has(fsnotify.Write):
		return "write"
	default:
		return "change"
	}
}

func shouldIgnoreDir(name string) bool {
	return name == ".git" || strings.HasPrefix(name, ".tmp")
}

func shouldIgnorePath(path string) bool {
	base := filepath.Base(path)
	if base == ".DS_Store" || base == ".pinned.lock" {
		return true
	}
	if strings.HasPrefix(base, ".tmp") || strings.HasPrefix(base, "#") {
		return true
	}
	if strings.HasSuffix(base, "~") || strings.HasSuffix(base, ".swp") || strings.HasSuffix(base, ".swx") {
		return true
	}
	return false
}
