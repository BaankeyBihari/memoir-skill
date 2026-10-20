"""Self-check for skills/memoir/scripts/memoir.py. Run: python3 test_memoir.py"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SCRIPT = Path(__file__).parent / "skills" / "memoir" / "scripts" / "memoir.py"

sys.path.insert(0, str(SCRIPT.parent))
import memoir # noqa: E402 (direct-function tests: add_superseded_by, ensure_gitignore_hint)


def run(store: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MEMOIR_STORE": str(store)}
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "store"
    active = store / "active"

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
    assert home_store == str(Path.home() / "memoir-test-x"), home_store

always_on = (SCRIPT.parents[1] / "references" / "always-on.md").read_text()
block = always_on[always_on.index("```markdown"):always_on.rindex("```") + 3]
assert block in (Path(__file__).parent / "README.md").read_text(), "README always-on block drifted"
assert "uv run" not in (SCRIPT.parents[1] / "SKILL.md").read_text(), "SKILL.md must invoke the CLI with python3"

# --- B5: the Superseded-By back-link is written into the ARCHIVED copy, right after Supersedes: ---
with tempfile.TemporaryDirectory() as tmp:
    store = Path(tmp) / "store"
    active = store / "active"
    run(store, "init")
    (active / "decision-old.md").write_text("Date: 2026-10-20\nSupersedes: none\nBody: 123\n")
    (active / "decision-new.md").write_text("Date: 2026-10-20\nSupersedes: decision-old.md\nBody: 456\n")
    out = run(store, "archive", "--superseded")
    assert out.returncode == 0
    assert "Archived 1 files" in out.stdout, out
    archived = store / "archive" / f"{datetime.now():%Y%m%d}-decision-old.md"
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
    active = store / "active"
    run(store, "init")
    (active / "feedback-tone.md").write_text("note\n")
    out = run(store, "archive", "feedback-tone.md")
    assert out.returncode == 0
    assert "Archived 1 files" in out.stdout, out
    assert not (active / "feedback-tone.md").exists()
    (active / "feedback-tone.md").write_text("note\n")
    assert run(store, "archive", "feedback-tone.md").returncode == 1  # same-day copy archived: no overwrite
    assert (active / "feedback-tone.md").exists()

# --- B4: ensure_gitignore_hint appends once, is idempotent, preserves existing content, is scoped ---
with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp) / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    prev = Path.cwd()
    os.chdir(repo)
    try:
        (repo / ".gitignore").write_text("node_modules") # pre-existing, no trailing newline
        base = memoir.get_git_root()/ ".agents/memoir"
        memoir.ensure_gitignore_hint(base)
        gi = (repo / ".gitignore").read_text()
        assert gi == "node_modules\n.agents/memoir/\n", repr(gi)
        memoir.ensure_gitignore_hint(base) # idempotent re-run doesn't add duplicates
        assert (repo / ".gitignore").read_text() == gi, "idempotent re-run changed content"
        memoir.ensure_gitignore_hint(Path(tmp) / "elsewhere" / "memoir") # override store: skipped
        assert (repo / ".gitignore").read_text() == gi, "override store: skipped re-added line"
        os.chdir(tmp)
        memoir.ensure_gitignore_hint(Path(tmp)/".agents"/"memoir")
        assert not (Path(tmp)/".gitignore").exists(), "gitignore not created"
    finally:
        os.chdir(prev)

# --- FR-1.3 / FR-1.4: store location, access check, protected .gitignore ---
def run_in(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("MEMOIR_")}
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, env=env, capture_output=True, text=True)

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp).resolve() / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert run_in(repo, "path").stdout.strip() == str(repo / ".agents" / "memoir")  # neither exists
    (repo / ".claude" / "memoir").mkdir(parents=True)
    out = run_in(repo, "path")
    assert out.stdout.strip() == str(repo / ".claude" / "memoir"), out  # only .claude exists
    (repo / ".gitignore").write_text(".claude/settings.local.json\n")
    assert run_in(repo, "resume").returncode == 0
    assert (repo / ".gitignore").read_text() == ".claude/settings.local.json\n.claude/memoir/\n"
    (repo / ".agents" / "memoir").mkdir(parents=True)
    out = run_in(repo, "path")
    assert out.stdout.strip() == str(repo / ".agents" / "memoir") and "both" in out.stderr, out  # both: .agents wins

    # protected .gitignore: command still succeeds, user gets the line to add
    (repo / ".gitignore").write_text("node_modules\n")
    (repo / ".gitignore").chmod(0o444)
    out = run_in(repo, "resume")
    (repo / ".gitignore").chmod(0o644)
    if os.geteuid() != 0:
        assert out.returncode == 0 and "Add this line manually: .agents/memoir/" in out.stderr, out
        assert (repo / ".gitignore").read_text() == "node_modules\n"

    # unwritable store: exit 3, message names the path, nothing created elsewhere
    ro = Path(tmp) / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    if os.geteuid() != 0:
        out = run(ro / "store", "resume")
        assert out.returncode == 3 and f"No write access to {ro / 'store'}" in out.stderr, out
        assert not (ro / "store").exists()
    ro.chmod(0o755)

print("ok")
