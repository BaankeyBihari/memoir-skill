"""Self-check for skills/memoir/scripts/memoir.py. Run: python3 test_memoir.py"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).parent / "skills" / "memoir" / "scripts" / "memoir.py"

def run(store: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MEMOIR_STORE": str(store)}
    # Run beside the store, not in this repo, whose own v1 `.agents/memoir` would be migrated.
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=store.expanduser().parent, env=env,
                          capture_output=True, text=True, check=False)


with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "store"
    base = Path(run(store, "path").stdout.strip())
    active = base / "active"

    out = run(store, "resume")
    assert out.returncode == 0 and str(active) in out.stdout and "Start fresh" in out.stdout, out

    run(store, "init")
    (active / "state-current.md").write_text("# Session State\n")
    (active / "decision-old-auth.md").write_text("Supersedes: none\n")
    (active / "decision-new-auth.md").write_text("Supersedes: decision-old-auth.md\n")
    (active / "reference-api.md").write_text("Target: x\n")

    lines = run(store, "resume").stdout.splitlines()
    assert lines[2] == str(active), lines
    assert lines[5].endswith("state-current.md"), lines

    out = run(store, "archive", "--superseded")
    assert out.returncode == 0 and "Archived 1 files" in out.stdout, out
    assert not (active / "decision-old-auth.md").exists()
    assert run(store, "archive", "--superseded").returncode == 0  # already archived: no-op

    for bad in ("state-current.md", "../x.md", "/etc/hosts", "Bad_Name.md", "missing-x.md"):
        assert run(store, "archive", bad).returncode == 1, bad

    (active / "decision-old-auth.md").write_text("second\n")
    assert run(store, "archive", "decision-old-auth.md").returncode == 1  # no overwrite
    assert (active / "decision-old-auth.md").exists()

    assert run(store, "archive").returncode == 2  # needs files or --superseded

    home_store = run(Path("~/memoir-test-x"), "path").stdout.strip()
    assert Path(home_store).is_relative_to(Path.home() / "memoir-test-x"), home_store

always_on = (SCRIPT.parents[1] / "references" / "always-on.md").read_text()
block = always_on[always_on.index("```markdown"):always_on.rindex("```") + 3]
assert block in (Path(__file__).parent / "README.md").read_text(), "README always-on block drifted"
assert "uv run" not in (SCRIPT.parents[1] / "SKILL.md").read_text(), "SKILL.md must invoke the CLI with python3"

# --- B5: the Superseded-By back-link is written into the ARCHIVED copy, right after Supersedes: ---
with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "store"
    base = Path(run(store, "path").stdout.strip())
    active = base / "active"
    run(store, "init")
    (active / "decision-old.md").write_text("Date: 2026-10-20\nSupersedes: none\nBody: 123\n")
    (active / "decision-new.md").write_text("Date: 2026-10-20\nSupersedes: decision-old.md\nBody: 456\n")
    out = run(store, "archive", "--superseded")
    assert out.returncode == 0
    assert "Archived 1 files" in out.stdout, out
    archived = base / "archive" / f"{datetime.now().astimezone():%Y%m%d}-decision-old.md"
    assert archived.exists(), "Archived file not found"
    archived_lines = archived.read_text().splitlines()
    assert "Supersedes: none" in archived_lines
    assert "Superseded-By: decision-new.md" in archived_lines
    i = archived_lines.index("Supersedes: none")
    j = archived_lines.index("Superseded-By: decision-new.md")
    assert j == i + 1

# --- B1: feedback-*.md fragments are archivable (parity with decision/log/reference) ---
with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "store"
    base = Path(run(store, "path").stdout.strip())
    active = base / "active"
    run(store, "init")
    (active / "feedback-tone.md").write_text("note\n")
    out = run(store, "archive", "feedback-tone.md")
    assert out.returncode == 0
    assert "Archived 1 files" in out.stdout, out
    assert not (active / "feedback-tone.md").exists()
    (active / "feedback-tone.md").write_text("note\n")
    assert run(store, "archive", "feedback-tone.md").returncode == 1  # same-day copy archived: no overwrite
    assert (active / "feedback-tone.md").exists()

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp).resolve() / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = {**os.environ, "HOME": tmp, "MEMOIR_STORE": ""}
    out = subprocess.run([sys.executable, SCRIPT, "prompt"], cwd=repo, env=env,
                         capture_output=True, text=True, check=True)
    assert Path(out.stdout.splitlines()[-1]).is_relative_to(Path(tmp).resolve() / ".memoir")
    assert not (repo / ".gitignore").exists()
    assert not (repo / ".agents").exists()

    # unwritable store: exit 3, message names the path, nothing created elsewhere
    ro = Path(tmp).resolve() / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    if os.geteuid() != 0:
        out = run(ro / "store", "resume")
        assert out.returncode == 3 and f"No write access to {ro / 'store'}" in out.stderr, out
        assert not (ro / "store").exists()
    ro.chmod(0o755)

# --- FR-1.7: v1 stores are copied into an empty v2 scope, never moved or merged ---
with tempfile.TemporaryDirectory() as raw:
    tmp = Path(raw).resolve()
    env = {**os.environ, "HOME": str(tmp), "MEMOIR_STORE": "", "XDG_CONFIG_HOME": str(tmp / "xdg")}

    def cli(cwd: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd, env=env, capture_output=True, text=True, check=False)

    repo = tmp / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    legacy = repo / ".agents" / "memoir"
    (legacy / "active").mkdir(parents=True)
    (legacy / "archive").mkdir()
    (legacy / "active" / "state-current.md").write_text("# Session State\n")
    (legacy / "archive" / "20260101-log-old.md").write_text("old\n")
    base = Path(cli(repo, "path").stdout.strip())
    assert not (base / "active").exists()  # path is read-only: no migration
    out = cli(repo, "resume")
    assert out.returncode == 0 and f"Migrated 2 files from {legacy} to {base}" in out.stderr, out
    assert (base / "active" / "state-current.md").read_text() == "# Session State\n"
    assert (base / "archive" / "20260101-log-old.md").exists()
    assert (legacy / "active" / "state-current.md").exists()  # copied, not moved
    assert str(base / "active" / "state-current.md") in out.stdout

    (base / "active" / "state-current.md").write_text("# Session State\nUpdated later\n")  # v2 evolves after the copy
    (legacy / "active" / "decision-done.md").write_text("done\n")
    (base / "archive" / "20260102-decision-done.md").write_text("done\n")  # copied, then archived in v2
    out = cli(repo, "resume")
    assert f"is already migrated to {base}; delete {legacy}" in out.stderr and "not migrated" not in out.stderr, out

    (legacy / "active" / "decision-late.md").write_text("late\n")
    out = cli(repo, "resume")
    assert "Migrated" not in out.stderr and "not migrated" in out.stderr, out  # no merge into a used scope
    assert not (base / "active" / "decision-late.md").exists()

    plain = tmp / "plain"  # non-Git v1 `.claude/memoir` at the cwd
    (plain / ".claude" / "memoir" / "active").mkdir(parents=True)
    (plain / ".claude" / "memoir" / "active" / "log-x.md").write_text("x\n")
    out = cli(plain, "init")
    assert out.returncode == 0 and "Migrated 1 files" in out.stderr, out
    assert (Path(cli(plain, "path").stdout.strip()) / "active" / "log-x.md").exists()

    # --- FR-1.4/FR-2.6: a pin groups standalone scopes; fragments never move ---
    ws = tmp / "ws"
    (ws / "sub" / "deep").mkdir(parents=True)
    scope = {}
    for folder in (ws, ws / "sub"):
        scope[folder] = Path(cli(folder, "path").stdout.strip())
        assert "/standalone/" in str(scope[folder]), scope[folder]
        cli(folder, "init")
        (scope[folder] / "active" / "state-current.md").write_text(f"# {folder.name}\n")
        (scope[folder] / "active" / f"log-{folder.name}.md").write_text("x\n")
    (scope[ws] / "active" / "decision-old.md").write_text("Supersedes: none\n")
    out = cli(ws, "pin")
    assert out.returncode == 0 and "/pinned/" in out.stdout, out
    group = Path(out.stdout.split(" (")[0])
    assert Path(cli(ws / "sub", "path").stdout.strip()) == scope[ws / "sub"]  # still standalone

    listed = cli(ws / "sub", "resume").stdout.splitlines()
    files = [line.split(". ", 1)[1] for line in listed if line[:1].isdigit()]
    assert files[0] == str(scope[ws / "sub"] / "active" / "state-current.md"), files
    assert str(scope[ws] / "active" / "log-ws.md") in files and str(scope[ws] / "active" / "decision-old.md") in files
    assert str(scope[ws] / "active" / "state-current.md") not in files  # state stays per folder

    out = cli(ws / "sub", "scope").stdout.splitlines()
    assert out[0] == str(group) and sorted(out[1:]) == sorted(map(str, scope.values())), out

    # A decision in sub supersedes one in ws: it is archived inside ws's own scope.
    (scope[ws / "sub"] / "active" / "decision-new.md").write_text("Supersedes: decision-old.md\n")
    out = cli(ws / "sub", "archive", "--superseded")
    assert out.returncode == 0 and "Archived 1 files" in out.stdout, out
    assert not (scope[ws] / "active" / "decision-old.md").exists()
    assert any((scope[ws] / "archive").glob("*-decision-old.md"))
    # The superseding decision's own scope wins when both hold the name.
    for folder in (ws, ws / "sub"):
        (scope[folder] / "active" / "decision-dup.md").write_text("Supersedes: none\n")
    (scope[ws / "sub"] / "active" / "decision-newer.md").write_text("Supersedes: decision-dup.md\n")
    assert cli(ws, "archive", "--superseded").returncode == 0
    assert (scope[ws] / "active" / "decision-dup.md").exists() and not (scope[ws / "sub"] / "active" / "decision-dup.md").exists()

    # A nested pin takes sub (and its own subfolders) out of the ws group.
    deep = Path(cli(ws / "sub" / "deep", "path").stdout.strip())
    cli(ws / "sub" / "deep", "init")
    assert cli(ws / "sub", "pin").returncode == 0
    assert str(scope[ws / "sub"] / "active" / "log-sub.md") not in cli(ws, "resume").stdout
    assert str(scope[ws / "sub"] / "active" / "log-sub.md") in cli(ws / "sub" / "deep", "resume").stdout
    assert str(deep) in cli(ws / "sub", "scope").stdout
    assert cli(ws / "sub", "unpin").returncode == 0

    # Unpin: each folder resumes only its own notes again, and nothing moved.
    assert cli(ws, "unpin").returncode == 0
    out = cli(ws / "sub", "resume").stdout
    assert str(scope[ws] / "active" / "log-ws.md") not in out and str(scope[ws / "sub"] / "active" / "log-sub.md") in out
    assert cli(ws / "sub", "scope").stdout == ""
    assert (group / "workspace.json").exists()  # group dir (and its wiki) stays

    # Legacy pre-group fragments inside the pin are copied into the folder's standalone scope.
    legacy_ws = tmp / "legacy-ws"
    legacy_ws.mkdir()
    pinned_dir = Path(cli(legacy_ws, "pin").stdout.split(" (")[0])
    (pinned_dir / "paths" / "_root" / "active").mkdir(parents=True)
    (pinned_dir / "paths" / "_root" / "active" / "log-pre-group.md").write_text("old\n")
    out = cli(legacy_ws, "resume")
    own = Path(cli(legacy_ws, "path").stdout.strip())
    assert f"Migrated 1 files from {pinned_dir / 'paths' / '_root'} to {own}" in out.stderr, out
    assert (own / "active" / "log-pre-group.md").exists() and (pinned_dir / "paths" / "_root" / "active" / "log-pre-group.md").exists()

    # gc reports a standalone scope whose folder is gone.
    gone = tmp / "gone"
    gone.mkdir()
    cli(gone, "init")
    gone_scope = Path(cli(gone, "path").stdout.strip())
    gone.rmdir()
    assert f"Orphan: {gone_scope} (missing directory {gone})" in cli(tmp, "gc").stdout

    # --- FR-1.8: MEMOIR_STORE still pointing at a v1 base directory is rejected ---
    out = run(legacy, "resume")
    assert out.returncode == 1 and "is a v1 store" in out.stderr, out
    assert not (legacy / "repos").exists() and not (legacy / "standalone").exists()

# --- FR-2.4/FR-2.9: sibling worktrees are listed, loaded on demand, and adopted ---
with tempfile.TemporaryDirectory() as raw:
    tmp = Path(raw).resolve()
    env = {**os.environ, "HOME": str(tmp), "MEMOIR_STORE": "", "XDG_CONFIG_HOME": str(tmp / "xdg")}

    def cli(cwd: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, SCRIPT, *args], cwd=cwd, env=env, capture_output=True, text=True, check=False)

    def git(*args: str) -> None:
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)

    main, feat, gone = tmp / "repo", tmp / "repo" / "wt" / "feat", tmp / "gone"
    git("init", "-q", str(main))
    git("-C", str(main), "commit", "-q", "--allow-empty", "-m", "init")
    git("-C", str(main), "worktree", "add", "-q", str(feat))
    git("-C", str(main), "worktree", "add", "-q", str(gone))
    base = {wt: Path(cli(wt, "path").stdout.strip()) for wt in (main, feat, gone)}
    assert base[feat].name == "wt__feat" and base[gone].name == "gone", base
    for wt in base:
        assert cli(wt, "init").returncode == 0
    assert '"root": "%s"' % feat in (base[feat] / "worktree.json").read_text()

    a = {wt: base[wt] / "active" for wt in base}
    (a[main] / "state-current.md").write_text("# main\n")
    (a[main] / "decision-a.md").write_text("Supersedes: none\nmain\n")
    (a[feat] / "state-current.md").write_text("# feat\n")
    (a[feat] / "decision-a.md").write_text("Supersedes: none\nfeat\n")
    (a[feat] / "decision-b.md").write_text("Date: 2026-11-01\nSupersedes: decision-a.md\n")
    (a[feat] / "log-x.md").write_text("x\n")
    (a[feat] / "feedback-y.md").write_text("y\n")
    os.utime(a[feat] / "log-x.md", (1767225600, 1767225600))  # newest: 2026-01-01 local
    for p in (a[feat] / "decision-a.md", a[feat] / "decision-b.md", a[feat] / "feedback-y.md"):
        os.utime(p, (1735689600, 1735689600))
    (a[gone] / "reference-r.md").write_text("Target: x\n")
    git("-C", str(main), "worktree", "remove", str(gone))
    empty = base[main].parent / "empty"
    (empty / "active").mkdir(parents=True)
    (empty / "active" / "state-current.md").write_text("# state only\n")
    legacy = base[main].parent / "legacy"
    (legacy / "active").mkdir(parents=True)
    (legacy / "active" / "log-old.md").write_text("old\n")

    out = cli(main, "resume").stdout
    head = "Sibling worktrees with fragments (not loaded; add with resume --with <key>):"
    newest = datetime.fromtimestamp(1767225600, timezone.utc).astimezone().strftime("%Y-%m-%d")
    assert out.split(head)[1].strip().splitlines() == [
        "- gone: 0 decisions, 0 logs, 1 references, 0 feedback; newest %s; worktree missing" % datetime.fromtimestamp((a[gone] / "reference-r.md").stat().st_mtime, timezone.utc).astimezone().strftime("%Y-%m-%d"),
        "- legacy: 0 decisions, 1 logs, 0 references, 0 feedback; newest %s; worktree unknown" % datetime.fromtimestamp((legacy / "active" / "log-old.md").stat().st_mtime, timezone.utc).astimezone().strftime("%Y-%m-%d"),
        f"- wt__feat: 2 decisions, 1 logs, 0 references, 1 feedback; newest {newest}; worktree present",
    ], out  # current scope and state-only "empty" excluded
    assert str(a[feat]) not in out.split(head)[0]  # listed, not loaded
    assert "- _main:" in cli(feat, "resume").stdout

    out = cli(main, "resume", "--with", "wt__feat", "--with", "wt__feat").stdout
    files = [line.split(". ", 1)[1] for line in out.splitlines() if line[:1].isdigit()]
    assert files == [str(a[main] / n) for n in ("state-current.md", "decision-a.md")] + [
        str(a[feat] / n) for n in ("decision-a.md", "decision-b.md", "feedback-y.md", "log-x.md")], files
    for bad in ("_main", "nope", "..", "wt__feat/active", ""):
        out = cli(main, "resume", "--with", bad)
        assert out.returncode == 1 and f"No sibling path {bad} in " in out.stderr, (bad, out)
    assert cli(tmp, "adopt", "x").returncode == 1  # outside Git

    out = cli(main, "adopt", "wt__feat")
    assert out.returncode == 0, out
    assert out.stdout.splitlines() == [
        "[Memoir] Adopted 4 files from wt__feat.",
        f"{a[main] / 'decision-a-2.md'} (renamed from decision-a.md)",
        f"{a[main] / 'decision-b.md'}",
        f"{a[main] / 'feedback-y.md'}",
        f"{a[main] / 'log-x.md'}",
    ], out.stdout
    assert (a[main] / "decision-a.md").read_text() == "Supersedes: none\nmain\n"
    assert (a[main] / "decision-a-2.md").read_text() == "Supersedes: none\nfeat\n"
    assert (a[main] / "decision-b.md").read_text() == "Date: 2026-11-01\nSupersedes: decision-a-2.md\n"
    assert sorted(p.name for p in a[feat].iterdir()) == ["state-current.md"]
    assert (a[main] / "state-current.md").read_text() == "# main\n"
    assert "Adopted 0 files from wt__feat." in cli(main, "adopt", "wt__feat").stdout

    out = cli(main, "archive", "--superseded")
    assert out.returncode == 0 and "Archived 1 files" in out.stdout, out
    assert (a[main] / "decision-a.md").exists() and not (a[main] / "decision-a-2.md").exists()

print("ok")
