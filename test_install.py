import os
from pathlib import Path
import subprocess


def test_repeat_install(tmp_path):
    script = Path(__file__).with_name("install.sh")
    home = tmp_path / "home"
    env = {**os.environ, "HOME": str(home)}
    parents = [home / p for p in (".claude/skills", ".codex/skills", ".pi/agent/skills",
                                  ".gemini/antigravity/skills")]
    for parent in parents:
        parent.mkdir(parents=True)
    store = tmp_path / "custom store"
    for _ in range(2):
        subprocess.run([script, "--skills-only", "--store", store], env=env, check=True)
    for parent in parents:
        for name in ("memoir", "memoir-wiki"):
            assert (parent / name).resolve() == home / ".agents/skills" / name
    assert (parents[0] / "memoir/scripts/memoir.py").is_file()
    assert (store / "standalone").is_dir()
    assert not (home / ".local/bin").exists()


def test_ui_only(tmp_path):
    curl = tmp_path / "curl"
    curl.write_text('#!/bin/sh\nprintf "%s" binary > "$4"\n')
    curl.chmod(0o755)
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    subprocess.run([Path(__file__).with_name("install.sh"), "--ui-only"], env=env, check=True)
    assert (tmp_path / ".local/bin/memoir-ui").read_text() == "binary"
    assert not (tmp_path / ".agents").exists()
