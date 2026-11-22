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
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ARCHIVABLE_RE = re.compile(r"^(decision|log|reference|feedback)-[a-z0-9]+(-[a-z0-9]+)*\.md$")
SUPERSEDED_RE = re.compile(r"decision-[a-z0-9]+(?:-[a-z0-9]+)*\.md")

def store_root() -> Path:
    return Path(os.environ.get("MEMOIR_STORE") or "~/.memoir").expanduser().resolve()


def scope_id(root: Path, identity: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "root"
    digest = hashlib.sha256(str(identity).encode()).hexdigest()[:8]
    return f"{slug}--{digest}"


def git_output(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).rstrip("\n")
    except (subprocess.CalledProcessError, FileNotFoundError):
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
    data = {"root": str(root), "last_seen": datetime.now(timezone.utc).isoformat()}
    atomic_write(record, json.dumps(data) + "\n")


def pinned_roots(store: Path) -> list[Path]:
    try:
        pins = json.loads((store / "pinned.json").read_text(encoding="utf-8"))
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
            folder = Path(json.loads(record.read_text(encoding="utf-8"))["root"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if (group_of(store, folder, pins) or (None,))[0] == group[0]:
            members.add(record.parent)
    return sorted(members)


def resolve_store(store: Path, record: bool) -> Path:
    top = git_output("rev-parse", "--show-toplevel")
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
    common_path = git_output("rev-parse", "--git-common-dir")
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
        key = toplevel.name
    return clone / "paths" / key


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

def migrate_legacy(base_dir: Path) -> None:
    """Copy a v1 store into an empty v2 scope, leaving the original in place (FR-1.7)."""
    cwd = Path.cwd().resolve()
    top = git_output("rev-parse", "--show-toplevel")
    root = Path(top).resolve() if top else cwd
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    digest = hashlib.sha256(str(cwd).encode()).hexdigest()[:8]
    candidates = [root / ".agents" / "memoir", root / ".claude" / "memoir", config / "memoir" / "memories" / digest]
    group = None if top else group_of(store_root(), cwd)
    if group:  # fragments stored inside the pin before pins became groups
        candidates.append(group[1] / "paths" / ("__".join(cwd.relative_to(group[0]).parts) or "_root"))
    if top:  # notes written before this folder became a Git repo
        candidates.append(store_root() / "standalone" / scope_id(cwd, cwd))
    legacy = next((c for c in candidates if (c / "active").is_dir() or (c / "archive").is_dir()), None)
    if legacy is None:
        return
    if any(any((base_dir / d).iterdir()) for d in ("active", "archive")):
        # v2 files change after the copy, so match by name: kept as-is, or an active fragment archived since.
        covered = all(
            (base_dir / f.relative_to(legacy)).exists()
            or (f.parent == legacy / "active" and any((base_dir / "archive").glob(f"[0-9]*-{f.name}")))
            for d in ("active", "archive") if (legacy / d).is_dir()
            for f in (legacy / d).rglob("*") if f.is_file()
        )
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

def find_superseded(scopes: list[Path]) -> dict[Path, str]:
    """Active decisions named on another active decision's `Supersedes:` line, mapped to that decision's name.

    A name resolves in the superseding decision's own scope first, else in the only scope holding it (FR-2.3).
    """
    found: dict[Path, str] = {}
    for scope in scopes:
        for path in sorted((scope / "active").glob("decision-*.md")):
            for line in path.read_text().splitlines():
                if not line.startswith("Supersedes:"):
                    continue
                for name in sorted(set(SUPERSEDED_RE.findall(line)) - {path.name}):
                    own = scope / "active" / name
                    holders = [own] if own.is_file() else [s / "active" / name for s in scopes if (s / "active" / name).is_file()]
                    if len(holders) == 1:
                        found[holders[0]] = path.name
                    elif holders:
                        print(f"[Memoir] {path.name} supersedes {name}, held by {len(holders)} scopes; skipped.", file=sys.stderr)
    return dict(sorted(found.items()))

def atomic_write(path: Path, contents: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        temporary = Path(tmp.name)
        try:
            tmp.write(contents)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def add_superseded_by(path: Path, by: str) -> None:
    """Write a `Superseded-By:` back-link right after the `Supersedes:` line, once."""
    lines = path.read_text().splitlines()
    link = f"Superseded-By: {by}"
    if link in lines:
        return
    i = next((k + 1 for k, line in enumerate(lines) if line.startswith("Supersedes:")), len(lines))
    lines.insert(i, link)
    atomic_write(path, "\n".join(lines) + "\n")

def archive_files(targets: list[tuple[str, Path]]):
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
        if not ARCHIVABLE_RE.match(filename):
            print(f"Not an archivable fragment name: {filename}")
            failed = True
        elif not source_path.exists():
            print(f"File not found in active: {filename}")
            failed = True
        elif dest_path.exists():
            print(f"Already archived, not overwriting: {dest_name}")
            failed = True
        else:
            shutil.move(source_path, dest_path)
            print(f"Archived: {filename} -> {dest_name}")
            archived_count += 1

    print(f"[Memoir] Archived {archived_count} files.")
    if failed:
        sys.exit(1)

def generate_resume(base_dir: Path, scopes: list[Path]):
    state_file = base_dir / "active" / "state-current.md"
    files = [state_file] if state_file.exists() else []
    # Other group members' state belongs to their own folders (FR-2.4).
    files += sorted(p for s in scopes for p in (s / "active").glob("*.md") if p.name != "state-current.md")

    generate_prompt(base_dir)
    if not files:
        print("\nNo recorded session found. Start fresh.")
        return

    print("\nLoad the following files to restore my session state:")
    for idx, filepath in enumerate(files, 1):
        print(f"{idx}. {filepath.absolute()}")
    print("\nBased on the state file, resume the current task.")

def collect_orphans(store: Path, prune: bool) -> None:
    for pattern in ("repos/*/clones/*/clone.json", "pinned/*/workspace.json", "standalone/*/scope.json"):
        for record in sorted(store.glob(pattern)):
            # A linked repo, scope or record could redirect pruning outside the store.
            if record.resolve() != record:
                print(f"[Memoir] Skipping linked metadata: {record}", file=sys.stderr)
                continue
            metadata = json.loads(record.read_text(encoding="utf-8"))
            root = metadata.get("root") if isinstance(metadata, dict) else None
            if not isinstance(root, str) or not Path(root).is_absolute():
                raise ValueError(f"Invalid root in {record}")
            try:
                info = Path(root).stat()
            except (FileNotFoundError, NotADirectoryError):
                pass
            else:
                if stat.S_ISDIR(info.st_mode):
                    continue
            print(f"[Memoir] Orphan: {record.parent} (missing directory {root})")
            if prune:
                shutil.rmtree(record.parent)


def print_scope(store: Path, base_dir: Path) -> None:
    """Wiki scope root, then each fragment directory it compiles (FR-2.8)."""
    if base_dir.is_relative_to(store / "repos"):
        repo = base_dir.parents[3]
        print(repo)
        for path in sorted(repo.glob("clones/*/paths/*")):
            print(path)
        return
    group = group_of(store, Path.cwd().resolve())
    if group:
        print(group[1])
        for scope in members_of(store, base_dir):
            print(scope)


def main():
    parser = argparse.ArgumentParser(description="Memoir Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the memoir directories")
    
    archive_parser = subparsers.add_parser("archive", help="Move specified files to the archive")
    archive_parser.add_argument("files", nargs="*", help="List of filenames in active/ to archive")
    archive_parser.add_argument("--superseded", action="store_true", help="Archive every decision named in an active decision's Supersedes: line")

    subparsers.add_parser("path", help="Print the resolved base directory")

    subparsers.add_parser("scope", help="Print the wiki scope root and the fragment directories it covers")
    
    subparsers.add_parser("prompt", help="Print the absolute path instruction for LLM injection")
    
    subparsers.add_parser("resume", help="Generate the exact prompt to load active files for the next session")

    for command in ("pin", "unpin"):
        pin_parser = subparsers.add_parser(command, help=f"{command.capitalize()} a workspace root")
        pin_parser.add_argument("directory", nargs="?", default=".", type=Path)

    gc_parser = subparsers.add_parser("gc", help="Report scopes with missing source directories")
    mode = gc_parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Only report orphans (default)")
    mode.add_argument("--prune", action="store_true", help="Remove each orphaned scope directory")

    args = parser.parse_args()
    if (store_root() / "active").is_dir():
        raise ValueError(f"{store_root()} is a v1 store (has active/); unset or repoint MEMOIR_STORE to a v2 store root.")
    if args.command == "gc":
        collect_orphans(store_root(), args.prune)
        return
    if args.command in {"pin", "unpin"}:
        update_pin(store_root(), args.directory.expanduser().resolve(), args.command == "pin")
        return
    read_only = args.command in {"path", "scope"}
    base_dir = resolve_store(store_root(), not read_only)
    if not read_only:
        check_access(base_dir)
        migrate_legacy(base_dir)

    if args.command == "path":
        print(base_dir.absolute())
    elif args.command == "scope":
        print_scope(store_root(), base_dir)
    elif args.command == "init":
        init_store(base_dir)
    elif args.command == "archive":
        if not args.files and not args.superseded:
            parser.error("archive needs filenames or --superseded")
        superseded = find_superseded(members_of(store_root(), base_dir)) if args.superseded else {}
        # Back-link the active copy before the move: a crash leaves a duplicate, never a lost fragment.
        for path, by in superseded.items():
            add_superseded_by(path, by)
        targets = [(f, base_dir / "active" / f) for f in args.files] + [(p.name, p) for p in superseded]
        archive_files(targets)
    elif args.command == "prompt":
        generate_prompt(base_dir)
    elif args.command == "resume":
        generate_resume(base_dir, members_of(store_root(), base_dir))

if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"[Memoir] No write access to {error.filename or store_root()} ({error.strerror})", file=sys.stderr)
        sys.exit(3)
    except ValueError as error:
        print(f"[Memoir] {error}", file=sys.stderr)
        sys.exit(1)
