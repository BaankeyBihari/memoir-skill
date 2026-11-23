#!/usr/bin/env bash
set -eu

store=${MEMOIR_STORE:-"$HOME/.memoir"}
skills=true
ui=true
dry_run=false
while (( $# )); do
    case $1 in
        --skills-only) ui=false ;;
        --ui-only) skills=false ;;
        --store) [[ -n ${2:-} ]] || { echo "--store requires a path" >&2; exit 2; }; store=$2; shift ;;
        --dry-run) dry_run=true ;;
        -h|--help)
            cat <<'EOF'
Usage: uninstall.sh [--skills-only | --ui-only] [--store <path>] [--dry-run]
EOF
            exit 0
            ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done
if ! "$skills" && ! "$ui"; then
    echo "Choose at most one of --skills-only or --ui-only" >&2
    exit 2
fi
if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required to read and roll back manifest.json" >&2
    exit 1
fi

python3 - "$store" "$HOME" "$skills" "$ui" "$dry_run" <<'PY'
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


def expand_home(raw: str, home: Path) -> Path:
    if raw == "~":
        return home
    if raw.startswith("~/"):
        return home / raw[2:]
    return Path(raw)


def canon_target(raw: str | Path) -> Path:
    p = Path(raw)
    missing: list[str] = []
    cur = p
    while not cur.exists() and not cur.is_symlink():
        parent = cur.parent
        if parent == cur:
            break
        missing.append(cur.name)
        cur = parent
    resolved_base = cur.parent.resolve() / cur.name if cur.is_symlink() else cur.resolve()
    out = resolved_base
    for part in reversed(missing):
        out = out / part
    return out


def is_safe_home_subpath(p: Path, home_real: Path, store_real: Path) -> bool:
    if p == Path("/") or p == home_real or p == store_real:
        return False
    if not p.is_relative_to(home_real):
        return False
    if p.is_relative_to(store_real):
        return False
    return True


def atomic_write_text(path: Path, contents: str, default_mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = default_mode
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            tmp.write(contents)
            tmp.flush()
            os.fsync(tmp.fileno())
            if mode is not None:
                os.chmod(tmp_path, mode)
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)


