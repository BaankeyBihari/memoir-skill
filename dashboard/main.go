package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/store"
	"github.com/BaankeyBihari/memoir-skill/dashboard/internal/web"
)

var version = "dev"

// latestURL is the GitHub API endpoint check-update asks; tests point it at a local server.
var latestURL = "https://api.github.com/repos/BaankeyBihari/memoir-skill/releases/latest"

const installCmd = "curl -fsSL https://raw.githubusercontent.com/BaankeyBihari/memoir-skill/main/scripts/install.sh | bash"

const usage = `Usage: memoir-ui [command] [flags]

Commands:
  (none)        Run the dashboard server in the foreground (--port, --store, --open, --version)
  dashboard     Start the server in the background if needed and open it (--port, --store)
  status        Show whether memoir-ui is running (--port)
  shutdown      Stop the memoir-ui running on a port (--port)
  check-update  Compare installed versions with the latest GitHub release
  help          Show this help

--port defaults to 7337. Set $BROWSER to choose the browser.
`

func main() {
	args := os.Args[1:]
	cmd := ""
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		cmd, args = args[0], args[1:]
	}
	var err error
	switch cmd {
	case "":
		serve(args)
	case "dashboard":
		err = dashboard(args)
	case "status":
		err = status(args)
	case "shutdown":
		err = shutdown(args)
	case "check-update":
		err = checkUpdate(os.Stdout)
	case "help":
		fmt.Print(usage)
	default:
		fmt.Fprintf(os.Stderr, "memoir-ui: unknown command %q\n\n%s", cmd, usage)
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "memoir-ui:", err)
		os.Exit(1)
	}
}

func newFlags(name string) (*flag.FlagSet, *int) {
	fs := flag.NewFlagSet(name, flag.ExitOnError)
	fs.Usage = func() { _, _ = fmt.Fprint(fs.Output(), usage) }
	return fs, fs.Int("port", 7337, "HTTP listen port")
}

func serve(args []string) {
	fs, port := newFlags("memoir-ui")
	storeFlag := fs.String("store", "", "Memoir store root (defaults to $MEMOIR_STORE or ~/.memoir)")
	openFlag := fs.Bool("open", false, "Open the dashboard in the default browser")
	versionFlag := fs.Bool("version", false, "Print version and exit")
	_ = fs.Parse(args)

	if *versionFlag {
		fmt.Println(version)
		return
	}

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
	srv.Version = version
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

// health is the part of GET /api/health the lifecycle subcommands read.
type health struct {
	App     string `json:"app"`
	PID     int    `json:"pid"`
	Version string `json:"version"`
	Store   string `json:"store"`
}

// probe reports the memoir-ui on port, if one answers; any other listener does not count (FR-5.6).
func probe(port int) (health, bool) {
	client := http.Client{Timeout: time.Second}
	resp, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/api/health", port))
	if err != nil {
		return health{}, false
	}
	defer func() { _ = resp.Body.Close() }()
	var h health
	if json.NewDecoder(resp.Body).Decode(&h) != nil || h.App != "memoir-ui" || h.PID <= 0 {
		return health{}, false
	}
	return h, true
}

// waitFor polls probe until it reports want or 5 s pass.
func waitFor(port int, want bool) (health, bool) {
	for deadline := time.Now().Add(5 * time.Second); ; time.Sleep(100 * time.Millisecond) {
		h, ok := probe(port)
		if ok == want || time.Now().After(deadline) {
			return h, ok
		}
	}
}

func dashboard(args []string) error {
	fs, port := newFlags("dashboard")
	storeFlag := fs.String("store", "", "Memoir store root (defaults to $MEMOIR_STORE or ~/.memoir)")
	_ = fs.Parse(args)
	addr := fmt.Sprintf("127.0.0.1:%d", *port)
	url := "http://" + addr

	h, ok := probe(*port)
	if ok {
		fmt.Printf("already running %s pid=%d\n", url, h.PID)
	} else {
		if conn, err := net.DialTimeout("tcp", addr, time.Second); err == nil {
			_ = conn.Close()
			return fmt.Errorf("port %d is in use by another program (maybe an older memoir-ui); stop it or pass --port <other>", *port)
		}
		exe, err := os.Executable()
		if err != nil {
			return err
		}
		cache, err := os.UserCacheDir()
		if err != nil {
			return err
		}
		logPath := filepath.Join(cache, "memoir-ui", "memoir-ui.log")
		if err := os.MkdirAll(filepath.Dir(logPath), 0o755); err != nil {
			return err
		}
		logFile, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
		if err != nil {
			return err
		}
		defer func() { _ = logFile.Close() }()
		serveArgs := []string{"--port", strconv.Itoa(*port)}
		if *storeFlag != "" {
			serveArgs = append(serveArgs, "--store", *storeFlag)
		}
		cmd := exec.Command(exe, serveArgs...)
		cmd.Stdout, cmd.Stderr = logFile, logFile
		cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true} // outlive this terminal
		if err := cmd.Start(); err != nil {
			return err
		}
		_ = cmd.Process.Release()
		if h, ok = waitFor(*port, true); !ok {
			return fmt.Errorf("memoir-ui did not start on port %d within 5s; see %s", *port, logPath)
		}
		fmt.Printf("started %s pid=%d log=%s\n", url, h.PID, logPath)
	}
	openBrowser(url)
	return nil
}

