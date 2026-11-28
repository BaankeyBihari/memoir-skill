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

const (
	apiHealth     = "/api/health"
	apiGCPrune    = "/api/gc/prune"
	testRepoID    = "github.com__acme__app"
	hdrOrigin     = "Origin"
	relDirRepos   = "repos"
	relDirPaths   = "paths"
	relKeyMain    = "_main"
	relDirActive  = "active"
	evilOriginURL = "https://evil.example"
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

func writeWebTestFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o750); err != nil {
		t.Fatalf("mkdir %s: %v", filepath.Dir(path), err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("write %s: %v", path, err)
	}
}

func verifyEmbeddedAssets(t *testing.T, h http.Handler) {
	t.Helper()
	assetChecks := map[string][]string{
		"/assets/app.css": {".sidebar-resizer", "--sidebar-width"},
		"/assets/app.js":  {"initSidebarResize", "formatTreeFileLabel"},
	}
	for asset, markers := range assetChecks {
		areq := httptest.NewRequest(http.MethodGet, asset, nil)
		arec := httptest.NewRecorder()
		h.ServeHTTP(arec, areq)
		if arec.Code != http.StatusOK {
			t.Fatalf("GET %s status = %d, want 200", asset, arec.Code)
		}
		assetBody := arec.Body.String()
		for _, want := range markers {
			if !strings.Contains(assetBody, want) {
				t.Fatalf("%s missing %q", asset, want)
			}
		}
	}
}

func TestServerServesEmbeddedAssetsAndThemes(t *testing.T) {
	storeRoot := t.TempDir()
	hub := NewHub()
	defer hub.Close()

	srv := NewServer(storeRoot, 7337, hub, nil)
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
		`id="sidebarResizer"`,
		`memoir-ui.sidebarWidth`,
	} {
		if !strings.Contains(body, want) {
			t.Fatalf("index.html missing %q", want)
		}
	}

	verifyEmbeddedAssets(t, h)

	hreq := httptest.NewRequest(http.MethodGet, apiHealth, nil)
	hrec := httptest.NewRecorder()
	h.ServeHTTP(hrec, hreq)
	if hrec.Code != http.StatusOK {
		t.Fatalf("GET %s status = %d, want 200", apiHealth, hrec.Code)
	}
	var health map[string]any
	if err := json.Unmarshal(hrec.Body.Bytes(), &health); err != nil {
		t.Fatalf("decode health: %v", err)
	}
	if health["status"] != "ok" || health["store_exists"] != true ||
		health["app"] != appName || health["pid"] != float64(os.Getpid()) || health["version"] != "" {
		t.Fatalf("unexpected health payload: %#v", health)
	}
}

func assertTreeHasOneRepo(t *testing.T, h http.Handler) {
	t.Helper()
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
	if repos, ok := tree[relDirRepos].([]any); !ok || len(repos) != 1 {
		t.Fatalf("expected 1 repo in tree, got %#v", tree[relDirRepos])
	}
}

func assertRenderedWikiAndBacklinks(t *testing.T, h http.Handler) {
	t.Helper()
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
	if badges, ok := fileResp["badges"].([]any); !ok || len(badges) == 0 {
		t.Fatalf("expected parsed header badges, got %#v", fileResp["badges"])
	}

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
	if backlinks, ok := dResp["backlinks"].([]any); !ok || len(backlinks) != 1 {
		t.Fatalf("expected 1 backlink from index.md, got %#v", dResp["backlinks"])
	}
}

func TestServerTreeAndFileEndpoints(t *testing.T) {
	storeRoot := t.TempDir()
	wikiFile := filepath.Join(storeRoot, relDirRepos, testRepoID, "wiki", "index.md")
	decisionFile := filepath.Join(storeRoot, relDirRepos, testRepoID, "wiki", "decisions", "use-go.md")
	writeWebTestFile(t, decisionFile, "# Use Go\nType: decision\nUpdated: 2026-11-21\n")
	writeWebTestFile(t, wikiFile, "# Wiki Index\nUpdated: 2026-11-21\n\n- [[decisions/use-go]]\n")

	hub := NewHub()
	defer hub.Close()
	h := NewServer(storeRoot, 7337, hub, nil).Handler()

	assertTreeHasOneRepo(t, h)
	assertRenderedWikiAndBacklinks(t, h)

	badReq := httptest.NewRequest(http.MethodGet, "/api/file?path=../etc/passwd", nil)
	badRec := httptest.NewRecorder()
	h.ServeHTTP(badRec, badReq)
	if badRec.Code != http.StatusBadRequest {
		t.Fatalf("GET /api/file traversal status = %d, want 400", badRec.Code)
	}

	missReq := httptest.NewRequest(http.MethodGet, "/api/file?path=repos/github.com__acme__app/wiki/missing.md", nil)
	missRec := httptest.NewRecorder()
	h.ServeHTTP(missRec, missReq)
	if missRec.Code != http.StatusNotFound {
		t.Fatalf("GET /api/file missing status = %d, want 404", missRec.Code)
	}
}

