package main

import (
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"
)

const (
	testCalVer   = "2026.11.3"
	cmdDashboard = "dashboard"
	cmdStatus    = "status"
	cmdShutdown  = "shutdown"
)

func TestResolveStoreRoot(t *testing.T) {
	base := t.TempDir()
	envStore := filepath.Join(base, "env-memoir-store")
	explicitStore := filepath.Join(base, "explicit-store")
	t.Setenv("MEMOIR_STORE", envStore)

	got, err := resolveStoreRoot("")
	if err != nil {
		t.Fatalf("resolveStoreRoot env: %v", err)
	}
	want, _ := filepath.Abs(envStore)
	if got != want {
		t.Fatalf("got %q, want %q", got, want)
	}

	gotExplicit, err := resolveStoreRoot(explicitStore)
	if err != nil {
		t.Fatalf("resolveStoreRoot explicit: %v", err)
	}
	wantExplicit, _ := filepath.Abs(explicitStore)
	if gotExplicit != wantExplicit {
		t.Fatalf("got %q, want %q", gotExplicit, wantExplicit)
	}
}

func TestDefaultVersion(t *testing.T) {
	if version == "" {
		t.Fatal("expected non-empty default version")
	}
	if version != "dev" {
		t.Fatalf("expected default version 'dev', got %q", version)
	}
}

func TestCompareCalVer(t *testing.T) {
	for _, tc := range []struct {
		a, b string
		cmp  int
		ok   bool
	}{
		{"2026.11.10", testCalVer, 1, true},
		{"2026.12.9", "2027.1.1", -1, true},
		{testCalVer, testCalVer, 0, true},
		{"dev", testCalVer, 0, false},
		{"", testCalVer, 0, false},
	} {
		if cmp, ok := compareCalVer(tc.a, tc.b); cmp != tc.cmp || ok != tc.ok {
			t.Errorf("compareCalVer(%q, %q) = %d, %v; want %d, %v", tc.a, tc.b, cmp, ok, tc.cmp, tc.ok)
		}
	}
}

func TestCheckUpdate(t *testing.T) {
	api := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`{"tag_name":"` + testCalVer + `"}`))
	}))
	defer api.Close()
	old := latestURL
	latestURL = api.URL
	defer func() { latestURL = old }()

	home := t.TempDir()
	t.Setenv("HOME", home)
	for skill, v := range map[string]string{"memoir": testCalVer, "memoir-wiki": "2026.11.2"} {
		dir := filepath.Join(home, ".agents", "skills", skill)
		if err := os.MkdirAll(dir, 0o750); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "VERSION"), []byte(v+"\n"), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	var out strings.Builder
	if err := checkUpdate(&out); err != nil {
		t.Fatalf("checkUpdate: %v", err)
	}
	for _, want := range []string{"latest       " + testCalVer, "memoir-ui    dev (unknown)", "memoir       " + testCalVer + " (current)", "memoir-wiki  2026.11.2 (behind)", installCmd} {
		if !strings.Contains(out.String(), want) {
			t.Errorf("output missing %q:\n%s", want, out.String())
		}
	}
}

func assertForeignPortRejected(t *testing.T, port string, run func(...string) (string, error)) {
	t.Helper()
	other, err := net.Listen("tcp", "127.0.0.1:"+port)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = other.Close() }()
	srv := &http.Server{Handler: http.NotFoundHandler(), ReadHeaderTimeout: time.Second}
	go func() { _ = srv.Serve(other) }()

	out, err := run(cmdDashboard)
	if err == nil || !strings.Contains(out, "port "+port+" is in use by another program") || !strings.Contains(out, "stop it or pass --port") {
		t.Fatalf("dashboard on a foreign port should fail with a hint: %v\n%s", err, out)
	}
}

func assertLifecycleTransitions(t *testing.T, port, store string, run func(...string) (string, error)) {
	t.Helper()
	out, err := run(cmdDashboard)
	if err != nil || !strings.Contains(out, "started http://127.0.0.1:"+port) {
		t.Fatalf("dashboard: %v\n%s", err, out)
	}
	pid := regexp.MustCompile(`pid=(\d+)`).FindStringSubmatch(out)[1]

	if out, err = run(cmdStatus); err != nil || !strings.Contains(out, "running") || !strings.Contains(out, "pid="+pid) || !strings.Contains(out, "store="+store) {
		t.Fatalf("status while running: %v\n%s", err, out)
	}
	if out, err = run(cmdDashboard); err != nil || !strings.Contains(out, "already running") || !strings.Contains(out, "pid="+pid) {
		t.Fatalf("second dashboard should reuse pid %s: %v\n%s", pid, err, out)
	}
	if out, err = run(cmdShutdown); err != nil || !strings.Contains(out, "stopped "+pid) {
		t.Fatalf("shutdown: %v\n%s", err, out)
	}
	if out, err = run(cmdStatus); err == nil || !strings.Contains(out, "not running on "+port) {
		t.Fatalf("status after shutdown should fail: %v\n%s", err, out)
	}
	if out, err = run(cmdShutdown); err != nil || !strings.Contains(out, "not running") {
		t.Fatalf("shutdown when stopped: %v\n%s", err, out)
	}
}

// TestLifecycle drives the real binary: dashboard starts or reuses a server, status reports it, shutdown stops it.
func TestLifecycle(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("background start and SIGTERM are unix-only")
	}
	tmp := t.TempDir()
	bin := filepath.Join(tmp, appName)
	if out, err := exec.Command("go", "build", "-o", bin, ".").CombinedOutput(); err != nil {
		t.Fatalf("go build: %v\n%s", err, out)
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := strconv.Itoa(ln.Addr().(*net.TCPAddr).Port)
	_ = ln.Close()
	store := filepath.Join(tmp, "store")
	if err := os.Mkdir(store, 0o750); err != nil {
		t.Fatal(err)
	}
	env := append(os.Environ(), "HOME="+tmp, "XDG_CACHE_HOME="+filepath.Join(tmp, "cache"), "BROWSER=true", "MEMOIR_STORE="+store)
	run := func(args ...string) (string, error) {
		cmd := exec.Command(bin, append(args, "--port", port)...)
		cmd.Env = env
		out, err := cmd.CombinedOutput()
		return string(out), err
	}
	t.Cleanup(func() { _, _ = run(cmdShutdown) })

	assertLifecycleTransitions(t, port, store, run)
	assertForeignPortRejected(t, port, run)
}
