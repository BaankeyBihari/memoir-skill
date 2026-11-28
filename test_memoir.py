"""Self-check for skills/memoir/scripts/memoir.py. Run: python3 test_memoir.py."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).parent / "skills" / "memoir" / "scripts" / "memoir.py"
GIT = shutil.which("git") or "/usr/bin/git"

UTF8 = "utf-8"
ENV_MEMOIR_STORE = "MEMOIR_STORE"
STATE_FILE = "state-current.md"
FILE_AGENTS = "AGENTS.md"
FILE_CLAUDE = "CLAUDE.md"
SKILL_MEMOIR = "memoir"
SKILL_WIKI = "memoir-wiki"
CMD_ARCHIVE = "archive"
CMD_PROJECT_INIT = "project-init"
CMD_RESUME = "resume"
FLAG_SUPERSEDED = "--superseded"
FLAG_WITH = "--with"
MSG_ARCHIVED_ONE = "Archived 1 files"
HDR_SESSION_STATE = "# Session State\n"
HDR_SUPERSEDES_NONE = "Supersedes: none\n"
FMT_DATE = "%Y-%m-%d"
GUARD_BEGIN = b":begin -->"

DECISION_OLD = "decision-old.md"
DECISION_OLD_AUTH = "decision-old-auth.md"
DECISION_DUP = "decision-dup.md"
DECISION_A = "decision-a.md"
DECISION_A2 = "decision-a-2.md"
DECISION_B = "decision-b.md"
LOG_X = "log-x.md"
LOG_SUB = "log-sub.md"
LOG_PRE_GROUP = "log-pre-group.md"
FEEDBACK_TONE = "feedback-tone.md"
FEEDBACK_Y = "feedback-y.md"

MODE_OWNER_RO = 0o500
MODE_OWNER_RWX = 0o700
MODE_GROUP_READ = 0o640
EXPECTED_GUARD_COUNT = 2
EXIT_INVALID_ARGS = 2
EXIT_UNWRITABLE_STORE = 3


def run_store(store: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run memoir.py against an explicit store path from beside the store."""
    env = {**os.environ, ENV_MEMOIR_STORE: str(store)}
    # Run beside the store, not in this repo, whose own v1 `.agents/memoir` would be migrated.
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=store.expanduser().parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def run_cli(
    cwd: Path,
    env: dict[str, str],
    *args: str | Path,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run memoir.py in a specific working directory with explicit environment."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(a) for a in args)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=check,
    )


def run_git(*args: str | Path) -> None:
    """Run git cleanly with deterministic test author metadata."""
    subprocess.run(
        [GIT, "-c", "user.name=t", "-c", "user.email=t@t", *(str(a) for a in args)],
        check=True,
        capture_output=True,
    )


def load_always_on_block() -> str:
    """Read the canonical Always-on markdown fenced block from memoir references."""
    always_on = (SCRIPT.parents[1] / "references" / "always-on.md").read_text(encoding=UTF8)
    return always_on[always_on.index("```markdown"):always_on.rindex("```") + 3]


def test_init_resume_and_archive() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "store"
        base = Path(run_store(store, "path").stdout.strip())
        active = base / "active"

        out = run_store(store, CMD_RESUME)
        assert out.returncode == 0
        assert str(active) in out.stdout
        assert "Start fresh" in out.stdout

        run_store(store, "init")
        (active / STATE_FILE).write_text(HDR_SESSION_STATE, encoding=UTF8)
        (active / DECISION_OLD_AUTH).write_text(HDR_SUPERSEDES_NONE, encoding=UTF8)
        (active / "decision-new-auth.md").write_text(
            f"Supersedes: {DECISION_OLD_AUTH}\n",
            encoding=UTF8,
        )
        (active / "reference-api.md").write_text("Target: x\n", encoding=UTF8)

        lines = run_store(store, CMD_RESUME).stdout.splitlines()
        assert lines[2] == str(active), lines
        assert lines[5].endswith(STATE_FILE), lines

        archived = run_store(store, CMD_ARCHIVE, FLAG_SUPERSEDED)
        assert archived.returncode == 0
        assert MSG_ARCHIVED_ONE in archived.stdout
        assert not (active / DECISION_OLD_AUTH).exists()
        assert run_store(store, CMD_ARCHIVE, FLAG_SUPERSEDED).returncode == 0

        outside_md = str(Path(tmp) / "outside.md")
        for invalid_name in (STATE_FILE, "../x.md", outside_md, "Bad_Name.md", "missing-x.md"):
            assert run_store(store, CMD_ARCHIVE, invalid_name).returncode == 1, invalid_name

        (active / DECISION_OLD_AUTH).write_text("second\n", encoding=UTF8)
        assert run_store(store, CMD_ARCHIVE, DECISION_OLD_AUTH).returncode == 1
        assert (active / DECISION_OLD_AUTH).exists()

        assert run_store(store, CMD_ARCHIVE).returncode == EXIT_INVALID_ARGS

        home_store = run_store(Path("~/memoir-test-x"), "path").stdout.strip()
        assert Path(home_store).is_relative_to(Path.home() / "memoir-test-x"), home_store