def load_json_dict(path: Path, label: str) -> dict | None:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[Memoir] Warning: cannot read {label} ({path}): {exc}", file=sys.stderr)
        return None
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[Memoir] Warning: skipping invalid JSON in {label} ({path}): {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        print(f"[Memoir] Warning: skipping {label} ({path}): root JSON value must be an object", file=sys.stderr)
        return None
    return data


def same_path_entry(item: object, targets: set[str], resolved_targets: set[Path], home_real: Path) -> bool:
    if not isinstance(item, str):
        return False
    val = item.strip()
    if val in targets:
        return True
    if val == "~" or val.startswith("~/"):
        cand = expand_home(val, home_real)
    elif val.startswith("//"):
        cand = Path("/" + val[2:])
    elif val.startswith("/"):
        cand = Path(val)
    else:
        return False
    try:
        return cand.resolve() in resolved_targets
    except OSError:
        return False


def find_matching_bracket(text: str, open_idx: int) -> int:
    depth = 0
    i = open_idx
    n = len(text)
    in_basic = False
    in_literal = False
    in_ml_basic = False
    in_ml_literal = False
    in_comment = False

    while i < n:
        ch = text[i]
        if in_comment:
            if ch == "\n":
                in_comment = False
            i += 1
            continue
        if in_ml_basic:
            if text.startswith('"""', i):
                in_ml_basic = False
                i += 3
                continue
            if ch == "\\":
                i += 2
                continue
            i += 1
            continue
        if in_ml_literal:
            if text.startswith("'''", i):
                in_ml_literal = False
                i += 3
                continue
            i += 1
            continue
        if in_basic:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_basic = False
            i += 1
            continue
        if in_literal:
            if ch == "'":
                in_literal = False
            i += 1
            continue

        if ch == "#":
            in_comment = True
            i += 1
            continue
        if text.startswith('"""', i):
            in_ml_basic = True
            i += 3
            continue
        if text.startswith("'''", i):
            in_ml_literal = True
            i += 3
            continue
        if ch == '"':
            in_basic = True
            i += 1
            continue
        if ch == "'":
            in_literal = True
            i += 1
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def format_toml_array(items: list[str], indent: str, multiline: bool) -> str:
    if not multiline:
        return "[" + ", ".join(json.dumps(item) for item in items) + "]"
    lines = ["["]
    for item in items:
        lines.append(f"{indent}    {json.dumps(item)},")
    lines.append(f"{indent}]")
    return "\n".join(lines)


def remove_line_span(text: str, start: int, end: int) -> tuple[str, int, int]:
    """Remove [start:end] plus trailing horizontal space, optional inline comment, and single newline."""
    n = len(text)
    cur = end
    while cur < n and text[cur] in " \t":
        cur += 1
    if cur < n and text[cur] == "#":
        while cur < n and text[cur] != "\n":
            cur += 1
    if cur < n and text[cur] == "\r":
        cur += 1
    if cur < n and text[cur] == "\n":
        cur += 1
    return text[:start] + text[cur:], start, cur - start


def unpatch_codex_toml(text: str, data: dict, target_vals: set[str], resolved_vals: set[Path], home_real: Path) -> str | None:
    sb = data.get("sandbox_workspace_write")
    if sb is None:
        return text
    if not isinstance(sb, dict) or "writable_roots" not in sb:
        return text
    roots = sb["writable_roots"]
    if not isinstance(roots, list):
        return None

    remaining = [
        str(item)
        for item in roots
        if not same_path_entry(item, target_vals, resolved_vals, home_real)
    ]
    if len(remaining) == len(roots):
        return text

    header_match = re.search(r"(?m)^[ \t]*\[\s*sandbox_workspace_write\s*\][ \t]*(?:#[^\n]*)?$", text)
    if header_match is None:
        first_table = re.search(r"(?m)^[ \t]*\[", text)
        section_end = first_table.start() if first_table else len(text)
        section = text[:section_end]
        key_match = re.search(r"(?m)^([ \t]*)sandbox_workspace_write\.writable_roots[ \t]*=[ \t]*", section)
        if key_match is None:
            return None
        open_idx = section.find("[", key_match.end())
        if open_idx < 0:
            return None
        close_idx = find_matching_bracket(section, open_idx)
        if close_idx < 0:
            return None
        if remaining:
            new_arr = format_toml_array(remaining, key_match.group(1), "\n" in section[open_idx:close_idx])
            return text[:open_idx] + new_arr + text[close_idx + 1:]
        updated, _, _ = remove_line_span(text, key_match.start(), close_idx + 1)
        return updated

    sec_start = header_match.end()
    if sec_start < len(text) and text[sec_start] == "\r":
        sec_start += 1
    if sec_start < len(text) and text[sec_start] == "\n":
        sec_start += 1
    next_table = re.search(r"(?m)^[ \t]*\[", text[sec_start:])
    sec_end = sec_start + next_table.start() if next_table else len(text)
    section = text[sec_start:sec_end]

    key_match = re.search(r"(?m)^([ \t]*)writable_roots[ \t]*=[ \t]*", section)
    if key_match is None:
        return None
    open_idx = section.find("[", key_match.end())
    if open_idx < 0:
        return None
    close_idx = find_matching_bracket(section, open_idx)
    if close_idx < 0:
        return None

    abs_open = sec_start + open_idx
    abs_close = sec_start + close_idx
    if remaining:
        new_arr = format_toml_array(remaining, key_match.group(1), "\n" in section[open_idx:close_idx])
        return text[:abs_open] + new_arr + text[abs_close + 1:]

    updated, _, removed_len = remove_line_span(text, sec_start + key_match.start(), abs_close + 1)
    updated_sec_end = sec_end - removed_len
    remaining_body = updated[sec_start:updated_sec_end]
    if remaining_body.strip() == "":
        rm_start = header_match.start()
        while rm_start > 0 and updated[rm_start - 1] == "\n" and (rm_start - 2 < 0 or updated[rm_start - 2] == "\n"):
            rm_start -= 1
        updated = updated[:rm_start] + updated[updated_sec_end:]
        if rm_start == 0:
            updated = updated.lstrip("\r\n")
    return updated


def revert_claude(cfg_path: Path, edit: dict, home_real: Path, dry_run: bool) -> bool:
    if not cfg_path.exists():
        return True
    data = load_json_dict(cfg_path, "Claude Code settings")
    if data is None:
        return False

    entries = edit.get("entries", [])
    add_vals = {str(e.get("value", "")) for e in entries if e.get("key") == "permissions.additionalDirectories" and e.get("value")}
    write_vals = {str(e.get("value", "")) for e in entries if e.get("key") == "sandbox.filesystem.allowWrite" and e.get("value")}

    changed = False
    perms = data.get("permissions")
    if add_vals and isinstance(perms, dict) and isinstance(perms.get("additionalDirectories"), list):
        resolved = set()
        for val in add_vals:
            try:
                p = Path("/" + val[2:]) if val.startswith("//") else expand_home(val, home_real)
                resolved.add(p.resolve())
            except OSError:
                pass
        orig = perms["additionalDirectories"]
        kept = [item for item in orig if not same_path_entry(item, add_vals, resolved, home_real)]
        if len(kept) != len(orig):
            changed = True
            if kept:
                perms["additionalDirectories"] = kept
            else:
                del perms["additionalDirectories"]
                if not perms:
                    del data["permissions"]

    sandbox = data.get("sandbox")
    if write_vals and isinstance(sandbox, dict):
        fs_cfg = sandbox.get("filesystem")
        if isinstance(fs_cfg, dict) and isinstance(fs_cfg.get("allowWrite"), list):
            resolved = set()
            for val in write_vals:
                try:
                    p = Path("/" + val[2:]) if val.startswith("//") else expand_home(val, home_real)
                    resolved.add(p.resolve())
                except OSError:
                    pass
            orig = fs_cfg["allowWrite"]
            kept = [item for item in orig if not same_path_entry(item, write_vals, resolved, home_real)]
            if len(kept) != len(orig):
                changed = True
                if kept:
                    fs_cfg["allowWrite"] = kept
                else:
                    del fs_cfg["allowWrite"]
                    if not fs_cfg:
                        del sandbox["filesystem"]
                    if not sandbox:
                        del data["sandbox"]

    if not changed:
        return True
    if edit.get("created_file") and not data:
        print(f"[Memoir] {'Would remove' if dry_run else 'Removed'} created config {cfg_path}")
        if not dry_run:
            cfg_path.unlink(missing_ok=True)
        return True
    print(f"[Memoir] {'Would revert' if dry_run else 'Reverted'} Claude Code access in {cfg_path}")
    if not dry_run:
        atomic_write_text(cfg_path, json.dumps(data, indent=2) + "\n")
    return True


def revert_codex(cfg_path: Path, edit: dict, home_real: Path, dry_run: bool) -> bool:
    if not cfg_path.exists():
        return True
    if tomllib is None:
        print("[Memoir] Warning: tomllib requires Python 3.11+; skipping Codex CLI rollback", file=sys.stderr)
        return False
    try:
        text = cfg_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[Memoir] Warning: cannot read Codex config ({cfg_path}): {exc}", file=sys.stderr)
        return False
    try:
        data = tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        print(f"[Memoir] Warning: skipping invalid TOML in {cfg_path}: {exc}", file=sys.stderr)
        return False

    vals = {str(e.get("value", "")) for e in edit.get("entries", []) if e.get("key") == "sandbox_workspace_write.writable_roots" and e.get("value")}
    if not vals:
        return True
    resolved: set[Path] = set()
    for val in vals:
        try:
            resolved.add(expand_home(val, home_real).resolve())
        except OSError:
            pass

    updated = unpatch_codex_toml(text, data, vals, resolved, home_real)
    if updated is None:
        print(f"[Memoir] Warning: could not safely revert {cfg_path}", file=sys.stderr)
        return False
    if updated == text:
        return True
    try:
        tomllib.loads(updated)
    except Exception as exc:
        print(f"[Memoir] Warning: skipping {cfg_path}: reverted TOML validation failed ({exc})", file=sys.stderr)
        return False

    if edit.get("created_file") and not updated.strip():
        print(f"[Memoir] {'Would remove' if dry_run else 'Removed'} created config {cfg_path}")
        if not dry_run:
            cfg_path.unlink(missing_ok=True)
        return True
    print(f"[Memoir] {'Would revert' if dry_run else 'Reverted'} Codex CLI access in {cfg_path}")
    if not dry_run:
        atomic_write_text(cfg_path, updated)
    return True


def revert_antigravity(cfg_path: Path, edit: dict, home_real: Path, dry_run: bool) -> bool:
    if not cfg_path.exists():
        return True
    data = load_json_dict(cfg_path, "Antigravity CLI settings")
    if data is None:
        return False

    vals = {str(e.get("value", "")) for e in edit.get("entries", []) if e.get("key") == "permissions.allow" and e.get("value")}
    if not vals:
        return True
    resolved: set[Path] = set()
    for val in vals:
        m = re.fullmatch(r"write_file\((.*)\)", val.strip())
        if m:
            try:
                resolved.add(expand_home(m.group(1).strip(), home_real).resolve())
            except OSError:
                pass

    perms = data.get("permissions")
    if not isinstance(perms, dict) or not isinstance(perms.get("allow"), list):
        return True

    def matches_agy(rule: object) -> bool:
        if not isinstance(rule, str):
            return False
        s = rule.strip()
        if s in vals:
            return True
        m = re.fullmatch(r"write_file\((.*)\)", s)
        if not m:
            return False
        try:
            return expand_home(m.group(1).strip(), home_real).resolve() in resolved
        except OSError:
            return False

    orig = perms["allow"]
    kept = [item for item in orig if not matches_agy(item)]
    if len(kept) == len(orig):
        return True
    if kept:
        perms["allow"] = kept
    else:
        del perms["allow"]
        if not perms:
            del data["permissions"]

    if edit.get("created_file") and not data:
        print(f"[Memoir] {'Would remove' if dry_run else 'Removed'} created config {cfg_path}")
        if not dry_run:
            cfg_path.unlink(missing_ok=True)
        return True
    print(f"[Memoir] {'Would revert' if dry_run else 'Reverted'} Antigravity CLI access in {cfg_path}")
    if not dry_run:
        atomic_write_text(cfg_path, json.dumps(data, indent=2) + "\n", default_mode=0o600)
    return True


def revert_pi(cfg_path: Path, edit: dict, home_real: Path, dry_run: bool) -> bool:
    if not cfg_path.exists():
        return True
    data = load_json_dict(cfg_path, "Pi sandbox config")
    if data is None:
        return False

    vals = {str(e.get("value", "")) for e in edit.get("entries", []) if e.get("key") == "allowWrite" and e.get("value")}
    if not vals or not isinstance(data.get("allowWrite"), list):
        return True
    resolved: set[Path] = set()
    for val in vals:
        try:
            resolved.add(expand_home(val, home_real).resolve())
        except OSError:
            pass

    orig = data["allowWrite"]
    kept = [item for item in orig if not same_path_entry(item, vals, resolved, home_real)]
    if len(kept) == len(orig):
        return True
    if kept:
        data["allowWrite"] = kept
    else:
        del data["allowWrite"]

    print(f"[Memoir] {'Would revert' if dry_run else 'Reverted'} Pi sandbox access in {cfg_path}")
    if not dry_run:
        atomic_write_text(cfg_path, json.dumps(data, indent=2) + "\n")
    return True


def main() -> None:
    store_arg, home_arg, skills_flag, ui_flag, dry_flag = sys.argv[1:6]
    remove_skills = skills_flag == "true"
    remove_ui = ui_flag == "true"
    dry_run = dry_flag == "true"

    home_real = Path(home_arg).resolve()
    store_real = expand_home(store_arg, home_real).resolve()
    manifest_path = store_real / "manifest.json"
    if not manifest_path.exists():
        print(f"Nothing to uninstall (no manifest at {manifest_path})")
        return

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[Memoir] Cannot read manifest {manifest_path}: {exc}", file=sys.stderr)
        sys.exit(1)

    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != 1
        or not isinstance(manifest.get("artifacts", []), list)
        or not isinstance(manifest.get("config_edits", []), list)
    ):
        print(f"[Memoir] Unsupported or invalid manifest format in {manifest_path}", file=sys.stderr)
        sys.exit(1)

    remaining_artifacts: list[dict] = []
    candidate_parents: set[Path] = set()
    planned_removed: set[Path] = set()
    actions = 0

    for art in manifest.get("artifacts", []):
        if not isinstance(art, dict):
            continue
        comp = art.get("component")
        selected = (comp == "skills" and remove_skills) or (comp == "ui" and remove_ui)
        if not selected:
            remaining_artifacts.append(art)
            continue

        raw_path = art.get("path")
        kind = art.get("kind")
        if not isinstance(raw_path, str) or not raw_path:
            continue
        target = canon_target(raw_path)
        valid_kind = (
            (kind == "skill_dir" and target.name in ("memoir", "memoir-wiki") and target.parent.name == "skills")
            or (kind == "binary" and target.name == "memoir-ui")
        )
        if not valid_kind or not is_safe_home_subpath(target, home_real, store_real):
            print(f"[Memoir] Warning: skipping unsafe manifest path {raw_path}", file=sys.stderr)
            remaining_artifacts.append(art)
            continue

        for raw_parent in art.get("created_parents", []):
            if isinstance(raw_parent, str) and raw_parent:
                p = canon_target(raw_parent)
                if is_safe_home_subpath(p, home_real, store_real):
                    candidate_parents.add(p)

        if target.is_symlink():
            print(f"[Memoir] {'Would remove' if dry_run else 'Removed'} symlink {target}")
            planned_removed.add(target)
            if not dry_run:
                target.unlink()
            actions += 1
        elif kind == "skill_dir" and target.is_dir():
            print(f"[Memoir] {'Would remove' if dry_run else 'Removed'} skill {target}")
            planned_removed.add(target)
            if not dry_run:
                shutil.rmtree(target)
            actions += 1
        elif kind == "binary" and target.is_file():
            print(f"[Memoir] {'Would remove' if dry_run else 'Removed'} binary {target}")
            planned_removed.add(target)
            if not dry_run:
                target.unlink()
            actions += 1
        elif target.exists():
            print(f"[Memoir] Warning: skipping unexpected file type at {target}", file=sys.stderr)
            remaining_artifacts.append(art)

    for parent in sorted(candidate_parents, key=lambda p: len(p.parts), reverse=True):
        if parent.is_symlink() or not parent.is_dir():
            continue
        if dry_run:
            try:
                children = set(parent.iterdir())
            except OSError:
                continue
            if children.issubset(planned_removed):
                print(f"[Memoir] Would remove empty directory {parent}")
                planned_removed.add(parent)
        else:
            try:
                parent.rmdir()
                print(f"[Memoir] Removed empty directory {parent}")
            except OSError:
                pass

    remaining_edits: list[dict] = []
    for edit in manifest.get("config_edits", []):
        if not isinstance(edit, dict):
            continue
        if not remove_skills:
            remaining_edits.append(edit)
            continue
        raw_cfg = edit.get("path")
        cli = edit.get("cli")
        if not isinstance(raw_cfg, str) or not raw_cfg:
            continue
        cfg_path = canon_target(raw_cfg)
        if not is_safe_home_subpath(cfg_path, home_real, store_real):
            print(f"[Memoir] Warning: skipping unsafe config path {raw_cfg}", file=sys.stderr)
            remaining_edits.append(edit)
            continue

        ok = True
        if cli == "claude":
            ok = revert_claude(cfg_path, edit, home_real, dry_run)
        elif cli == "codex":
            ok = revert_codex(cfg_path, edit, home_real, dry_run)
        elif cli == "antigravity":
            ok = revert_antigravity(cfg_path, edit, home_real, dry_run)
        elif cli == "pi":
            ok = revert_pi(cfg_path, edit, home_real, dry_run)
        if not ok:
            remaining_edits.append(edit)
        else:
            actions += 1

    if not dry_run:
        if remaining_artifacts or remaining_edits:
            updated_manifest = {
                "schema_version": 1,
                "store": store_real.as_posix(),
                "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "artifacts": remaining_artifacts,
                "config_edits": remaining_edits,
            }
            atomic_write_text(manifest_path, json.dumps(updated_manifest, indent=2) + "\n")
        else:
            manifest_path.unlink(missing_ok=True)
    else:
        if remaining_artifacts or remaining_edits:
            print(f"[Memoir] Would update manifest {manifest_path}")
        else:
            print(f"[Memoir] Would remove manifest {manifest_path}")

    prefix = "Dry run complete" if dry_run else f"Uninstall complete ({actions} items processed)"
    print(f"{prefix}; Memoir store data preserved in {store_real}")


if __name__ == "__main__":
    main()
PY
