"""Self-check for skills/memoir/scripts/memoir.py. Run: python3 test_memoir.py"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime
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

    # --- FR-2.6: pinning carries each folder's standalone notes into the workspace, copy-only ---
    ws = tmp / "ws"
    (ws / "sub").mkdir(parents=True)
    old = {}
    for folder in (ws, ws / "sub"):
        old[folder] = Path(cli(folder, "path").stdout.strip())
        assert "/standalone/" in str(old[folder]), old[folder]
        cli(folder, "init")
        (old[folder] / "active" / "log-before-pin.md").write_text(f"{folder.name}\n")
    out = cli(ws, "pin")
    assert out.returncode == 0 and "/pinned/" in out.stdout, out
    for folder, key in ((ws, "_root"), (ws / "sub", "sub")):
        base = Path(cli(folder, "path").stdout.strip())
        assert base.name == key and "/pinned/" in str(base), base
        out = cli(folder, "resume")
        assert f"Migrated 1 files from {old[folder]} to {base}" in out.stderr, out
        assert (base / "active" / "log-before-pin.md").read_text() == f"{folder.name}\n"
        assert (old[folder] / "active" / "log-before-pin.md").exists()  # copied, not moved
        assert "already migrated" in cli(folder, "resume").stderr
    assert cli(ws, "unpin").returncode == 0
    assert Path(cli(ws, "path").stdout.strip()) == old[ws]  # back to standalone
    assert (base.parent / "_root" / "active" / "log-before-pin.md").exists()  # unpin keeps data

    # --- FR-1.8: MEMOIR_STORE still pointing at a v1 base directory is rejected ---
    out = run(legacy, "resume")
    assert out.returncode == 1 and "is a v1 store" in out.stderr, out
    assert not (legacy / "repos").exists() and not (legacy / "standalone").exists()

print("ok")