def test_wiki_diff_and_lag() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        work = root / "work"
        work.mkdir()
        store = root / "store"
        env = {**os.environ, ENV_MEMOIR_STORE: str(store)}
        def cli(*args):
            return run_cli(work, env, *args, check=True).stdout

        assert not cli("wiki-diff") and not store.exists()
        run_git("init", "-q", work)
        assert not cli("wiki-diff") and not store.exists()
        cli("init")
        scope, base = map(Path, cli("scope").splitlines())
        archived = base / "archive" / "20260101-log-note.md"
        archived.write_bytes(b"note")
        other = scope / "clones" / "other" / "paths" / "_main" / "active"
        other.mkdir(parents=True)
        shared = other / "reference-doc.md"
        shared.write_bytes(b"doc")
        for name in ("state-current.md", "task-open.md"):
            (other / name).write_bytes(b"ignore")
        assert "Wiki:" not in cli("resume")
        wiki = scope / "wiki"
        wiki.mkdir()
        rows = [(str(p.relative_to(scope)), hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted([archived, shared])]
        assert cli("wiki-diff").splitlines() == [f"new {h} {key}" for key, h in rows]
        assert "No recorded session" in cli("resume") and "(2 new)" in cli("resume")
        seen = {key: {"sha256": h, "pages": []} for key, h in rows}
        mark = wiki / ".ingest-state.json"
        mark.write_text(json.dumps({"fragments": seen}))
        assert cli("wiki-diff") == "" and "Wiki:" not in cli("resume")
        shared.write_bytes(b"update")
        archived.unlink()
        assert cli("wiki-diff").splitlines() == [
            f"changed {hashlib.sha256(b'update').hexdigest()} {shared.relative_to(scope)}",
            f"missing - {archived.relative_to(scope)}",
        ]
        assert "(1 changed, 1 missing)" in cli("resume")
        shared.write_bytes(b"doc")
        assert "(1 missing)" in cli("resume")
        mark.write_text("[]")
        assert run_cli(work, env, "wiki-diff").returncode == 1
        assert "No recorded session" in cli("resume")

        member = root / "member"
        member.mkdir()
        run_cli(member, env, "pin", root, check=True)
        run_cli(member, env, "init", check=True)
        group, folder = map(Path, run_cli(member, env, "scope", check=True).stdout.splitlines())
        log = folder / "active" / LOG_X
        log.write_bytes(b"x")
        assert run_cli(member, env, "wiki-diff", check=True).stdout.strip().endswith(os.path.relpath(log, group))


def test_retirement_and_backlog() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        env = {**os.environ, ENV_MEMOIR_STORE: str(root / "store"), "MEMOIR_LOG_MAX_AGE_DAYS": "30"}
        run_cli(root, env, "init", check=True)
        base = Path(run_cli(root, env, "path", check=True).stdout.strip())
        active, archive = base / "active", base / "archive"
        today = datetime.now().astimezone().date()
        for days in (0, 30, 31):
            (active / f"log-age-{days}.md").write_text(f"Date: {today - timedelta(days=days)}\n")
        (active / "log-broken.md").write_text("Date: 2026-02-30\n")
        (active / "log-future.md").write_text(f"Date: {today + timedelta(days=1)}\n")
        (active / "task-open.md").write_text("Status: open\n\nStatus: done\n")
        (active / "task-shipped.md").write_text("Status: done\n")
        for kind in ("feedback", "reference"):
            (active / f"{kind}-old.md").write_text("# Older fragment without Supersedes\n")
            (active / f"{kind}-new.md").write_text(f"Supersedes: {kind}-old.md, task-open.md\n")
        bad = {**env, "MEMOIR_LOG_MAX_AGE_DAYS": "-1"}
        assert run_cli(root, bad, "archive", "--retired").returncode == 1
        assert not list(archive.iterdir())
        assert "Archived 4 files" in run_cli(root, env, "archive", "--retired", check=True).stdout
        assert "Archived 0 files" in run_cli(root, env, "archive", "--retired", check=True).stdout
        for name in ("task-open", "log-age-30", "log-broken", "log-future"):
            assert (active / f"{name}.md").is_file()
        for kind in ("reference", "feedback"):
            assert f"Superseded-By: {kind}-new.md" in next(archive.glob(f"*-{kind}-old.md")).read_text()
        assert "Archived 1 files" in run_cli(root, {**env, "MEMOIR_LOG_MAX_AGE_DAYS": "0"}, "archive", "--retired", check=True).stdout
        assert (active / "log-age-0.md").exists()

    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "store"
        run_store(store, "init")
        active = Path(run_store(store, "path").stdout.strip()) / "active"
        (active / "missing-target.md").symlink_to(active / "absent")
        for index in range(50):
            (active / f"task-{index}.md").touch()
        size_file = active / "task-0.md"
        size_file.write_bytes(b"x" * 61440)
        assert "Active: 50 files, 61440 bytes\n" in run_store(store, "resume").stdout
        size_file.write_bytes(b"x" * 61441)
        assert "61441 bytes; run /memoir prune" in run_store(store, "resume").stdout
        size_file.write_bytes(b"")
        (active / "task-extra.md").touch()
        assert "51 files, 0 bytes; run /memoir prune" in run_store(store, "resume").stdout


def test_docs_and_skill_invariants() -> None:
    block = load_always_on_block()
    assert block in (Path(__file__).parent / "README.md").read_text(encoding=UTF8), (
        "README always-on block drifted"
    )
    assert "uv run" not in (SCRIPT.parents[1] / "SKILL.md").read_text(encoding=UTF8), (
        "SKILL.md must invoke the CLI with python3"
    )


def test_project_init_blocks_and_adoption() -> None:
    block = load_always_on_block()
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw).resolve()
        project = root / "project"
        child = project / "subdir"
        child.mkdir(parents=True)
        run_git("init", "-q", project)
        store = root / "store"
        env = {**os.environ, ENV_MEMOIR_STORE: str(store)}
        agents, claude = project / FILE_AGENTS, project / FILE_CLAUDE

        for first, second in ((SKILL_MEMOIR, SKILL_WIKI), (SKILL_WIKI, SKILL_MEMOIR)):
            run_cli(child, env, CMD_PROJECT_INIT, first, check=True)
            first_block = agents.read_bytes()
            assert f"<!-- {first}:begin -->".encode() in first_block
            assert f"<!-- {second}:begin -->".encode() not in first_block
            run_cli(child, env, CMD_PROJECT_INIT, second, check=True)
            both = agents.read_bytes()
            assert both.startswith(first_block)
            assert both.count(GUARD_BEGIN) == EXPECTED_GUARD_COUNT
            mtime = agents.stat().st_mtime_ns
            run_cli(child, env, CMD_PROJECT_INIT, first, check=True)
            run_cli(child, env, CMD_PROJECT_INIT, second, check=True)
            assert agents.read_bytes() == both
            assert agents.stat().st_mtime_ns == mtime
            agents.unlink()
        assert not store.exists()
        assert not (child / FILE_AGENTS).exists()

        # Adopt the manual CRLF block in place, preserving the user's BOM, text, and file mode.
        legacy = block.removeprefix("```markdown\n").removesuffix("\n```").replace("\n", "\r\n").encode()
        prefix, suffix = b"\xef\xbb\xbf# Team rules\r\n\r\n", b"\r\n\r\n## More rules\r\nKeep me."
        agents.write_bytes(prefix + legacy + suffix)
        agents.chmod(MODE_GROUP_READ)
        claude.write_text("# Project\nSee @./AGENTS.md for shared instructions.\n", encoding=UTF8)
        run_cli(child, env, CMD_PROJECT_INIT, SKILL_MEMOIR, check=True)
        guarded = b"<!-- memoir:begin -->\r\n" + legacy + b"\r\n<!-- memoir:end -->"
        assert agents.read_bytes() == prefix + guarded + suffix
        assert agents.stat().st_mode & 0o777 == MODE_GROUP_READ
        run_cli(child, env, CMD_PROJECT_INIT, SKILL_WIKI, check=True)
        complete = agents.read_bytes()
        agents.write_bytes(complete.replace(legacy, b"Old managed text"))
        run_cli(child, env, CMD_PROJECT_INIT, SKILL_MEMOIR, check=True)
        assert agents.read_bytes() == complete
        assert ":begin -->" not in claude.read_text(encoding=UTF8)

        malformed_cases = (
            b"<!-- memoir:begin -->",
            b"<!-- memoir:end -->",
            b"<!-- memoir:begin -->\n<!-- memoir-wiki:begin -->\n<!-- memoir:end -->",
            guarded + b"\n" + guarded,
            legacy + b"\r\n- A custom capture rule",
        )
        for bad_bytes in malformed_cases:
            agents.write_bytes(bad_bytes)
            assert run_cli(child, env, CMD_PROJECT_INIT, SKILL_MEMOIR).returncode != 0
            assert agents.read_bytes() == bad_bytes


