"""Self-check for skills/memoir/scripts/memoir.py. Run: python3 test_memoir.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).parent / "skills" / "memoir" / "scripts" / "memoir.py"


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

print("ok")
