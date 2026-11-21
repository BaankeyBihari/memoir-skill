package web

import (
	"bufio"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

type ssePipeWriter struct {
	header http.Header
	pw     *io.PipeWriter
	once   sync.Once
	code   int
}

func newSSEPipeWriter(pw *io.PipeWriter) *ssePipeWriter {
	return &ssePipeWriter{
		header: make(http.Header),
		pw:     pw,
	}
}

func (w *ssePipeWriter) Header() http.Header {
	return w.header
}

func (w *ssePipeWriter) WriteHeader(statusCode int) {
	w.once.Do(func() {
		w.code = statusCode
	})
}

func (w *ssePipeWriter) Write(p []byte) (int, error) {
	w.WriteHeader(http.StatusOK)
	return w.pw.Write(p)
}

func (w *ssePipeWriter) Flush() {}

func TestServerServesEmbeddedAssetsAndThemes(t *testing.T) {
	store := t.TempDir()
	hub := NewHub()
	defer hub.Close()

	srv := NewServer(store, 7337, hub)
	h := srv.Handler()

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("GET / status = %d, want 200", rec.Code)
	}
	body := rec.Body.String()
	for _, want := range []string{
		`id="themeSelect"`,
		`value="midnight"`,
		`value="rose-pine"`,
		`value="rose-pine-dawn"`,
		`value="solarized-dark"`,
		`value="solarized-light"`,
		`value="sky-light"`,
		`value="zinc-light"`,
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("index.html missing %q", want)
		}
	}

	for _, asset := range []string{"/assets/app.css", "/assets/app.js"} {
		areq := httptest.NewRequest(http.MethodGet, asset, nil)
		arec := httptest.NewRecorder()
		h.ServeHTTP(arec, areq)
		if arec.Code != http.StatusOK {
			t.Fatalf("GET %s status = %d, want 200", asset, arec.Code)
		}
	}

	hreq := httptest.NewRequest(http.MethodGet, "/api/health", nil)
	hrec := httptest.NewRecorder()
	h.ServeHTTP(hrec, hreq)
	if hrec.Code != http.StatusOK {
		t.Fatalf("GET /api/health status = %d, want 200", hrec.Code)
	}
	var health map[string]any
	if err := json.Unmarshal(hrec.Body.Bytes(), &health); err != nil {
		t.Fatalf("decode health: %v", err)
	}
	if health["status"] != "ok" || health["store_exists"] != true {
		t.Fatalf("unexpected health payload: %#v", health)
	}
}

