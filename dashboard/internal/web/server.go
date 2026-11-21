package web

import (
	"embed"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"path"
	"strings"
	"time"

	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/render"
	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/store"
)

//go:embed assets/*
var assetsFS embed.FS

// Server serves the embedded dashboard UI, store tree/file APIs, and SSE live-reload endpoints.
type Server struct {
	StoreRoot string
	Port      int
	Hub       *Hub
}

// NewServer constructs a dashboard HTTP server.
func NewServer(storeRoot string, port int, hub *Hub) *Server {
	return &Server{
		StoreRoot: storeRoot,
		Port:      port,
		Hub:       hub,
	}
}

// Handler returns the HTTP handler wrapped with localhost origin protection.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /", s.handleIndex)

	sub, err := fs.Sub(assetsFS, "assets")
	if err != nil {
		panic(err)
	}
	assetServer := http.StripPrefix("/assets/", http.FileServer(http.FS(sub)))
	mux.Handle("GET /assets/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-cache")
		assetServer.ServeHTTP(w, r)
	}))

	mux.HandleFunc("GET /api/health", s.handleHealth)
	mux.HandleFunc("GET /api/tree", s.handleTree)
	mux.HandleFunc("GET /api/file", s.handleFile)
	mux.HandleFunc("GET /events", s.handleEvents)

	return s.localhostGuard(mux)
}

func (s *Server) localhostGuard(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			origin := strings.TrimSpace(r.Header.Get("Origin"))
			if origin != "" && !s.isAllowedOrigin(origin) {
				writeJSONError(w, http.StatusForbidden, "forbidden origin")
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) isAllowedOrigin(origin string) bool {
	if s.Port > 0 {
		expected1 := fmt.Sprintf("http://127.0.0.1:%d", s.Port)
		expected2 := fmt.Sprintf("http://localhost:%d", s.Port)
		return origin == expected1 || origin == expected2
	}
	u, err := url.Parse(origin)
	if err != nil {
		return false
	}
	host := u.Hostname()
	return u.Scheme == "http" && (host == "127.0.0.1" || host == "localhost")
}

func (s *Server) handleIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path != "/" && r.URL.Path != "/index.html" {
		http.NotFound(w, r)
		return
	}
	data, err := assetsFS.ReadFile("assets/index.html")
	if err != nil {
		http.Error(w, "missing embedded index", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Header().Set("Cache-Control", "no-cache")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(data)
}

func (s *Server) handleHealth(w http.ResponseWriter, r *http.Request) {
	info, err := os.Stat(s.StoreRoot)
	exists := err == nil && info.IsDir()
	writeJSON(w, http.StatusOK, map[string]any{
		"status":       "ok",
		"store":        s.StoreRoot,
		"store_exists": exists,
		"port":         s.Port,
	})
}

func (s *Server) handleTree(w http.ResponseWriter, r *http.Request) {
	tree, err := store.Scan(s.StoreRoot)
	if err != nil {
		writeJSONError(w, http.StatusInternalServerError, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, tree)
}

func (s *Server) handleFile(w http.ResponseWriter, r *http.Request) {
	relPath := strings.TrimSpace(r.URL.Query().Get("path"))
	resolved, err := store.ResolveSafeFile(s.StoreRoot, relPath)
	if err != nil {
		switch {
		case errors.Is(err, store.ErrInvalidPath):
			writeJSONError(w, http.StatusBadRequest, "invalid file path")
		case errors.Is(err, store.ErrNotFound):
			writeJSONError(w, http.StatusNotFound, "file not found")
		default:
			writeJSONError(w, http.StatusInternalServerError, err.Error())
		}
		return
	}

	raw, err := os.ReadFile(resolved)
	if err != nil {
		if os.IsNotExist(err) {
			writeJSONError(w, http.StatusNotFound, "file not found")
			return
		}
		writeJSONError(w, http.StatusInternalServerError, err.Error())
		return
	}

	cleanRel := path.Clean(relPath)
	kind, archived := store.ClassifyFile(cleanRel)
	rawStr := string(raw)

	doc, err := render.RenderDocument(s.StoreRoot, cleanRel, rawStr)
	if err != nil {
		writeJSONError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"path":           cleanRel,
		"name":           path.Base(cleanRel),
		"title":          doc.Title,
		"kind":           kind,
		"archived":       archived,
		"raw":            rawStr,
		"html":           doc.HTML,
		"badges":         doc.Badges,
		"sources":        doc.Sources,
		"backlinks":      doc.Backlinks,
		"decision_chain": doc.DecisionChain,
	})
}

func (s *Server) handleEvents(w http.ResponseWriter, r *http.Request) {
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeJSONError(w, http.StatusInternalServerError, "streaming unsupported")
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	ch, unsub := s.Hub.Subscribe()
	defer unsub()

	connected := Event{
		Type:      "connected",
		Timestamp: time.Now().UTC().Format(time.RFC3339),
	}
	if err := writeSSEEvent(w, "connected", connected); err != nil {
		return
	}
	flusher.Flush()

	keepalive := time.NewTicker(30 * time.Second)
	defer keepalive.Stop()

	for {
		select {
		case <-r.Context().Done():
			return
		case <-s.Hub.Done():
			return
		case ev := <-ch:
			eventName := ev.Type
			if eventName == "" {
				eventName = "change"
			}
			if err := writeSSEEvent(w, eventName, ev); err != nil {
				return
			}
			flusher.Flush()
		case <-keepalive.C:
			if _, err := fmt.Fprint(w, ": ping\n\n"); err != nil {
				return
			}
			flusher.Flush()
		}
	}
}

func writeSSEEvent(w http.ResponseWriter, name string, payload any) error {
	data, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(w, "event: %s\ndata: %s\n\n", name, data)
	return err
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeJSONError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]string{"error": msg})
}