def test_project_init_claude_symlink_and_pinned() -> None:
    block = load_always_on_block()
    legacy = block.removeprefix("```markdown\n").removesuffix("\n```").replace("\n", "\r\n").encode()
    custom_rule = legacy + b"\r\n- A custom capture rule"
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw).resolve()
        project = root / "project"
        child = project / "subdir"
        child.mkdir(parents=True)
        run_git("init", "-q", project)
        env = {**os.environ, ENV_MEMOIR_STORE: str(root / "store")}
        agents, claude = project / FILE_AGENTS, project / FILE_CLAUDE
        agents.write_bytes(custom_rule)

        claude.write_text("```text\n@AGENTS.md\n```\n", encoding=UTF8)
        before = claude.read_bytes()
        err = run_cli(child, env, CMD_PROJECT_INIT, SKILL_WIKI).stderr
        assert "Choose AGENTS.md or CLAUDE.md" in err
        assert claude.read_bytes() == before
        run_cli(child, env, CMD_PROJECT_INIT, SKILL_WIKI, "CLAUDE.md", check=True)
        assert claude.read_bytes().startswith(before)
        assert agents.read_bytes() == custom_rule

        agents.unlink()
        run_cli(child, env, CMD_PROJECT_INIT, SKILL_MEMOIR, check=True)  # CLAUDE.md alone
        assert not agents.exists()
        assert claude.read_bytes().count(GUARD_BEGIN) == EXPECTED_GUARD_COUNT

        outside = root / "outside"
        outside.write_text("leave alone", encoding=UTF8)
        agents.symlink_to(outside)
        assert run_cli(child, env, CMD_PROJECT_INIT, SKILL_MEMOIR, FILE_AGENTS).returncode != 0
        assert outside.read_text(encoding=UTF8) == "leave alone"
        assert agents.is_symlink()

        pinned = root / "pinned"
        nested = pinned / "nested"
        nested.mkdir(parents=True)
        run_cli(nested, env, "pin", pinned, check=True)
        run_cli(nested, env, CMD_PROJECT_INIT, SKILL_WIKI, check=True)
        assert (pinned / FILE_AGENTS).is_file()
        assert not (nested / FILE_AGENTS).exists()