func status(args []string) error {
	fs, port := newFlags("status")
	_ = fs.Parse(args)
	h, ok := probe(*port)
	if !ok {
		return fmt.Errorf("not running on %d", *port)
	}
	fmt.Printf("running http://127.0.0.1:%d pid=%d version=%s store=%s\n", *port, h.PID, h.Version, h.Store)
	return nil
}

func shutdown(args []string) error {
	fs, port := newFlags("shutdown")
	_ = fs.Parse(args)
	h, ok := probe(*port)
	if !ok {
		fmt.Println("not running")
		return nil
	}
	// A signal, not an HTTP endpoint: any browser page can reach localhost (FR-5.6).
	if err := syscall.Kill(h.PID, syscall.SIGTERM); err != nil {
		return fmt.Errorf("stop pid %d: %w", h.PID, err)
	}
	if _, ok := waitFor(*port, false); ok {
		return fmt.Errorf("pid %d did not stop within 5s", h.PID)
	}
	fmt.Printf("stopped %d\n", h.PID)
	return nil
}

var calver = regexp.MustCompile(`^([0-9]{4})\.([0-9]{1,2})\.([0-9]+)$`)

// compareCalVer orders two YYYY.M.N versions numerically; ok is false when either is not one (e.g. "dev").
func compareCalVer(a, b string) (cmp int, ok bool) {
	pa, pb := calver.FindStringSubmatch(a), calver.FindStringSubmatch(b)
	if pa == nil || pb == nil {
		return 0, false
	}
	for i := 1; i <= 3; i++ {
		x, _ := strconv.Atoi(pa[i])
		y, _ := strconv.Atoi(pb[i])
		if x != y {
			if x < y {
				return -1, true
			}
			return 1, true
		}
	}
	return 0, true
}

// checkUpdate makes the one network call memoir-ui ever makes, and only on request (NFR-2.1).
func checkUpdate(out io.Writer) error {
	client := http.Client{Timeout: 10 * time.Second}
	req, err := http.NewRequest(http.MethodGet, latestURL, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("check latest release: %w", err)
	}
	defer func() { _ = resp.Body.Close() }()
	var rel struct {
		Tag string `json:"tag_name"`
	}
	if resp.StatusCode != http.StatusOK || json.NewDecoder(resp.Body).Decode(&rel) != nil || calver.FindString(rel.Tag) == "" {
		return fmt.Errorf("check latest release: unexpected response (HTTP %d)", resp.StatusCode)
	}

	installed := [][2]string{{"memoir-ui", version}}
	home, _ := os.UserHomeDir()
	for _, skill := range []string{"memoir", "memoir-wiki"} {
		data, _ := os.ReadFile(filepath.Join(home, ".agents", "skills", skill, "VERSION"))
		installed = append(installed, [2]string{skill, strings.TrimSpace(string(data))})
	}
	_, _ = fmt.Fprintf(out, "latest       %s\n", rel.Tag)
	stale := false
	for _, c := range installed {
		state := "current"
		switch cmp, ok := compareCalVer(c[1], rel.Tag); {
		case !ok:
			state, c[1] = "unknown", displayVersion(c[1])
		case cmp < 0:
			state = "behind"
		}
		stale = stale || state != "current"
		_, _ = fmt.Fprintf(out, "%-12s %s (%s)\n", c[0], c[1], state)
	}
	if stale {
		_, _ = fmt.Fprintf(out, "\nUpdate with:\n  %s\n", installCmd)
	}
	return nil
}

// displayVersion names a version that is not YYYY.M.N for display.
func displayVersion(v string) string {
	if v == "" {
		return "not found"
	}
	return v
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
	if browser := os.Getenv("BROWSER"); browser != "" {
		cmd = exec.Command(browser, url)
	}
	if err := cmd.Start(); err == nil {
		go func() { _ = cmd.Wait() }()
	}
}
