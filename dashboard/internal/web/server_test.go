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

	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/store"
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

	srv := NewServer(store, 7337, hub, nil)
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
	if health["app"] != "memoir-ui" || health["pid"] != float64(os.Getpid()) || health["version"] != "" {
		t.Fatalf("health missing app/pid/version: %#v", health)
	}
}

func TestServerTreeAndFileEndpoints(t *testing.T) {
	storeRoot := t.TempDir()
	wikiFile := filepath.Join(storeRoot, "repos", "github.com__acme__app", "wiki", "index.md")
	decisionFile := filepath.Join(storeRoot, "repos", "github.com__acme__app", "wiki", "decisions", "use-go.md")
	if err := os.MkdirAll(filepath.Dir(decisionFile), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(decisionFile, []byte("# Use Go\nType: decision\nUpdated: 2026-11-21\n"), 0o644); err != nil {
		t.Fatalf("write decision: %v", err)
	}
	if err := os.WriteFile(wikiFile, []byte("# Wiki Index\nUpdated: 2026-11-21\n\n- [[decisions/use-go]]\n"), 0o644); err != nil {
		t.Fatalf("write index: %v", err)
	}

	hub := NewHub()
	defer hub.Close()
	srv := NewServer(storeRoot, 7337, hub, nil)
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
	htmlBody, _ := fileResp["html"].(string)
	if !strings.Contains(htmlBody, `class="wikilink"`) {
		t.Fatalf("expected rendered wikilink in html, got %q", htmlBody)
	}
	badges, ok := fileResp["badges"].([]any)
	if !ok || len(badges) == 0 {
		t.Fatalf("expected parsed header badges, got %#v", fileResp["badges"])
	}

	// Verify backlinks on target decision page.
	dReq := httptest.NewRequest(http.MethodGet, "/api/file?path=repos/github.com__acme__app/wiki/decisions/use-go.md", nil)
	dRec := httptest.NewRecorder()
	h.ServeHTTP(dRec, dReq)
	if dRec.Code != http.StatusOK {
		t.Fatalf("GET decision wiki status = %d, want 200", dRec.Code)
	}
	var dResp map[string]any
	if err := json.Unmarshal(dRec.Body.Bytes(), &dResp); err != nil {
		t.Fatalf("decode decision file: %v", err)
	}
	backlinks, ok := dResp["backlinks"].([]any)
	if !ok || len(backlinks) != 1 {
		t.Fatalf("expected 1 backlink from index.md, got %#v", dResp["backlinks"])
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

	srv := NewServer(store, 7337, hub, nil)
	pr, pw := io.Pipe()
	defer func() { _ = pr.Close() }()

	rw := newSSEPipeWriter(pw)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	req := httptest.NewRequest(http.MethodGet, "/events", nil).WithContext(ctx)
	done := make(chan struct{})
	go func() {
		defer close(done)
		defer func() { _ = pw.Close() }()
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

	srv := NewServer(t.TempDir(), 7337, hub, nil)
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

func TestServerSearchAndGCPruneEndpoints(t *testing.T) {
	storeRoot := t.TempDir()
	healthyDir := t.TempDir()
	missingDir := filepath.Join(t.TempDir(), "gone")

	repoBase := filepath.Join(storeRoot, "repos", "github.com__acme__app")
	if err := os.MkdirAll(filepath.Join(repoBase, "wiki"), 0o755); err != nil {
		t.Fatalf("mkdir: %v", err)
	}
	if err := os.WriteFile(filepath.Join(repoBase, "wiki", "index.md"), []byte("# App Wiki\nUpdated: 2026-11-21\n"), 0o644); err != nil {
		t.Fatalf("write wiki: %v", err)
	}

	healthyClone := filepath.Join(repoBase, "clones", "app--11111111")
	if err := os.MkdirAll(filepath.Join(healthyClone, "paths", "_main", "active"), 0o755); err != nil {
		t.Fatalf("mkdir healthy: %v", err)
	}
	_ = os.WriteFile(filepath.Join(healthyClone, "clone.json"), []byte(`{"root":"`+healthyDir+`"}`), 0o644)
	_ = os.WriteFile(filepath.Join(healthyClone, "paths", "_main", "active", "decision-keep.md"), []byte("# Keep\nDecision: keep live\n"), 0o644)

	orphanClone := filepath.Join(repoBase, "clones", "old--22222222")
	if err := os.MkdirAll(filepath.Join(orphanClone, "paths", "_main", "active"), 0o755); err != nil {
		t.Fatalf("mkdir orphan: %v", err)
	}
	_ = os.WriteFile(filepath.Join(orphanClone, "clone.json"), []byte(`{"root":"`+missingDir+`"}`), 0o644)
	_ = os.WriteFile(filepath.Join(orphanClone, "paths", "_main", "active", "decision-stale.md"), []byte("# Stale\nDecision: remove stale token\n"), 0o644)

	idx := store.NewSearchIndex(storeRoot)
	if err := idx.Rebuild(); err != nil {
		t.Fatalf("Rebuild: %v", err)
	}

	hub := NewHub()
	defer hub.Close()
	srv := NewServer(storeRoot, 7337, hub, idx)
	h := srv.Handler()

	// Search query with scope & type filters.
	sReq := httptest.NewRequest(http.MethodGet, "/api/search?q=stale&scope=repo&type=decision", nil)
	sRec := httptest.NewRecorder()
	h.ServeHTTP(sRec, sReq)
	if sRec.Code != http.StatusOK {
		t.Fatalf("GET /api/search status = %d", sRec.Code)
	}
	var sResp map[string]any
	_ = json.Unmarshal(sRec.Body.Bytes(), &sResp)
	if int(sResp["total"].(float64)) != 1 {
		t.Fatalf("expected 1 search result, got %#v", sResp)
	}

	// GET /api/gc lists only the orphan clone.
	gReq := httptest.NewRequest(http.MethodGet, "/api/gc", nil)
	gRec := httptest.NewRecorder()
	h.ServeHTTP(gRec, gReq)
	if gRec.Code != http.StatusOK {
		t.Fatalf("GET /api/gc status = %d", gRec.Code)
	}
	var gResp struct {
		Orphans []store.Orphan `json:"orphans"`
	}
	_ = json.Unmarshal(gRec.Body.Bytes(), &gResp)
	if len(gResp.Orphans) != 1 || gResp.Orphans[0].RelPath != "repos/github.com__acme__app/clones/old--22222222" {
		t.Fatalf("unexpected orphans: %+v", gResp.Orphans)
	}

	// POST /api/gc/prune requires confirm=true.
	noConfirm := httptest.NewRequest(http.MethodPost, "/api/gc/prune", strings.NewReader(`{"path":"repos/github.com__acme__app/clones/old--22222222","confirm":false}`))
	noConfirmRec := httptest.NewRecorder()
	h.ServeHTTP(noConfirmRec, noConfirm)
	if noConfirmRec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 without confirm=true, got %d", noConfirmRec.Code)
	}

	// POST /api/gc/prune blocks foreign Origin.
	foreign := httptest.NewRequest(http.MethodPost, "/api/gc/prune", strings.NewReader(`{"path":"repos/github.com__acme__app/clones/old--22222222","confirm":true}`))
	foreign.Header.Set("Origin", "https://evil.example")
	foreignRec := httptest.NewRecorder()
	h.ServeHTTP(foreignRec, foreign)
	if foreignRec.Code != http.StatusForbidden {
		t.Fatalf("expected 403 for foreign origin, got %d", foreignRec.Code)
	}

	// POST /api/gc/prune rejects healthy clone with 409 Conflict.
	healthyReq := httptest.NewRequest(http.MethodPost, "/api/gc/prune", strings.NewReader(`{"path":"repos/github.com__acme__app/clones/app--11111111","confirm":true}`))
	healthyRec := httptest.NewRecorder()
	h.ServeHTTP(healthyRec, healthyReq)
	if healthyRec.Code != http.StatusConflict {
		t.Fatalf("expected 409 for healthy clone, got %d", healthyRec.Code)
	}

	// Valid confirmed prune deletes orphan and refreshes search index.
	okReq := httptest.NewRequest(http.MethodPost, "/api/gc/prune", strings.NewReader(`{"path":"repos/github.com__acme__app/clones/old--22222222","confirm":true}`))
	okReq.Header.Set("Origin", "http://127.0.0.1:7337")
	okRec := httptest.NewRecorder()
	h.ServeHTTP(okRec, okReq)
	if okRec.Code != http.StatusOK {
		t.Fatalf("expected 200 on valid prune, got %d (%s)", okRec.Code, okRec.Body.String())
	}

	// Search index should no longer return pruned clone's decision.
	afterReq := httptest.NewRequest(http.MethodGet, "/api/search?q=stale", nil)
	afterRec := httptest.NewRecorder()
	h.ServeHTTP(afterRec, afterReq)
	var afterResp map[string]any
	_ = json.Unmarshal(afterRec.Body.Bytes(), &afterResp)
	if int(afterResp["total"].(float64)) != 0 {
		t.Fatalf("expected pruned document removed from search index, got %#v", afterResp)
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
