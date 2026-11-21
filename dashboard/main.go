package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"time"

	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/store"
	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/web"
)

func main() {
	port := flag.Int("port", 7337, "HTTP listen port")
	storeFlag := flag.String("store", "", "Memoir store root (defaults to $MEMOIR_STORE or ~/.memoir)")
	openFlag := flag.Bool("open", false, "Open the dashboard in the default browser")
	flag.Parse()

	if *port < 1 || *port > 65535 {
		log.Fatalf("invalid --port %d: must be between 1 and 65535", *port)
	}

	storeRoot, err := resolveStoreRoot(*storeFlag)
	if err != nil {
		log.Fatalf("resolve store root: %v", err)
	}

	addr := fmt.Sprintf("127.0.0.1:%d", *port)
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Fatalf("listen %s: %v", addr, err)
	}

	searchIdx := store.NewSearchIndex(storeRoot)
	if err := searchIdx.Rebuild(); err != nil {
		log.Printf("memoir-ui: initial search index build: %v", err)
	}

	hub := web.NewHub()
	watcher, err := web.NewWatcher(storeRoot, hub, 100*time.Millisecond, func(web.Event) {
		if err := searchIdx.Rebuild(); err != nil {
			log.Printf("memoir-ui: search reindex error: %v", err)
		}
	})
	if err != nil {
		log.Fatalf("init watcher: %v", err)
	}

	ctx, stopSignals := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stopSignals()

	go watcher.Start(ctx)

	srv := web.NewServer(storeRoot, *port, hub, searchIdx)
	httpServer := &http.Server{
		Handler:           srv.Handler(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	url := fmt.Sprintf("http://%s", addr)
	log.Printf("memoir-ui listening on %s (store: %s)", url, storeRoot)

	if *openFlag {
		go openBrowser(url)
	}

	errCh := make(chan error, 1)
	go func() {
		if err := httpServer.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
		close(errCh)
	}()

	select {
	case err := <-errCh:
		if err != nil {
			log.Fatalf("server error: %v", err)
		}
	case <-ctx.Done():
		log.Printf("memoir-ui shutting down")
		hub.Close()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = httpServer.Shutdown(shutdownCtx)
	}
}

func resolveStoreRoot(explicit string) (string, error) {
	raw := strings.TrimSpace(explicit)
	if raw == "" {
		raw = strings.TrimSpace(os.Getenv("MEMOIR_STORE"))
	}
	if raw == "" {
		raw = "~/.memoir"
	}

	if raw == "~" || strings.HasPrefix(raw, "~/") {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		if raw == "~" {
			raw = home
		} else {
			raw = filepath.Join(home, strings.TrimPrefix(raw, "~/"))
		}
	}

	return filepath.Abs(filepath.Clean(raw))
}

func openBrowser(url string) {
	var cmd *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		cmd = exec.Command("open", url)
	case "linux":
		cmd = exec.Command("xdg-open", url)
	case "windows":
		cmd = exec.Command("rundll32", "url.dll,FileProtocolHandler", url)
	default:
		return
	}
	if err := cmd.Start(); err == nil {
		go func() { _ = cmd.Wait() }()
	}
}
