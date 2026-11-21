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


def resolve_store(store: Path, record: bool) -> Path:
    top = git_output("rev-parse", "--show-toplevel")
    if not top:
        cwd = Path.cwd().resolve()
        matches = [pin for pin in pinned_roots(store) if cwd.is_relative_to(pin)]
        if not matches:
            return store / "standalone" / scope_id(cwd, cwd)
        root = max(matches, key=lambda pin: len(pin.parts))
        workspace = store / "pinned" / scope_id(root, root)
        if record:
            record_scope(workspace / "workspace.json", root)
        key = "__".join(cwd.relative_to(root).parts) or "_root"
        return workspace / "paths" / key
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

def find_superseded(base_dir: Path) -> dict[str, str]:
    """Decision files named on a `Supersedes:` line of another active decision, mapped to that decision."""
    active_dir = base_dir / "active"
    names = {}
    for path in sorted(active_dir.glob("decision-*.md")):
        for line in path.read_text().splitlines():
            if line.startswith("Supersedes:"):
                for name in set(SUPERSEDED_RE.findall(line)) - {path.name}:
                    names[name] = path.name
    return {n: by for n, by in sorted(names.items()) if (active_dir / n).is_file()}

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

def archive_files(base_dir: Path, target_files: list[str]):
    active_dir = base_dir / "active"
    archive_dir = base_dir / "archive"

    if not target_files:
        print("[Memoir] Archived 0 files.")
        return

    if not active_dir.exists():
        print("[Memoir] Error: Active directory not found. Run init first.")
        sys.exit(1)

    today = datetime.now().astimezone().strftime("%Y%m%d")
    archived_count = 0
    failed = False

    for filename in target_files:
        source_path = active_dir / filename
        dest_name = f"{today}-{filename}"
        dest_path = archive_dir / dest_name
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

def generate_resume(base_dir: Path):
    active_dir = base_dir / "active"
    state_file = active_dir / "state-current.md"
    files = [state_file] if state_file.exists() else []
    files += sorted(p for p in active_dir.glob("*.md") if p != state_file)

    generate_prompt(base_dir)
    if not files:
        print("\nNo recorded session found. Start fresh.")
        return

    print("\nLoad the following files to restore my session state:")
    for idx, filepath in enumerate(files, 1):
        print(f"{idx}. {filepath.absolute()}")
    print("\nBased on the state file, resume the current task.")

def collect_orphans(store: Path, prune: bool) -> None:
    for pattern in ("repos/*/clones/*/clone.json", "pinned/*/workspace.json"):
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


def main():
    parser = argparse.ArgumentParser(description="Memoir Management CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the memoir directories")
    
    archive_parser = subparsers.add_parser("archive", help="Move specified files to the archive")
    archive_parser.add_argument("files", nargs="*", help="List of filenames in active/ to archive")
    archive_parser.add_argument("--superseded", action="store_true", help="Archive every decision named in an active decision's Supersedes: line")

    subparsers.add_parser("path", help="Print the resolved base directory")
    
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
    if args.command == "gc":
        collect_orphans(store_root(), args.prune)
        return
    if args.command in {"pin", "unpin"}:
        update_pin(store_root(), args.directory.expanduser().resolve(), args.command == "pin")
        return
    base_dir = resolve_store(store_root(), args.command != "path")
    if args.command != "path":
        check_access(base_dir)

    if args.command == "path":
        print(base_dir.absolute())
    elif args.command == "init":
        init_store(base_dir)
    elif args.command == "archive":
        if not args.files and not args.superseded:
            parser.error("archive needs filenames or --superseded")
        superseded = find_superseded(base_dir) if args.superseded else {}
        # Back-link the active copy before the move: a crash leaves a duplicate, never a lost fragment.
        for name, by in superseded.items():
            add_superseded_by(base_dir / "active" / name, by)
        archive_files(base_dir, args.files + list(superseded))
    elif args.command == "prompt":
        generate_prompt(base_dir)
    elif args.command == "resume":
        generate_resume(base_dir)

if __name__ == "__main__":
    try:
        main()
    except OSError as error:
        print(f"[Memoir] No write access to {error.filename or store_root()} ({error.strerror})", file=sys.stderr)
        sys.exit(3)
    except ValueError as error:
        print(f"[Memoir] {error}", file=sys.stderr)
        sys.exit(1)