func TestServerTreeAndFileEndpoints(t *testing.T) {
	storeRoot := t.TempDir()
	wikiFile := filepath.Join(storeRoot, "repos", "github.com__acme__app", "wiki", "index.md")
	if err := os.MkdirAll(filepath.Dir(wikiFile), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(wikiFile, []byte("# Wiki Index\nUpdated: 2026-11-21\n"), 0o644); err != nil {
		t.Fatalf("write index: %v", err)
	}

	hub := NewHub()
	defer hub.Close()
	srv := NewServer(storeRoot, 7337, hub)
	h := srv.Handler()

	// GET /api/tree
	tReq := httptest.NewRequest(http.MethodGet, "/api/tree", nil)
	tRec := httptest.NewRecorder()
	h.ServeHTTP(tRec, tReq)
	if tRec.Code != http.StatusOK {
		t.Fatalf("GET /api/tree status = %d, want 200", tRec.Code)
	}
	var tree map[string]any
	if err := json.Unmarshal(tRec.Body.Bytes(), &tree); err != nil {
		t.Fatalf("decode tree: %v", err)
	}
	repos, ok := tree["repos"].([]any)
	if !ok || len(repos) != 1 {
		t.Fatalf("expected 1 repo in tree, got %#v", tree["repos"])
	}

	// GET /api/file valid
	fReq := httptest.NewRequest(http.MethodGet, "/api/file?path=repos/github.com__acme__app/wiki/index.md", nil)
	fRec := httptest.NewRecorder()
	h.ServeHTTP(fRec, fReq)
	if fRec.Code != http.StatusOK {
		t.Fatalf("GET /api/file status = %d, want 200", fRec.Code)
	}
	var fileResp map[string]any
	if err := json.Unmarshal(fRec.Body.Bytes(), &fileResp); err != nil {
		t.Fatalf("decode file: %v", err)
	}
	if fileResp["title"] != "Wiki Index" || fileResp["kind"] != "wiki" {
		t.Fatalf("unexpected file payload: %#v", fileResp)
	}

	// GET /api/file invalid traversal
	badReq := httptest.NewRequest(http.MethodGet, "/api/file?path=../etc/passwd", nil)
	badRec := httptest.NewRecorder()
	h.ServeHTTP(badRec, badReq)
	if badRec.Code != http.StatusBadRequest {
		t.Fatalf("GET /api/file traversal status = %d, want 400", badRec.Code)
	}

	// GET /api/file missing
	missReq := httptest.NewRequest(http.MethodGet, "/api/file?path=repos/github.com__acme__app/wiki/missing.md", nil)
	missRec := httptest.NewRecorder()
	h.ServeHTTP(missRec, missReq)
	if missRec.Code != http.StatusNotFound {
		t.Fatalf("GET /api/file missing status = %d, want 404", missRec.Code)
	}
}

func TestServerSSEStreamAndClose(t *testing.T) {
	store := t.TempDir()
	hub := NewHub()
	defer hub.Close()

	srv := NewServer(store, 7337, hub)
	pr, pw := io.Pipe()
	defer pr.Close()

	rw := newSSEPipeWriter(pw)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	req := httptest.NewRequest(http.MethodGet, "/events", nil).WithContext(ctx)
	done := make(chan struct{})
	go func() {
		defer close(done)
		defer pw.Close()
		srv.Handler().ServeHTTP(rw, req)
	}()

	reader := bufio.NewReader(pr)
	firstEvent := readSSEBlock(t, reader)
	if !strings.Contains(firstEvent, "event: connected") {
		t.Fatalf("expected connected event, got %q", firstEvent)
	}
	if ct := rw.Header().Get("Content-Type"); !strings.HasPrefix(ct, "text/event-stream") {
		t.Fatalf("Content-Type = %q, want text/event-stream", ct)
	}

	hub.Broadcast(Event{
		Type:      "change",
		Op:        "write",
		Path:      "repos/r1/wiki/index.md",
		Timestamp: time.Now().UTC().Format(time.RFC3339),
	})

	secondEvent := readSSEBlock(t, reader)
	if !strings.Contains(secondEvent, "event: change") || !strings.Contains(secondEvent, "repos/r1/wiki/index.md") {
		t.Fatalf("expected change event with path, got %q", secondEvent)
	}

	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("SSE handler did not exit after request cancel")
	}
}

func TestLocalhostGuardRejectsForeignOrigin(t *testing.T) {
	hub := NewHub()
	defer hub.Close()

	srv := NewServer(t.TempDir(), 7337, hub)
	h := srv.Handler()

	req := httptest.NewRequest(http.MethodPost, "/api/health", nil)
	req.Header.Set("Origin", "https://evil.example")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusForbidden {
		t.Fatalf("POST with foreign origin status = %d, want 403", rec.Code)
	}

	okReq := httptest.NewRequest(http.MethodPost, "/api/health", nil)
	okReq.Header.Set("Origin", "http://127.0.0.1:7337")
	okRec := httptest.NewRecorder()
	h.ServeHTTP(okRec, okReq)
	if okRec.Code == http.StatusForbidden {
		t.Fatalf("POST with localhost origin should not return 403")
	}
}

func readSSEBlock(t *testing.T, r *bufio.Reader) string {
	t.Helper()
	var b strings.Builder
	for {
		line, err := r.ReadString('\n')
		if err != nil && err != io.EOF {
			t.Fatalf("read SSE: %v", err)
		}
		b.WriteString(line)
		if line == "\n" || err == io.EOF {
			return b.String()
		}
	}
}