def test_superseded_by_backlink_and_feedback_archive() -> None:
    # --- B5: Superseded-By back-link is written into the ARCHIVED copy, right after Supersedes: ---
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "store"
        base = Path(run_store(store, "path").stdout.strip())
        active = base / "active"
        run_store(store, "init")
        (active / DECISION_OLD).write_text(f"Date: 2026-10-20\n{HDR_SUPERSEDES_NONE}Body: 123\n", encoding=UTF8)
        (active / "decision-new.md").write_text(f"Date: 2026-10-20\nSupersedes: {DECISION_OLD}\nBody: 456\n", encoding=UTF8)
        out = run_store(store, CMD_ARCHIVE, FLAG_SUPERSEDED)
        assert out.returncode == 0
        assert MSG_ARCHIVED_ONE in out.stdout
        archived = base / CMD_ARCHIVE / f"{datetime.now(UTC).astimezone():%Y%m%d}-{DECISION_OLD}"
        assert archived.exists(), "Archived file not found"
        archived_lines = archived.read_text(encoding=UTF8).splitlines()
        assert "Supersedes: none" in archived_lines
        assert "Superseded-By: decision-new.md" in archived_lines
        idx_sup = archived_lines.index("Supersedes: none")
        idx_back = archived_lines.index("Superseded-By: decision-new.md")
        assert idx_back == idx_sup + 1

    # --- B1: feedback-*.md fragments are archivable (parity with decision/log/reference) ---
    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "store"
        base = Path(run_store(store, "path").stdout.strip())
        active = base / "active"
        run_store(store, "init")
        (active / FEEDBACK_TONE).write_text("note\n", encoding=UTF8)
        out = run_store(store, CMD_ARCHIVE, FEEDBACK_TONE)
        assert out.returncode == 0
        assert MSG_ARCHIVED_ONE in out.stdout
        assert not (active / FEEDBACK_TONE).exists()
        (active / FEEDBACK_TONE).write_text("note\n", encoding=UTF8)
        assert run_store(store, CMD_ARCHIVE, FEEDBACK_TONE).returncode == 1  # no overwrite
        assert (active / FEEDBACK_TONE).exists()


def test_git_store_and_unwritable_store() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp).resolve() / "repo"
        repo.mkdir()
        run_git("init", "-q", repo)
        env = {**os.environ, "HOME": tmp, ENV_MEMOIR_STORE: ""}
        out = run_cli(repo, env, "prompt", check=True)
        assert Path(out.stdout.splitlines()[-1]).is_relative_to(Path(tmp).resolve() / ".memoir")
        assert not (repo / ".gitignore").exists()
        assert not (repo / ".agents").exists()

        ro = Path(tmp).resolve() / "ro"
        ro.mkdir()
        ro.chmod(MODE_OWNER_RO)
        try:
            if os.geteuid() != 0:
                denied = run_store(ro / "store", CMD_RESUME)
                assert denied.returncode == EXIT_UNWRITABLE_STORE
                assert f"No write access to {ro / 'store'}" in denied.stderr
                assert not (ro / "store").exists()
        finally:
            ro.chmod(MODE_OWNER_RWX)


def test_v1_store_migration() -> None:
    # --- FR-1.7 / FR-1.8: v1 stores copy once into empty v2 scopes; MEMOIR_STORE at v1 fails ---
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw).resolve()
        env = {**os.environ, "HOME": str(tmp), ENV_MEMOIR_STORE: "", "XDG_CONFIG_HOME": str(tmp / "xdg")}

        repo = tmp / "repo"
        run_git("init", "-q", repo)
        legacy = repo / ".agents" / SKILL_MEMOIR
        (legacy / "active").mkdir(parents=True)
        (legacy / CMD_ARCHIVE).mkdir()
        (legacy / "active" / STATE_FILE).write_text(HDR_SESSION_STATE, encoding=UTF8)
        (legacy / CMD_ARCHIVE / "20260101-log-old.md").write_text("old\n", encoding=UTF8)
        base = Path(run_cli(repo, env, "path").stdout.strip())
        assert not (base / "active").exists()  # path is read-only: no migration
        out = run_cli(repo, env, CMD_RESUME)
        assert out.returncode == 0
        assert f"Migrated 2 files from {legacy} to {base}" in out.stderr
        assert (base / "active" / STATE_FILE).read_text(encoding=UTF8) == HDR_SESSION_STATE
        assert (base / CMD_ARCHIVE / "20260101-log-old.md").exists()
        assert (legacy / "active" / STATE_FILE).exists()  # copied, not moved
        assert str(base / "active" / STATE_FILE) in out.stdout

        (base / "active" / STATE_FILE).write_text(f"{HDR_SESSION_STATE}Updated later\n", encoding=UTF8)
        (legacy / "active" / "decision-done.md").write_text("done\n", encoding=UTF8)
        (base / CMD_ARCHIVE / "20260102-decision-done.md").write_text("done\n", encoding=UTF8)
        done_out = run_cli(repo, env, CMD_RESUME)
        assert f"is already migrated to {base}; delete {legacy}" in done_out.stderr
        assert "not migrated" not in done_out.stderr

        (legacy / "active" / "decision-late.md").write_text("late\n", encoding=UTF8)
        late_out = run_cli(repo, env, CMD_RESUME)
        assert "Migrated" not in late_out.stderr
        assert "not migrated" in late_out.stderr  # no merge into a used scope
        assert not (base / "active" / "decision-late.md").exists()

        plain = tmp / "plain"  # non-Git v1 `.claude/memoir` at the cwd
        (plain / ".claude" / SKILL_MEMOIR / "active").mkdir(parents=True)
        (plain / ".claude" / SKILL_MEMOIR / "active" / LOG_X).write_text("x\n", encoding=UTF8)
        init_out = run_cli(plain, env, "init")
        assert init_out.returncode == 0
        assert "Migrated 1 files" in init_out.stderr
        assert (Path(run_cli(plain, env, "path").stdout.strip()) / "active" / LOG_X).exists()

        v1_err = run_store(legacy, CMD_RESUME)
        assert v1_err.returncode == 1
        assert "is a v1 store" in v1_err.stderr
        assert not (legacy / "repos").exists()
        assert not (legacy / "standalone").exists()