func TestServerSSEStreamAndClose(t *testing.T) {
	storeRoot := t.TempDir()
	hub := NewHub()
	defer hub.Close()

	srv := NewServer(storeRoot, 7337, hub, nil)
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
		Type:      eventChange,
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

	h := NewServer(t.TempDir(), 7337, hub, nil).Handler()

	req := httptest.NewRequest(http.MethodPost, apiHealth, nil)
	req.Header.Set(hdrOrigin, evilOriginURL)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	if rec.Code != http.StatusForbidden {
		t.Fatalf("POST with foreign origin status = %d, want 403", rec.Code)
	}

	okReq := httptest.NewRequest(http.MethodPost, apiHealth, nil)
	okReq.Header.Set(hdrOrigin, "http://127.0.0.1:7337")
	okRec := httptest.NewRecorder()
	h.ServeHTTP(okRec, okReq)
	if okRec.Code == http.StatusForbidden {
		t.Fatalf("POST with localhost origin should not return 403")
	}
}

func seedSearchAndGCStore(t *testing.T, storeRoot string) {
	t.Helper()
	healthyDir := t.TempDir()
	missingDir := filepath.Join(t.TempDir(), "gone")

	repoBase := filepath.Join(storeRoot, relDirRepos, testRepoID)
	writeWebTestFile(t, filepath.Join(repoBase, "wiki", "index.md"), "# App Wiki\nUpdated: 2026-11-21\n")

	healthyClone := filepath.Join(repoBase, "clones", "app--11111111")
	writeWebTestFile(t, filepath.Join(healthyClone, "clone.json"), `{"root":"`+healthyDir+`"}`)
	writeWebTestFile(t, filepath.Join(healthyClone, relDirPaths, relKeyMain, relDirActive, "decision-keep.md"), "# Keep\nDecision: keep live\n")

	orphanClone := filepath.Join(repoBase, "clones", "old--22222222")
	writeWebTestFile(t, filepath.Join(orphanClone, "clone.json"), `{"root":"`+missingDir+`"}`)
	writeWebTestFile(t, filepath.Join(orphanClone, relDirPaths, relKeyMain, relDirActive, "decision-stale.md"), "# Stale\nDecision: remove stale token\n")
}

func verifyGCPruneGuards(t *testing.T, h http.Handler) {
	t.Helper()
	noConfirm := httptest.NewRequest(http.MethodPost, apiGCPrune, strings.NewReader(`{"path":"repos/github.com__acme__app/clones/old--22222222","confirm":false}`))
	noConfirmRec := httptest.NewRecorder()
	h.ServeHTTP(noConfirmRec, noConfirm)
	if noConfirmRec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400 without confirm=true, got %d", noConfirmRec.Code)
	}

	foreign := httptest.NewRequest(http.MethodPost, apiGCPrune, strings.NewReader(`{"path":"repos/github.com__acme__app/clones/old--22222222","confirm":true}`))
	foreign.Header.Set(hdrOrigin, evilOriginURL)
	foreignRec := httptest.NewRecorder()
	h.ServeHTTP(foreignRec, foreign)
	if foreignRec.Code != http.StatusForbidden {
		t.Fatalf("expected 403 for foreign origin, got %d", foreignRec.Code)
	}

	healthyReq := httptest.NewRequest(http.MethodPost, apiGCPrune, strings.NewReader(`{"path":"repos/github.com__acme__app/clones/app--11111111","confirm":true}`))
	healthyRec := httptest.NewRecorder()
	h.ServeHTTP(healthyRec, healthyReq)
	if healthyRec.Code != http.StatusConflict {
		t.Fatalf("expected 409 for healthy clone, got %d", healthyRec.Code)
	}
}

func TestServerSearchAndGCPruneEndpoints(t *testing.T) {
	storeRoot := t.TempDir()
	seedSearchAndGCStore(t, storeRoot)

	idx := store.NewSearchIndex(storeRoot)
	if err := idx.Rebuild(); err != nil {
		t.Fatalf("Rebuild: %v", err)
	}

	hub := NewHub()
	defer hub.Close()
	h := NewServer(storeRoot, 7337, hub, idx).Handler()

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

	verifyGCPruneGuards(t, h)

	okReq := httptest.NewRequest(http.MethodPost, apiGCPrune, strings.NewReader(`{"path":"repos/github.com__acme__app/clones/old--22222222","confirm":true}`))
	okReq.Header.Set(hdrOrigin, "http://127.0.0.1:7337")
	okRec := httptest.NewRecorder()
	h.ServeHTTP(okRec, okReq)
	if okRec.Code != http.StatusOK {
		t.Fatalf("expected 200 on valid prune, got %d (%s)", okRec.Code, okRec.Body.String())
	}

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
