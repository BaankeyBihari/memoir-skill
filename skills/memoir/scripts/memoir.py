#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

"""
Memoir Helper CLI
Manages directory resolution, initialization, and archiving for the Memoir skill.
"""

import os
import re
import sys
import shutil
import hashlib
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

ARCHIVABLE_RE = re.compile(r"^(decision|log|reference|feedback)-[a-z0-9]+(-[a-z0-9]+)*\.md$")
SUPERSEDED_RE = re.compile(r"decision-[a-z0-9]+(?:-[a-z0-9]+)*\.md")

def get_git_root():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], 
            capture_output=True, text=True, check=True
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

def resolve_store():
    # 1. Explicit Override
    memoir_store = os.environ.get("MEMOIR_STORE")
    if memoir_store:
        return Path(memoir_store).expanduser()

    # 2. Git Workspace
    git_root = get_git_root()
    if git_root:
        return git_root / ".agents" / "memoir"

    # 3. Non-Git Local / Global Fallback
    cwd = Path.cwd()
    project_slug = hashlib.sha256(str(cwd).encode()).hexdigest()[:8]
    
    use_global = os.environ.get("MEMOIR_USE_GLOBAL", "false").lower() == "true"
    if use_global:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return config_home / "memoir" / "memories" / project_slug

    # 4. Default to CWD
    return cwd / ".agents" / "memoir"

def init_store(base_dir: Path):
    active_dir = base_dir / "active"
    archive_dir = base_dir / "archive"
    
    active_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Memoir] Initialized store at: {base_dir.absolute()}")
    return active_dir, archive_dir

def ensure_gitignore_hint(base_dir: Path) -> None:
    """Keep the default Git-root store out of commits by adding it to the repository .gitignore."""
    git_root = get_git_root()
    if git_root is None or base_dir != git_root / ".agents" / "memoir":
        return

    hint = ".agents/memoir/"
    gitignore = git_root / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    if hint in existing or ".agents/" in existing:
        return
    with gitignore.open("a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(hint + "\n")

def generate_prompt(base_dir: Path):
    active_dir = base_dir / "active"
    print(f"SYSTEM CONTEXT INJECTION:")
    print(f"Your Memoir store is active. You must write all files strictly to this absolute path:")
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

def add_superseded_by(path: Path, by: str) -> None:
    """Write a `Superseded-By:` back-link right after the `Supersedes:` line, once."""
    lines = path.read_text().splitlines()
    link = f"Superseded-By: {by}"
    if link in lines:
        return
    i = next((k + 1 for k, line in enumerate(lines) if line.startswith("Supersedes:")), len(lines))
    lines.insert(i, link)
    path.write_text("\n".join(lines) + "\n")

def archive_files(base_dir: Path, target_files: list[str]):
    active_dir = base_dir / "active"
    archive_dir = base_dir / "archive"

    if not target_files:
        print("[Memoir] Archived 0 files.")
        return

    if not active_dir.exists():
        print("[Memoir] Error: Active directory not found. Run init first.")
        sys.exit(1)

    today = datetime.now().strftime("%Y%m%d")
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

    args = parser.parse_args()
    base_dir = resolve_store()
    if args.command != "path":
        ensure_gitignore_hint(base_dir)

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
    main()