def test_pinned_workspace_groups() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw).resolve()
        env = {**os.environ, "HOME": str(tmp), ENV_MEMOIR_STORE: "", "XDG_CONFIG_HOME": str(tmp / "xdg")}

        ws = tmp / "ws"
        (ws / "sub" / "deep").mkdir(parents=True)
        scope: dict[Path, Path] = {}
        for folder in (ws, ws / "sub"):
            scope[folder] = Path(run_cli(folder, env, "path").stdout.strip())
            assert "/standalone/" in str(scope[folder])
            run_cli(folder, env, "init")
            (scope[folder] / "active" / STATE_FILE).write_text(f"# {folder.name}\n", encoding=UTF8)
            (scope[folder] / "active" / f"log-{folder.name}.md").write_text("x\n", encoding=UTF8)
        (scope[ws] / "active" / DECISION_OLD).write_text(HDR_SUPERSEDES_NONE, encoding=UTF8)

        pin_out = run_cli(ws, env, "pin")
        assert pin_out.returncode == 0
        assert "/pinned/" in pin_out.stdout
        group = Path(pin_out.stdout.split(" (")[0])
        assert Path(run_cli(ws / "sub", env, "path").stdout.strip()) == scope[ws / "sub"]

        listed = run_cli(ws / "sub", env, CMD_RESUME).stdout.splitlines()
        files = [line.split(". ", 1)[1] for line in listed if line[:1].isdigit()]
        assert files[0] == str(scope[ws / "sub"] / "active" / STATE_FILE), files
        assert str(scope[ws] / "active" / "log-ws.md") in files
        assert str(scope[ws] / "active" / DECISION_OLD) in files
        assert str(scope[ws] / "active" / STATE_FILE) not in files

        scope_lines = run_cli(ws / "sub", env, "scope").stdout.splitlines()
        assert scope_lines[0] == str(group)
        assert sorted(scope_lines[1:]) == sorted(map(str, scope.values()))

        # A decision in sub supersedes one in ws: archived inside ws's own scope.
        (scope[ws / "sub"] / "active" / "decision-new.md").write_text(
            f"Supersedes: {DECISION_OLD}\n",
            encoding=UTF8,
        )
        arch_out = run_cli(ws / "sub", env, CMD_ARCHIVE, FLAG_SUPERSEDED)
        assert arch_out.returncode == 0
        assert MSG_ARCHIVED_ONE in arch_out.stdout
        assert not (scope[ws] / "active" / DECISION_OLD).exists()
        assert any((scope[ws] / CMD_ARCHIVE).glob(f"*-{DECISION_OLD}"))

        # Superseding decision's own scope wins when both hold the name.
        for folder in (ws, ws / "sub"):
            (scope[folder] / "active" / DECISION_DUP).write_text(HDR_SUPERSEDES_NONE, encoding=UTF8)
        (scope[ws / "sub"] / "active" / "decision-newer.md").write_text(
            f"Supersedes: {DECISION_DUP}\n",
            encoding=UTF8,
        )
        assert run_cli(ws, env, CMD_ARCHIVE, FLAG_SUPERSEDED).returncode == 0
        assert (scope[ws] / "active" / DECISION_DUP).exists()
        assert not (scope[ws / "sub"] / "active" / DECISION_DUP).exists()

        # Nested pin takes sub (and its own subfolders) out of ws group.
        deep = Path(run_cli(ws / "sub" / "deep", env, "path").stdout.strip())
        run_cli(ws / "sub" / "deep", env, "init")
        assert run_cli(ws / "sub", env, "pin").returncode == 0
        assert str(scope[ws / "sub"] / "active" / LOG_SUB) not in run_cli(ws, env, CMD_RESUME).stdout
        assert str(scope[ws / "sub"] / "active" / LOG_SUB) in run_cli(ws / "sub" / "deep", env, CMD_RESUME).stdout
        assert str(deep) in run_cli(ws / "sub", env, "scope").stdout
        assert run_cli(ws / "sub", env, "unpin").returncode == 0

        # Unpin: each folder resumes only its own notes again, and nothing moved.
        assert run_cli(ws, env, "unpin").returncode == 0
        sub_resume = run_cli(ws / "sub", env, CMD_RESUME).stdout
        assert str(scope[ws] / "active" / "log-ws.md") not in sub_resume
        assert str(scope[ws / "sub"] / "active" / LOG_SUB) in sub_resume
        assert run_cli(ws / "sub", env, "scope").stdout == ""
        assert (group / "workspace.json").exists()

        # Legacy pre-group fragments inside pin copy into folder's standalone scope.
        legacy_ws = tmp / "legacy-ws"
        legacy_ws.mkdir()
        pinned_dir = Path(run_cli(legacy_ws, env, "pin").stdout.split(" (")[0])
        (pinned_dir / "paths" / "_root" / "active").mkdir(parents=True)
        (pinned_dir / "paths" / "_root" / "active" / LOG_PRE_GROUP).write_text("old\n", encoding=UTF8)
        mig_out = run_cli(legacy_ws, env, CMD_RESUME)
        own = Path(run_cli(legacy_ws, env, "path").stdout.strip())
        assert f"Migrated 1 files from {pinned_dir / 'paths' / '_root'} to {own}" in mig_out.stderr
        assert (own / "active" / LOG_PRE_GROUP).exists()
        assert (pinned_dir / "paths" / "_root" / "active" / LOG_PRE_GROUP).exists()

        # gc reports a standalone scope whose folder is gone.
        gone = tmp / "gone"
        gone.mkdir()
        run_cli(gone, env, "init")
        gone_scope = Path(run_cli(gone, env, "path").stdout.strip())
        gone.rmdir()
        assert f"Orphan: {gone_scope} (missing directory {gone})" in run_cli(tmp, env, "gc").stdout


