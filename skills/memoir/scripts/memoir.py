#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
Memoir Helper CLI
Manages directory resolution, initialization, and archiving for the Memoir skill.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

UTF8 = "utf-8"
UTF8_SIG = "utf-8-sig"
GIT_REV_PARSE = "rev-parse"
FLAG_SHOW_TOPLEVEL = "--show-toplevel"
HDR_SUPERSEDES = "Supersedes:"
STATE_FILENAME = "state-current.md"
AGENTS_MD = "AGENTS.md"
CLAUDE_MD = "CLAUDE.md"

ARCHIVABLE_RE = re.compile(r"^(decision|log|reference|feedback|task)-[a-z0-9]+(-[a-z0-9]+)*\.md$")
FRAGMENT_LINK_RE = re.compile(r"(?<![\w./-])(?:decision|reference|feedback|log|task)-[a-z0-9]+(?:-[a-z0-9]+)*\.md(?![\w./-])")

def store_root() -> Path:
    return Path(os.environ.get("MEMOIR_STORE") or "~/.memoir").expanduser().resolve()


def scope_id(root: Path, identity: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "root"
    digest = hashlib.sha256(str(identity).encode()).hexdigest()[:8]
    return f"{slug}--{digest}"


def git_output(*args: str) -> str:
    git_bin = shutil.which("git")
    if not git_bin:
        return ""
    try:
        return subprocess.check_output([git_bin, *args], text=True, stderr=subprocess.DEVNULL).rstrip("\n")
    except (subprocess.CalledProcessError, OSError):
        return ""


def remote_id(remote: str, main_root: Path) -> str:
    if "://" in remote:
        url = urlsplit(remote)
        host = url.hostname or ""
        authority = f"{host}__{url.port}" if url.port else host
        value = f"{authority}/{url.path.lstrip('/')}"
    elif re.match(r"^(?:[^/@]+@)?[^/:]+:", remote):
        host, path = remote.split(":", 1)
        value = f"{host.split('@')[-1]}/{path.lstrip('/')}"
    else:
        value = str((main_root / remote).resolve())
    key = re.sub(r"[:/]+", "__", value.strip("/").lower().removesuffix(".git"))
    if key in {"", ".", ".."}:
        raise ValueError("Invalid origin identity")
    return key


def record_scope(record: Path, root: Path) -> None:
    record.parent.mkdir(parents=True, exist_ok=True)
    data = {"root": str(root), "last_seen": datetime.now(UTC).isoformat()}
    atomic_write(record, json.dumps(data) + "\n")


def pinned_roots(store: Path) -> list[Path]:
    try:
        pins = json.loads((store / "pinned.json").read_text(encoding=UTF8))
    except FileNotFoundError:
        return []
    if not isinstance(pins, list) or not all(isinstance(p, str) and Path(p).is_absolute() for p in pins):
        raise ValueError("pinned.json must contain an array of absolute paths")
    return [Path(p) for p in pins]


def update_pin(store: Path, root: Path, add: bool) -> None:
    import fcntl

    if add and not root.is_dir():
        raise ValueError(f"Cannot pin missing directory {root}")
    store.mkdir(parents=True, exist_ok=True)
    # Lock a stable inode because atomic replacement changes pinned.json's inode.
    with (store / ".pinned.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pins = set(pinned_roots(store))
        workspace = store / "pinned" / scope_id(root, root)
        if add:
            pins.add(root)
            record_scope(workspace / "workspace.json", root)
        else:
            pins.discard(root)
        atomic_write(store / "pinned.json", json.dumps(sorted(map(str, pins))) + "\n")
    print(f"{workspace} ({root})")


def group_of(store: Path, folder: Path, pins: list[Path] | None = None) -> tuple[Path, Path] | None:
    """The longest pin containing folder and its group directory, or None (FR-1.4)."""
    matches = [pin for pin in (pinned_roots(store) if pins is None else pins) if folder.is_relative_to(pin)]
    if not matches:
        return None
    root = max(matches, key=lambda pin: len(pin.parts))
    return root, store / "pinned" / scope_id(root, root)


def members_of(store: Path, base_dir: Path) -> list[Path]:
    """Every scope whose fragments a read in base_dir covers: the pinned group's members, else base_dir alone."""
    group = group_of(store, Path.cwd().resolve()) if base_dir.is_relative_to(store / "standalone") else None
    if group is None:
        return [base_dir]
    pins = pinned_roots(store)
    members = {base_dir}
    for record in (store / "standalone").glob("*/scope.json"):
        try:
            folder = Path(json.loads(record.read_text(encoding=UTF8))["root"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if (group_of(store, folder, pins) or (None,))[0] == group[0]:
            members.add(record.parent)
    return sorted(members)


def resolve_store(store: Path, record: bool) -> Path:
    top = git_output(GIT_REV_PARSE, FLAG_SHOW_TOPLEVEL)
    if not top:
        # Non-Git fragments always live in the folder's own scope; a pin only groups scopes.
        cwd = Path.cwd().resolve()
        base = store / "standalone" / scope_id(cwd, cwd)
        if record:
            record_scope(base / "scope.json", cwd)
            group = group_of(store, cwd)
            if group:
                record_scope(group[1] / "workspace.json", group[0])
        return base
    toplevel = Path(top).resolve()
    common_path = git_output(GIT_REV_PARSE, "--git-common-dir")
    if not common_path:
        raise ValueError("Cannot resolve Git common directory")
    common = Path(common_path).resolve()
    root = common.parent
    clone_id = scope_id(root, common)
    remote = git_output("remote", "get-url", "origin")
    repo_id = remote_id(remote, root) if remote else f"local__{clone_id}"
    clone = store / "repos" / repo_id / "clones" / clone_id
    if record:
        record_scope(clone / "clone.json", root)
    if toplevel == root:
        key = "_main"
    elif toplevel.is_relative_to(root):
        key = "__".join(toplevel.relative_to(root).parts)
    else:
        # Hashed so same-named external worktrees, or one named `_main`, never share a folder (FR-1.3).
        key = scope_id(toplevel, toplevel)
    if record:
        record_scope(clone / "paths" / key / "worktree.json", toplevel)
    return clone / "paths" / key


def fragments(scope: Path) -> list[Path]:
    """Archivable active fragments, including tasks."""
    return sorted(p for p in (scope / "active").glob("*.md") if ARCHIVABLE_RE.fullmatch(p.name) and p.is_file() and not p.is_symlink())


def _plain_name(part: str) -> bool:
    return part not in {"", ".", ".."} and Path(part).name == part


def sibling(store: Path, base_dir: Path, key: str, other_clones: bool = False) -> Path:
    """Another paths/<key>/ of the same Git clone, or with other_clones a `<clone_id>/<key>` of the repo (FR-2.4, FR-2.9)."""
    in_git = base_dir.is_relative_to(store / "repos")
    if other_clones and in_git and key.count("/") == 1:
        clone_id, name = key.split("/")
        path = base_dir.parents[2] / clone_id / "paths" / name
        if not (_plain_name(clone_id) and _plain_name(name)) or path == base_dir or not path.is_dir():
            raise ValueError(f"No clone path {key} in {base_dir.parents[3]}")
        return path
    path = base_dir.parent / key
    if not in_git or not _plain_name(key) or path == base_dir or not path.is_dir():
        raise ValueError(f"No sibling path {key} in {base_dir.parent.parent}")
    return path


def _record_root(record: Path) -> tuple[str, str]:
    """A clone.json or worktree.json root and whether it still exists: present, missing or unknown."""
    # Validated like gc's records: no linked record, and only an absolute string root is checked on disk.
    try:
        metadata = None if record.resolve() != record else json.loads(record.read_text(encoding=UTF8))
    except (OSError, ValueError):
        metadata = None
    root = metadata.get("root") if isinstance(metadata, dict) else None
    if not isinstance(root, str) or not Path(root).is_absolute():
        return "unknown", "unknown"
    return root, "present" if Path(root).is_dir() else "missing"


def _checkout_lines(paths_dir: Path, skip: Path | None) -> list[str]:
    """One summary line per paths/<key>/ that has fragments, sorted by key."""
    lines = []
    for path in sorted(p for p in paths_dir.iterdir() if p.is_dir() and p != skip):
        found = fragments(path)
        if not found:
            continue
        count = {kind: sum(p.name.startswith(f"{kind}-") for p in found) for kind in ("decision", "log", "reference", "feedback")}
        tasks = sum(p.name.startswith("task-") for p in found)
        task_summary = f", {tasks} tasks" if tasks else ""
        newest = datetime.fromtimestamp(max(p.stat().st_mtime for p in found), UTC).astimezone().strftime("%Y-%m-%d")
        status = _record_root(path / "worktree.json")[1]
        lines.append(f"- {path.name}: {count['decision']} decisions, {count['log']} logs, {count['reference']} references, "
                     f"{count['feedback']} feedback{task_summary}; newest {newest}; worktree {status}")
    return lines


def print_siblings(store: Path, base_dir: Path) -> None:
    if not base_dir.is_relative_to(store / "repos"):
        return
    lines = _checkout_lines(base_dir.parent, base_dir)
    if lines:
        print("\nSibling worktrees with fragments (not loaded; add with resume --with <key>):")
        print("\n".join(lines))


def print_peek(store: Path, base_dir: Path) -> None:
    """Other clones of the same repository, grouped per clone (FR-2.4 --peek)."""
    if not base_dir.is_relative_to(store / "repos"):
        return
    clone = base_dir.parents[1]
    blocks = []
    for other in sorted(p for p in clone.parent.iterdir() if p.is_dir() and p != clone):
        lines = _checkout_lines(other / "paths", None) if (other / "paths").is_dir() else []
        if lines:
            root, status = _record_root(other / "clone.json")
            blocks += [f"clone {other.name}: root {root}, {status}", *(f"  {line}" for line in lines)]
    if blocks:
        print("\nOther clones with fragments (peek; add with resume --with <clone_id>/<key>):")
        print("\n".join(blocks))


def adopt(base_dir: Path, source: Path) -> None:
    """Move a sibling's fragments into base_dir, suffixing collisions and rewriting links to renamed files (FR-2.9)."""
    moving = fragments(source)
    taken = {p.name for p in (base_dir / "active").iterdir()}
    names = {}
    for path in moving:
        name, n = path.name, 2
        while name in taken:
            name, n = f"{path.stem}-{n}.md", n + 1
        taken.add(name)
        names[path.name] = name
    renamed = {old: new for old, new in names.items() if old != new}
    print(f"[Memoir] Adopted {len(moving)} files from {source.name}.")
    for path in moving:
        lines = path.read_text(encoding=UTF8).splitlines(keepends=True)
        for i, line in enumerate(lines):
            if line.startswith((HDR_SUPERSEDES, "Superseded-By:", "Origin:")):
                lines[i] = FRAGMENT_LINK_RE.sub(lambda m: renamed.get(m.group(), m.group()), line)
        dest = base_dir / "active" / names[path.name]
        # Write before unlinking: a crash leaves a duplicate, never a lost fragment.
        atomic_write(dest, "".join(lines))
        path.unlink()
        print(f"{dest.absolute()}{f' (renamed from {path.name})' if path.name in renamed else ''}")


def check_access(base_dir: Path) -> None:
    """Create the store and probe a write; exit 3 so the caller can ask the user for access."""
    try:
        (base_dir / "active").mkdir(parents=True, exist_ok=True)
        (base_dir / "archive").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=base_dir / "active"):
            pass
    except OSError as e:
        print(f"[Memoir] No write access to {base_dir.absolute()} ({e.strerror or e})", file=sys.stderr)
        sys.exit(3)


def _legacy_candidates(cwd: Path, top: str, base_dir: Path) -> list[Path]:
    root = Path(top).resolve() if top else cwd
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    digest = hashlib.sha256(str(cwd).encode()).hexdigest()[:8]
    candidates = [root / ".agents" / "memoir", root / ".claude" / "memoir", config / "memoir" / "memories" / digest]
    group = None if top else group_of(store_root(), cwd)
    if group:  # fragments stored inside the pin before pins became groups
        candidates.append(group[1] / "paths" / ("__".join(cwd.relative_to(group[0]).parts) or "_root"))
    if top:  # notes written before this folder became a Git repo
        candidates.append(store_root() / "standalone" / scope_id(cwd, cwd))
    if top and base_dir.name == scope_id(root, root):  # external worktree keyed by basename before FR-1.3 hashed it
        old = base_dir.parent / root.name
        record = old / "worktree.json"
        try:
            owner = json.loads(record.read_text(encoding=UTF8))["root"] if record.exists() else str(root)
        except (OSError, ValueError, KeyError, TypeError):
            owner = None
        if owner == str(root):  # never copy in another worktree's notes
            candidates.append(old)
    return candidates


def _legacy_files(root: Path) -> list[Path]:
    return [
        f
        for d in ("active", "archive")
        if (root / d).is_dir()
        for f in (root / d).rglob("*")
        if f.is_file()
    ]


def _is_legacy_file_covered(base_dir: Path, legacy: Path, file_path: Path) -> bool:
    if (base_dir / file_path.relative_to(legacy)).exists():
        return True
    return file_path.parent == legacy / "active" and any((base_dir / "archive").glob(f"[0-9]*-{file_path.name}"))


def migrate_legacy(base_dir: Path) -> None:
    """Copy a v1 store into an empty v2 scope, leaving the original in place (FR-1.7)."""
    cwd = Path.cwd().resolve()
    top = git_output(GIT_REV_PARSE, FLAG_SHOW_TOPLEVEL)
    candidates = _legacy_candidates(cwd, top, base_dir)
    legacy = next((c for c in candidates if (c / "active").is_dir() or (c / "archive").is_dir()), None)
    if legacy is None:
        return
    if any(any((base_dir / d).iterdir()) for d in ("active", "archive")):
        # v2 files change after the copy, so match by name: kept as-is, or an active fragment archived since.
        covered = all(_is_legacy_file_covered(base_dir, legacy, f) for f in _legacy_files(legacy))
        if covered:
            print(f"[Memoir] Legacy store {legacy} is already migrated to {base_dir}; delete {legacy} to silence this.", file=sys.stderr)
        else:
            print(f"[Memoir] Legacy store {legacy} not migrated: {base_dir} already has files.", file=sys.stderr)
        return
    copied = 0
    for d in ("active", "archive"):
        if (legacy / d).is_dir():
            shutil.copytree(legacy / d, base_dir / d, dirs_exist_ok=True)
            copied += sum(1 for p in (legacy / d).rglob("*") if p.is_file())
    print(f"[Memoir] Migrated {copied} files from {legacy} to {base_dir}; delete {legacy} once verified.", file=sys.stderr)


def init_store(base_dir: Path):
    active_dir = base_dir / "active"
    archive_dir = base_dir / "archive"

    print(f"[Memoir] Initialized store at: {base_dir.absolute()}")
    return active_dir, archive_dir


def generate_prompt(base_dir: Path):
    active_dir = base_dir / "active"
    print("SYSTEM CONTEXT INJECTION:")
    print("Your Memoir store is active. You must write all files strictly to this absolute path:")
    print(f"{active_dir.absolute()}")


def _superseded_names(path: Path) -> list[str]:
    names = {
        name
        for line in path.read_text(encoding=UTF8).splitlines()
        if line.startswith(HDR_SUPERSEDES)
        for name in FRAGMENT_LINK_RE.findall(line)
        if name.partition("-")[0] == path.name.partition("-")[0]
    }
    return sorted(names - {path.name})


def _resolve_superseded_holder(name: str, own_scope: Path, scopes: list[Path], superseder: str) -> Path | None:
    own = own_scope / "active" / name
    if own.is_file():
        return own
    holders = [s / "active" / name for s in scopes if (s / "active" / name).is_file()]
    if len(holders) == 1:
        return holders[0]
    if holders:
        print(f"[Memoir] {superseder} supersedes {name}, held by {len(holders)} scopes; skipped.", file=sys.stderr)
    return None


def find_superseded(scopes: list[Path]) -> dict[Path, str]:
    """Active fragments named on another same-kind fragment's `Supersedes:` line, mapped to that decision's name.

    A name resolves in the superseding decision's own scope first, else in the only scope holding it (FR-2.3).
    """
    found: dict[Path, str] = {}
    for scope in scopes:
        for path in fragments(scope):
            if not path.name.startswith(("decision-", "reference-", "feedback-")):
                continue
            for name in _superseded_names(path):
                holder = _resolve_superseded_holder(name, scope, scopes, path.name)
                if holder is not None:
                    found[holder] = path.name
    return dict(sorted(found.items()))


def atomic_write(path: Path, contents: str, *, mode: int | None = None) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding=UTF8, dir=path.parent, delete=False) as tmp:
        temporary = Path(tmp.name)
        try:
            tmp.write(contents)
            tmp.flush()
            if mode is not None:
                os.fchmod(tmp.fileno(), mode)
            os.fsync(tmp.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def add_superseded_by(path: Path, by: str) -> None:
    """Write a `Superseded-By:` back-link right after the `Supersedes:` line, once."""
    lines = path.read_text(encoding=UTF8).splitlines()
    link = f"Superseded-By: {by}"
    if link in lines:
        return
    i = next((k + 1 for k, line in enumerate(lines) if line.startswith(HDR_SUPERSEDES)), len(lines))
    lines.insert(i, link)
    atomic_write(path, "\n".join(lines) + "\n")


def retired_by_age_or_status(path: Path, today: date, max_age: int) -> bool:
    if not path.name.startswith(("task-", "log-")):
        return False
    # Only leading fields carry lifecycle metadata. Examples in the body do not.
    headers = path.read_text(encoding=UTF8).split("\n\n", 1)[0].splitlines()
    key = "Status:" if path.name.startswith("task-") else "Date:"
    values = [line.removeprefix(key).strip() for line in headers if line.startswith(key)]
    if len(values) != 1:
        return False
    value = values[0]
    if key == "Status:":
        return value == "done"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return (today - date.fromisoformat(value)).days > max_age
    except ValueError:
        return False


def archive_selected(args: argparse.Namespace, store: Path, base_dir: Path):
    targets = {base_dir / "active" / f: f for f in args.files}
    links = {}
    if args.retired or args.superseded:
        scopes = members_of(store, base_dir)
        links = find_superseded(scopes)
        targets.update((p, p.name) for p in links)
        if args.retired:
            raw = os.environ.get("MEMOIR_LOG_MAX_AGE_DAYS", "30")
            if not re.fullmatch(r"[0-9]+", raw):
                raise ValueError("MEMOIR_LOG_MAX_AGE_DAYS must be a nonnegative integer")
            today = datetime.now().astimezone().date()
            age = int(raw)
            for scope in scopes:
                targets.update((p, p.name) for p in fragments(scope) if retired_by_age_or_status(p, today, age))
    archive_files([(name, path) for path, name in targets.items()], links)


def archive_files(targets: list[tuple[str, Path]], links: dict[Path, str]):
    """Move each (name, active path) into the archive/ beside it."""
    if not targets:
        print("[Memoir] Archived 0 files.")
        return

    today = datetime.now().astimezone().strftime("%Y%m%d")
    archived_count = 0
    failed = False

    for filename, source_path in targets:
        dest_name = f"{today}-{filename}"
        dest_path = source_path.parent.parent / "archive" / dest_name
        if not ARCHIVABLE_RE.fullmatch(filename):
            print(f"Not an archivable fragment name: {filename}")
            failed = True
        elif not source_path.is_file() or source_path.is_symlink():
            print(f"File not found in active: {filename}")
            failed = True
        elif dest_path.exists() or dest_path.is_symlink():
            print(f"Already archived, not overwriting: {dest_name}")
            failed = True
        else:
            if source_path in links:
                add_superseded_by(source_path, links[source_path])
            shutil.move(source_path, dest_path)
            print(f"Archived: {filename} -> {dest_name}")
            archived_count += 1

    print(f"[Memoir] Archived {archived_count} files.")
    if failed:
        sys.exit(1)


def active_file_sizes(base_dir: Path, scopes: list[Path], extra: list[Path]) -> dict[Path, int]:
    state_file = base_dir / "active" / STATE_FILENAME
    files = [state_file]
    # Other group members' and siblings' state belongs to their own folders (FR-2.4).
    files += sorted(p for s in scopes for p in (s / "active").glob("*.md") if p.name != STATE_FILENAME)
    files += [p for s in dict.fromkeys(extra) for p in fragments(s)]

    sizes = {}
    for path in files:
        try:
            info = path.stat()
        except FileNotFoundError:
            continue  # Another reload may have retired it during the scan.
        if stat.S_ISREG(info.st_mode):
            sizes[path] = info.st_size
    return sizes


def generate_resume(base_dir: Path, scopes: list[Path], extra: list[Path], peek: bool = False):
    files = active_file_sizes(base_dir, scopes, extra)
    generate_prompt(base_dir)
    if not files:
        print("\nNo recorded session found. Start fresh.")
    else:
        print("\nLoad the following files to restore my session state:")
        for idx, filepath in enumerate(files, 1):
            print(f"{idx}. {filepath.absolute()}")
        print("\nBased on the state file, resume the current task.")
    size = sum(files.values())
    hint = "; run /memoir prune" if len(files) > 50 or size > 60 * 1024 else ""
    noun = "file" if len(files) == 1 else "files"
    print(f"Active: {len(files)} {noun}, {size} bytes{hint}")
    print_wiki_lag(store_root(), base_dir)
    print_siblings(store_root(), base_dir)
    if peek:
        print_peek(store_root(), base_dir)


def _orphan_missing_root(record: Path) -> str | None:
    # A linked repo, scope or record could redirect pruning outside the store.
    if record.resolve() != record:
        print(f"[Memoir] Skipping linked metadata: {record}", file=sys.stderr)
        return None
    metadata = json.loads(record.read_text(encoding=UTF8))
    root = metadata.get("root") if isinstance(metadata, dict) else None
    if not isinstance(root, str) or not Path(root).is_absolute():
        raise ValueError(f"Invalid root in {record}")
    try:
        info = Path(root).stat()
    except (FileNotFoundError, NotADirectoryError):
        return root
    return None if stat.S_ISDIR(info.st_mode) else root


def collect_orphans(store: Path, prune: bool) -> None:
    for pattern in ("repos/*/clones/*/clone.json", "pinned/*/workspace.json", "standalone/*/scope.json"):
        for record in sorted(store.glob(pattern)):
            missing = _orphan_missing_root(record)
            if missing is None:
                continue
            print(f"[Memoir] Orphan: {record.parent} (missing directory {missing})")
            if prune:
                shutil.rmtree(record.parent)


def wiki_scope(store: Path, base_dir: Path) -> tuple[Path, list[Path]] | None:
    """Wiki scope root and its fragment directories (FR-2.8)."""
    if base_dir.is_relative_to(store / "repos"):
        repo = base_dir.parents[3]
        return repo, sorted(repo.glob("clones/*/paths/*"))
    group = group_of(store, Path.cwd().resolve())
    return (group[1], members_of(store, base_dir)) if group else None


def wiki_diff(root: Path, dirs: list[Path]):
    state = root / "wiki" / ".ingest-state.json"
    watermark = json.loads(state.read_text(encoding=UTF8)) if state.is_file() else {"fragments": {}}
    seen = watermark.get("fragments") if isinstance(watermark, dict) else None
    if not isinstance(seen, dict) or not all(isinstance(entry, dict) for entry in seen.values()):
        raise ValueError(f"Invalid fragment watermark: {state}")
    missing = set(seen)
    for path in sorted(p for d in dirs for sub in ("active", "archive") for p in (d / sub).glob("*.md")):
        if not re.fullmatch(r"(\d{8}-)?(decision|log|reference|feedback)-[a-z0-9-]+\.md", path.name):
            continue
        rel = os.path.relpath(path, root)
        missing.discard(rel)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        old = seen.get(rel, {}).get("sha256")
        if digest != old:
            yield ("new" if old is None else "changed"), digest, rel
    for rel in sorted(missing):
        yield "missing", "-", rel


def print_wiki_scope(store: Path, base_dir: Path, command: str):
    scope = wiki_scope(store, base_dir)
    if scope is None:
        return
    if command == "scope":
        print(scope[0], *scope[1], sep="\n")
    else:
        for row in wiki_diff(*scope):
            print(*row)


def print_wiki_lag(store: Path, base_dir: Path):
    scope = wiki_scope(store, base_dir)
    if not scope or not (scope[0] / "wiki").is_dir():
        return
    try:
        counts = Counter(kind for kind, _, _ in wiki_diff(*scope))
    except (ValueError, OSError) as error:
        print(f"[Memoir] Cannot read wiki lag: {error}", file=sys.stderr)
        return
    if counts:
        details = ", ".join(f"{counts[k]} {k}" for k in ("new", "changed", "missing") if counts[k])
        noun = "change" if counts.total() == 1 else "changes"
        print(f"Wiki: {counts.total()} pending fragment {noun} ({details}); run /memoir-wiki ingest")


def instruction_lines(lines: list[str]):
    """Yield prose lines so setup ignores block examples inside Markdown fences."""
    fence = ""
    for i, line in enumerate(lines):
        value = line.rstrip("\r\n")
        delimiter = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", value)
        if delimiter:
            marker, rest = delimiter.groups()
            if not fence:
                fence = marker
            elif marker.startswith(fence) and not rest.strip():
                fence = ""
        elif not fence:
            yield i, value
    if fence:
        raise ValueError("Unclosed Markdown fence in project instructions")


def instruction_target(root: Path, target: str | None) -> Path:
    agents, claude = root / AGENTS_MD, root / CLAUDE_MD
    if (target is None or target == claude.name) and claude.is_file() and claude.resolve().parent == root:
        imports = claude.read_bytes().decode(UTF8_SIG).splitlines()
        if any(re.search(r"(?:^|\s)@(?:\./)?AGENTS\.md(?=\s|[.,;:]?(?:\s|$))",
                         re.sub(r"`[^`]*`", "", line)) for _, line in instruction_lines(imports)):
            return agents
    if target:
        return root / target
    if agents.exists() and claude.exists() and agents.resolve() != claude.resolve():
        raise ValueError(f"Both instruction files exist in {root}. Choose {AGENTS_MD} or {CLAUDE_MD}.")
    return claude if claude.exists() and not agents.exists() else agents


def _parse_guard_marker(value: str, line_num: int) -> tuple[str, str] | None:
    if not re.match(r"^\s*<!--\s*memoir(?:-wiki)?:", value):
        return None
    match = re.fullmatch(r"<!-- (memoir(?:-wiki)?):(begin|end) -->", value)
    if not match:
        raise ValueError(f"Malformed or overlapping Memoir guards at line {line_num}")
    return match.groups()


def _scan_instruction_guards(lines: list[str], heading: str) -> tuple[dict[str, tuple[int, int]], list[int]]:
    legacy: list[int] = []
    spans: dict[str, tuple[int, int]] = {}
    opened: tuple[str, int] | None = None
    for i, value in instruction_lines(lines):
        if value == heading and opened is None:
            legacy.append(i)
        marker = _parse_guard_marker(value, i + 1)
        if not marker:
            continue
        owner, side = marker
        if side == "begin" and opened is None and owner not in spans:
            opened = (owner, i)
        elif side == "end" and opened and opened[0] == owner:
            spans[owner] = (opened[1], i)
            opened = None
        else:
            raise ValueError(f"Malformed or overlapping Memoir guards at line {i + 1}")
    if opened:
        raise ValueError("Unclosed Memoir guard in project instructions")
    return spans, legacy


def _resolve_legacy_span(
    lines: list[str],
    legacy: list[int],
    spans: dict[str, tuple[int, int]],
    skill: str,
    expected: list[str],
) -> tuple[int, int]:
    start = legacy[0]
    stop = start + len(expected)
    following = next((line for line in lines[stop:] if line.strip()), "")
    if (
        skill in spans
        or len(legacy) != 1
        or (following and not following.startswith(("#", "<!--")))
        or [line.rstrip("\r\n") for line in lines[start:stop]] != expected
    ):
        raise ValueError(f"Review the existing '{expected[0]}' section before enabling {skill}")
    return start, stop - 1


def guarded_instructions(text: str, skill: str, body: str) -> str:
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if text.partition("\n")[0].endswith("\r") else "\n"
    begin, end = f"<!-- {skill}:begin -->", f"<!-- {skill}:end -->"
    expected = body.splitlines()
    spans, legacy = _scan_instruction_guards(lines, expected[0])

    block = newline.join([begin, *expected, end])
    if legacy:
        spans[skill] = _resolve_legacy_span(lines, legacy, spans, skill, expected)
    if skill in spans:
        start, last = spans[skill]
        ending = lines[last][len(lines[last].rstrip("\r\n")):]
        return "".join(lines[:start]) + block + ending + "".join(lines[last + 1:])
    if text and not text.endswith("\n"):
        text += newline
    if text and not text.endswith(newline * 2):
        text += newline
    return text + block + newline


def project_init(skill: str, target: str | None) -> None:
    import fcntl

    top = git_output(GIT_REV_PARSE, FLAG_SHOW_TOPLEVEL)
    root = Path(top).resolve() if top else Path.cwd()
    if not top and (group := group_of(store_root(), root)):
        root = group[0]
    reference = Path(__file__).resolve().parents[2] / skill / "references" / "always-on.md"
    template = re.search(r"^```markdown\n(.+?)\n```$", reference.read_text(encoding=UTF8), re.M | re.S)
    if not template:
        raise ValueError(f"Missing instruction block in {reference}")
    # Lock the directory so simultaneous inits can atomically replace the same file in either order.
    directory = os.open(root, os.O_RDONLY)
    try:
        fcntl.flock(directory, fcntl.LOCK_EX)
        path = instruction_target(root, target)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"Expected a regular project instruction file at {path}")
        existing = path.exists()
        raw = path.read_bytes() if existing else b""
        text = raw.decode(UTF8_SIG)
        updated = guarded_instructions(text, skill, template[1])
        if updated == text:
            print(f"Already current: {path}")
            return
        if raw.startswith(b"\xef\xbb\xbf"):
            updated = "\ufeff" + updated
        atomic_write(path, updated, mode=stat.S_IMODE(path.stat().st_mode) if existing else None)
        print(f"Installed {skill} project instructions in {path}")
    finally:
        os.close(directory)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Memoir Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the memoir directories")
    setup = subparsers.add_parser("project-init", help="Install one skill's project instructions")
    setup.add_argument("skill", choices=("memoir", "memoir-wiki"))
    setup.add_argument("target", nargs="?", choices=(AGENTS_MD, CLAUDE_MD))

    archive_parser = subparsers.add_parser("archive", help="Move specified files to the archive")
    archive_parser.add_argument("files", nargs="*", help="List of filenames in active/ to archive")
    archive_parser.add_argument("--superseded", action="store_true", help="Archive superseded decisions, references and feedback")

    archive_parser.add_argument("--retired", action="store_true", help="Also archive completed tasks and expired logs")

    subparsers.add_parser("path", help="Print the resolved base directory")
    subparsers.add_parser("scope", help="Print the wiki scope root and the fragment directories it covers")
    subparsers.add_parser("prompt", help="Print the absolute path instruction for LLM injection")

    subparsers.add_parser("wiki-diff", help="List new, changed and missing wiki sources")

    resume_parser = subparsers.add_parser("resume", help="Generate the exact prompt to load active files for the next session")
    resume_parser.add_argument("--with", dest="siblings", action="append", default=[], metavar="KEY",
                               help="Also load a sibling worktree's, or <clone_id>/<key> of another clone's, fragments (repeatable)")
    resume_parser.add_argument("--peek", action="store_true", help="Also list other clones of this repository")

    adopt_parser = subparsers.add_parser("adopt", help="Move a sibling worktree's fragments into this scope")
    adopt_parser.add_argument("key", help="The sibling's paths/<key> folder name")

    for command in ("pin", "unpin"):
        pin_parser = subparsers.add_parser(command, help=f"{command.capitalize()} a workspace root")
        pin_parser.add_argument("directory", nargs="?", default=".", type=Path)

    gc_parser = subparsers.add_parser("gc", help="Report scopes with missing source directories")
    mode = gc_parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only report orphans (default)")
    mode.add_argument("--prune", action="store_true", help="Remove each orphaned scope directory")
    return parser


def _run_store_command(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    store: Path,
    base_dir: Path,
) -> None:
    if args.command == "path":
        print(base_dir.absolute())
    elif args.command in {"scope", "wiki-diff"}:
        print_wiki_scope(store, base_dir, args.command)
    elif args.command == "init":
        init_store(base_dir)
    elif args.command == "archive":
        if not (args.files or args.superseded or args.retired):
            parser.error("archive needs filenames, --superseded or --retired")
        import fcntl

        # Overlapping pin members and simultaneous reloads share archive destinations.
        directory = os.open(store, os.O_RDONLY)
        try:
            fcntl.flock(directory, fcntl.LOCK_EX)
            archive_selected(args, store, base_dir)
        finally:
            os.close(directory)
    elif args.command == "prompt":
        generate_prompt(base_dir)
    elif args.command == "resume":
        extra = [sibling(store, base_dir, key, other_clones=True) for key in args.siblings]
        generate_resume(base_dir, members_of(store, base_dir), extra, args.peek)
    elif args.command == "adopt":
        adopt(base_dir, sibling(store, base_dir, args.key))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "project-init":
        project_init(args.skill, args.target)
        return
    store = store_root()
    if (store / "active").is_dir():
        raise ValueError(f"{store} is a v1 store (has active/); unset or repoint MEMOIR_STORE to a v2 store root.")
    if args.command == "gc":
        collect_orphans(store, args.prune)
        return
    if args.command in {"pin", "unpin"}:
        update_pin(store, args.directory.expanduser().resolve(), args.command == "pin")
        return
    read_only = args.command in {"path", "scope", "wiki-diff"}
    base_dir = resolve_store(store, not read_only)
    if not read_only:
        check_access(base_dir)
        migrate_legacy(base_dir)
    _run_store_command(parser, args, store, base_dir)

if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"[Memoir] No write access to {error.filename or store_root()} ({error.strerror})", file=sys.stderr)
        sys.exit(3)
    except ValueError as error:
        print(f"[Memoir] {error}", file=sys.stderr)
        sys.exit(1)
