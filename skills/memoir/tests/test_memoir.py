import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/memoir.py"


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path.resolve() / "store"
    monkeypatch.setenv("MEMOIR_STORE", str(root))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    return root


def cli(cwd, *args):
    return subprocess.check_output([sys.executable, SCRIPT, *args], cwd=cwd, text=True).strip()


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=test@example.org", "-c", "user.name=Test", *args],
                   cwd=cwd, check=True, capture_output=True)


def sha8(path):
    return hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:8]


def test_clones_and_worktrees(tmp_path, store):
    origin = tmp_path / "origin"
    git(tmp_path, "init", str(origin))
    git(origin, "commit", "--allow-empty", "-m", "seed")
    for parent, remote in [("work", "git@EXAMPLE.org:Team/Repo.git"),
                           ("scratch", "https://user:secret@example.org/team/repo.git")]:
        dest = tmp_path / parent / "My Clone"
        git(tmp_path, "clone", str(origin), str(dest))
        git(dest, "remote", "set-url", "origin", remote)
        clone_id = "my-clone--" + sha8(dest / ".git")
        clone = store / "repos/example.org__team__repo/clones" / clone_id
        assert cli(dest, "path") == str(clone / "paths/_main")
        assert not clone.exists()
        cli(dest, "init")
        metadata = json.loads((clone / "clone.json").read_text())
        assert metadata["root"] == str(dest.resolve())
        assert datetime.fromisoformat(metadata["last_seen"]).tzinfo
        for checkout, key in [(dest / "Worktrees/wt-one", "Worktrees__wt-one"),
                              (dest.parent / "wt-two", "wt-two")]:
            git(dest, "worktree", "add", "--detach", str(checkout))
            sub = checkout / "nested"
            sub.mkdir()
            assert cli(sub, "prompt").splitlines()[-1] == str(clone / "paths" / key / "active")
    assert len(list((store / "repos/example.org__team__repo/clones").iterdir())) == 2


def test_local_fallback(tmp_path, store):
    git(tmp_path, "init")
    key = tmp_path.name.replace("_", "-") + "--" + sha8(tmp_path / ".git")
    assert Path(cli(tmp_path, "path")) == store / "repos" / ("local__" + key) / "clones" / key / "paths/_main"


def test_pin_resolution(tmp_path, store):
    root = tmp_path / "My Notes"
    nested = root / "drafts"
    child = nested / "2026"
    child.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(root)
    sibling = tmp_path / "My Notes Archive"
    sibling.mkdir()
    workspace = store / "pinned" / ("my-notes--" + sha8(root))
    standalone = store / "standalone" / ("my-notes-archive--" + sha8(sibling))
    assert cli(sibling, "path") == str(standalone)
    for path in (root, alias):
        assert str(workspace) in cli(tmp_path, "pin", path)
    assert json.loads((store / "pinned.json").read_text()) == [str(root.resolve())]
    assert cli(root, "path") == str(workspace / "paths/_root")
    cli(child, "init")
    assert (workspace / "paths/drafts__2026/archive").is_dir()
    assert json.loads((workspace / "workspace.json").read_text())["root"] == str(root.resolve())
    cli(nested, "pin")
    inner = store / "pinned" / ("drafts--" + sha8(nested))
    assert cli(child, "path") == str(inner / "paths/2026")
    cli(nested, "unpin")
    cli(nested, "unpin")
    assert cli(child, "path") == str(workspace / "paths/drafts__2026")
    assert cli(sibling, "path") == str(standalone)
    git(child, "init")
    assert Path(cli(child, "path")).is_relative_to(store / "repos")
    cli(root, "unpin")
    assert Path(cli(root, "path")) == store / "standalone" / workspace.name
    assert workspace.is_dir()