def test_sibling_worktrees_and_adopt() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw).resolve()
        env = {**os.environ, "HOME": str(tmp), ENV_MEMOIR_STORE: "", "XDG_CONFIG_HOME": str(tmp / "xdg")}

        main_wt, feat_wt, gone_wt = tmp / "repo", tmp / "repo" / "wt" / "feat", tmp / "gone"
        run_git("init", "-q", main_wt)
        run_git("-C", main_wt, "commit", "-q", "--allow-empty", "-m", "init")
        run_git("-C", main_wt, "worktree", "add", "-q", feat_wt)
        run_git("-C", main_wt, "worktree", "add", "-q", gone_wt)
        base = {wt: Path(run_cli(wt, env, "path").stdout.strip()) for wt in (main_wt, feat_wt, gone_wt)}
        assert base[feat_wt].name == "wt__feat"
        gone_key = f"gone--{hashlib.sha256(str(gone_wt).encode()).hexdigest()[:8]}"
        assert base[gone_wt].name == gone_key
        for wt in base:
            assert run_cli(wt, env, "init").returncode == 0
        assert f'"root": "{feat_wt}"' in (base[feat_wt] / "worktree.json").read_text(encoding=UTF8)

        active_dirs = {wt: base[wt] / "active" for wt in base}
        (active_dirs[main_wt] / STATE_FILE).write_text("# main\n", encoding=UTF8)
        (active_dirs[main_wt] / DECISION_A).write_text(f"{HDR_SUPERSEDES_NONE}main\n", encoding=UTF8)
        (active_dirs[feat_wt] / STATE_FILE).write_text("# feat\n", encoding=UTF8)
        (active_dirs[feat_wt] / DECISION_A).write_text(f"{HDR_SUPERSEDES_NONE}feat\n", encoding=UTF8)
        (active_dirs[feat_wt] / DECISION_B).write_text(f"Date: 2026-11-01\nSupersedes: {DECISION_A}\n", encoding=UTF8)
        (active_dirs[feat_wt] / LOG_X).write_text("x\n", encoding=UTF8)
        (active_dirs[feat_wt] / FEEDBACK_Y).write_text("y\n", encoding=UTF8)
        os.utime(active_dirs[feat_wt] / LOG_X, (1767225600, 1767225600))
        for frag in (
            active_dirs[feat_wt] / DECISION_A,
            active_dirs[feat_wt] / DECISION_B,
            active_dirs[feat_wt] / FEEDBACK_Y,
        ):
            os.utime(frag, (1735689600, 1735689600))
        (active_dirs[gone_wt] / "reference-r.md").write_text("Target: x\n", encoding=UTF8)
        run_git("-C", main_wt, "worktree", "remove", gone_wt)

        empty = base[main_wt].parent / "empty"
        (empty / "active").mkdir(parents=True)
        (empty / "active" / STATE_FILE).write_text("# state only\n", encoding=UTF8)
        legacy = base[main_wt].parent / "legacy"
        (legacy / "active").mkdir(parents=True)
        (legacy / "active" / "log-old.md").write_text("old\n", encoding=UTF8)

        summary = run_cli(main_wt, env, CMD_RESUME).stdout
        head = "Sibling worktrees with fragments (not loaded; add with resume --with <key>):"
        newest_feat = datetime.fromtimestamp(1767225600, UTC).astimezone().strftime(FMT_DATE)
        newest_gone = datetime.fromtimestamp(
            (active_dirs[gone_wt] / "reference-r.md").stat().st_mtime,
            UTC,
        ).astimezone().strftime(FMT_DATE)
        newest_legacy = datetime.fromtimestamp(
            (legacy / "active" / "log-old.md").stat().st_mtime,
            UTC,
        ).astimezone().strftime(FMT_DATE)
        assert summary.split(head)[1].strip().splitlines() == [
            f"- {gone_key}: 0 decisions, 0 logs, 1 references, 0 feedback; newest {newest_gone}; worktree missing",
            f"- legacy: 0 decisions, 1 logs, 0 references, 0 feedback; newest {newest_legacy}; worktree unknown",
            f"- wt__feat: 2 decisions, 1 logs, 0 references, 1 feedback; newest {newest_feat}; worktree present",
        ], summary
        assert str(active_dirs[feat_wt]) not in summary.split(head)[0]
        assert "- _main:" in run_cli(feat_wt, env, CMD_RESUME).stdout

        loaded = run_cli(main_wt, env, CMD_RESUME, FLAG_WITH, "wt__feat", FLAG_WITH, "wt__feat").stdout
        files = [line.split(". ", 1)[1] for line in loaded.splitlines() if line[:1].isdigit()]
        assert files == [str(active_dirs[main_wt] / n) for n in (STATE_FILE, DECISION_A)] + [
            str(active_dirs[feat_wt] / n) for n in (DECISION_A, DECISION_B, FEEDBACK_Y, LOG_X)
        ], files
        for bad_key in ("_main", "nope", "..", ""):
            err = run_cli(main_wt, env, CMD_RESUME, FLAG_WITH, bad_key)
            assert err.returncode == 1
            assert f"No sibling path {bad_key} in " in err.stderr
        assert "No clone path wt__feat/active in " in run_cli(main_wt, env, CMD_RESUME, FLAG_WITH, "wt__feat/active").stderr
        assert run_cli(tmp, env, "adopt", "x").returncode == 1

        (active_dirs[feat_wt] / "task-review-auth.md").write_text(f"Origin: {DECISION_A}\nStatus: open\n")
        adopt_out = run_cli(main_wt, env, "adopt", "wt__feat", check=True)
        assert adopt_out.stdout.splitlines() == [
            "[Memoir] Adopted 5 files from wt__feat.",
            f"{active_dirs[main_wt] / DECISION_A2} (renamed from {DECISION_A})",
            f"{active_dirs[main_wt] / DECISION_B}",
            f"{active_dirs[main_wt] / FEEDBACK_Y}",
            f"{active_dirs[main_wt] / LOG_X}",
            f"{active_dirs[main_wt] / 'task-review-auth.md'}",
        ]
        assert (active_dirs[main_wt] / DECISION_A).read_text(encoding=UTF8) == f"{HDR_SUPERSEDES_NONE}main\n"
        assert (active_dirs[main_wt] / DECISION_A2).read_text(encoding=UTF8) == f"{HDR_SUPERSEDES_NONE}feat\n"
        assert (active_dirs[main_wt] / DECISION_B).read_text(encoding=UTF8) == (
            f"Date: 2026-11-01\nSupersedes: {DECISION_A2}\n"
        )
        assert f"Origin: {DECISION_A2}" in (active_dirs[main_wt] / "task-review-auth.md").read_text()
        assert sorted(p.name for p in active_dirs[feat_wt].iterdir()) == [STATE_FILE]
        assert (active_dirs[main_wt] / STATE_FILE).read_text(encoding=UTF8) == "# main\n"
        assert "Adopted 0 files from wt__feat." in run_cli(main_wt, env, "adopt", "wt__feat").stdout

        arch = run_cli(main_wt, env, CMD_ARCHIVE, FLAG_SUPERSEDED)
        assert arch.returncode == 0
        assert MSG_ARCHIVED_ONE in arch.stdout
        assert (active_dirs[main_wt] / DECISION_A).exists()
        assert not (active_dirs[main_wt] / DECISION_A2).exists()


