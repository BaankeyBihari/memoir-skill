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
    return subprocess.run([sys.executable, str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)


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

print("ok")