def test_external_worktree_keys() -> None:
    """FR-1.3/FR-1.7: external worktrees get hashed keys; pre-hash folders are copied only into their owner."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw).resolve()
        env = {**os.environ, "HOME": str(tmp), ENV_MEMOIR_STORE: "", "XDG_CONFIG_HOME": str(tmp / "xdg")}
        main_wt, a_wt, b_wt, c_wt, named_main = (
            tmp / "repo", tmp / "a" / "feat", tmp / "b" / "feat", tmp / "c" / "feat", tmp / "x" / "_main",
        )
        run_git("init", "-q", main_wt)
        run_git("-C", main_wt, "commit", "-q", "--allow-empty", "-m", "init")
        for wt in (a_wt, b_wt, c_wt, named_main):
            run_git("-C", main_wt, "worktree", "add", "-q", "--detach", wt)
        base = {wt: Path(run_cli(wt, env, "path").stdout.strip()) for wt in (main_wt, a_wt, b_wt, c_wt, named_main)}
        assert len(set(base.values())) == len(base), base  # same-named and `_main`-named worktrees stay apart
        assert base[main_wt].name == "_main"
        assert base[a_wt].name == f"feat--{hashlib.sha256(str(a_wt).encode()).hexdigest()[:8]}"

        # A pre-hash `paths/feat/` recorded for a_wt is copied into a_wt's new scope, never into b_wt's.
        old = base[main_wt].parent / "feat"
        (old / "active").mkdir(parents=True)
        (old / "active" / DECISION_A).write_text(HDR_SUPERSEDES_NONE, encoding=UTF8)
        (old / "worktree.json").write_text(f'{{"root": "{a_wt}", "last_seen": "x"}}\n', encoding=UTF8)
        out = run_cli(a_wt, env, CMD_RESUME)
        assert f"Migrated 1 files from {old} to {base[a_wt]}" in out.stderr, out
        assert (base[a_wt] / "active" / DECISION_A).exists() and (old / "active" / DECISION_A).exists()
        out = run_cli(b_wt, env, CMD_RESUME)
        assert "Migrated" not in out.stderr and not (base[b_wt] / "active" / DECISION_A).exists(), out

        # A pre-hash folder written before worktree.json existed is copied into the first claimant.
        (old / "worktree.json").unlink()
        assert f"Migrated 1 files from {old} to {base[c_wt]}" in run_cli(c_wt, env, CMD_RESUME).stderr


def test_peek_other_clones() -> None:
    """FR-2.4 --peek: other clones of the repo are listed per clone and loadable as <clone_id>/<key>; never adopted."""
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw).resolve()
        env = {**os.environ, "HOME": str(tmp), ENV_MEMOIR_STORE: "", "XDG_CONFIG_HOME": str(tmp / "xdg")}
        clones = {name: tmp / name / "app" for name in ("a", "b", "c", "d")}
        for root in clones.values():
            run_git("init", "-q", root)
            run_git("-C", root, "remote", "add", "origin", "https://example.com/o/app.git")
        run_git("-C", clones["b"], "commit", "-q", "--allow-empty", "-m", "init")
        b_wt = tmp / "b" / "spike"
        run_git("-C", clones["b"], "worktree", "add", "-q", "--detach", b_wt)
        base = {name: Path(run_cli(root, env, "path").stdout.strip()) for name, root in clones.items()}
        base["b_wt"] = Path(run_cli(b_wt, env, "path").stdout.strip())
        for name, root in [*clones.items(), ("b_wt", b_wt)]:
            assert run_cli(root, env, "init").returncode == 0, name
        clone_id = {name: base[name].parents[1].name for name in clones}
        assert len(set(clone_id.values())) == len(clones) and len({base[n].parents[2] for n in clones}) == 1

        (base["a"] / "active" / DECISION_A).write_text(HDR_SUPERSEDES_NONE, encoding=UTF8)
        (base["b"] / "active" / STATE_FILE).write_text("# b\n", encoding=UTF8)
        (base["b"] / "active" / DECISION_B).write_text(HDR_SUPERSEDES_NONE, encoding=UTF8)
        (base["b_wt"] / "active" / LOG_X).write_text("x\n", encoding=UTF8)
        (base["d"] / "active" / FEEDBACK_Y).write_text("y\n", encoding=UTF8)
        for frag in (base["b"] / "active" / DECISION_B, base["b_wt"] / "active" / LOG_X, base["d"] / "active" / FEEDBACK_Y):
            os.utime(frag, (1767225600, 1767225600))
        shutil.rmtree(tmp / "d")  # clone d is gone; c has no fragments and is omitted
        (base["b_wt"] / "worktree.json").write_text('{"root": "relative/spike", "last_seen": "x"}\n', encoding=UTF8)
        day = datetime.fromtimestamp(1767225600, UTC).astimezone().strftime(FMT_DATE)

        plain = run_cli(clones["a"], env, CMD_RESUME).stdout
        assert "Other clones" not in plain and "Sibling" not in plain, plain  # other clones' checkouts are never siblings
        peek = run_cli(clones["a"], env, CMD_RESUME, "--peek").stdout
        head = "Other clones with fragments (peek; add with resume --with <clone_id>/<key>):"
        expected = {
            clone_id["b"]: [
                f"clone {clone_id['b']}: root {clones['b']}, present",
                f"  - _main: 1 decisions, 0 logs, 0 references, 0 feedback; newest {day}; worktree present",
                f"  - {base['b_wt'].name}: 0 decisions, 1 logs, 0 references, 0 feedback; newest {day}; worktree unknown",
            ],
            clone_id["d"]: [
                f"clone {clone_id['d']}: root {clones['d']}, missing",
                f"  - _main: 0 decisions, 0 logs, 0 references, 1 feedback; newest {day}; worktree missing",
            ],
        }
        assert peek.split(head)[1].strip().splitlines() == [line for k in sorted(expected) for line in expected[k]], peek

        loaded = run_cli(clones["a"], env, CMD_RESUME, FLAG_WITH, f"{clone_id['b']}/_main").stdout
        files = [line.split(". ", 1)[1] for line in loaded.splitlines() if line[:1].isdigit()]
        assert files == [str(base["a"] / "active" / DECISION_A), str(base["b"] / "active" / DECISION_B)], files
        for bad in (f"{clone_id['b']}/nope", "nope/_main", f"{clone_id['a']}/_main", f"..{'/'}_main", f"{clone_id['b']}/.."):
            err = run_cli(clones["a"], env, CMD_RESUME, FLAG_WITH, bad)
            assert err.returncode == 1 and f"No clone path {bad} in {base['a'].parents[3]}" in err.stderr, (bad, err)
        err = run_cli(clones["a"], env, "adopt", f"{clone_id['b']}/_main")
        assert err.returncode == 1 and "No sibling path" in err.stderr, err
        assert (base["b"] / "active" / DECISION_B).exists()

        outside = tmp / "plain"
        outside.mkdir()
        out = run_cli(outside, env, CMD_RESUME, "--peek")
        assert out.returncode == 0 and "Other clones" not in out.stdout, out


def main() -> None:
    test_init_resume_and_archive()
    test_retirement_and_backlog()
    test_wiki_diff_and_lag()
    test_docs_and_skill_invariants()
    test_project_init_blocks_and_adoption()
    test_project_init_claude_symlink_and_pinned()
    test_superseded_by_backlink_and_feedback_archive()
    test_git_store_and_unwritable_store()
    test_v1_store_migration()
    test_pinned_workspace_groups()
    test_sibling_worktrees_and_adopt()
    test_external_worktree_keys()
    test_peek_other_clones()
    print("ok")


if __name__ == "__main__":
    main()
