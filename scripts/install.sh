#!/usr/bin/env bash
set -eu

repo=BaankeyBihari/memoir-skill
store=${MEMOIR_STORE:-"$HOME/.memoir"}
version=
skills=true
ui=true
while (( $# )); do
    case $1 in
        --skills-only) ui=false ;;
        --ui-only) skills=false ;;
        --store) [[ -n ${2:-} ]] || { echo "--store requires a path" >&2; exit 2; }; store=$2; shift ;;
        --version)
            [[ -n ${2:-} ]] || { echo "--version requires a YYYY.M.N tag" >&2; exit 2; }
            if [[ ! $2 =~ ^[0-9]{4}\.([1-9]|1[0-2])\.[1-9][0-9]*$ ]]; then
                echo "Invalid --version '$2': expected YYYY.M.N (e.g. 2026.11.1, 2027.1.1)" >&2
                exit 2
            fi
            version=$2
            shift
            ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done
if ! "$skills" && ! "$ui"; then
    echo "Choose one installation mode" >&2
    exit 2
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
src=
if [[ -f ${BASH_SOURCE[0]:-} ]]; then
    src=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
fi

if [[ -n $version ]]; then
    release_base="https://github.com/$repo/releases/download/$version"
else
    release_base="https://github.com/$repo/releases/latest/download"
fi

checksums_state=
fetch_checksums() {
    case $checksums_state in
        ok) return 0 ;;
        missing) return 1 ;;
    esac
    if curl -fsSL "$release_base/SHA256SUMS" -o "$tmp/SHA256SUMS" && [[ -s $tmp/SHA256SUMS ]]; then
        checksums_state=ok
        return 0
    fi
    checksums_state=missing
    return 1
}

sha256_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        echo "Missing sha256sum or shasum for checksum verification" >&2
        return 1
    fi
}

verify_checksum() {
    local file=$1
    local asset=$2
    local expected actual
    expected=$(awk -v name="$asset" '$2 == name || $2 == "*" name {print $1; exit}' "$tmp/SHA256SUMS")
    if [[ -z $expected ]]; then
        echo "Missing checksum entry for $asset in SHA256SUMS" >&2
        exit 1
    fi
    actual=$(sha256_file "$file")
    if [[ $actual != "$expected" ]]; then
        echo "Checksum mismatch for $asset (expected $expected, got $actual)" >&2
        exit 1
    fi
}

source_tree() {
    if [[ -z $src || ! -d $src/skills/memoir ]]; then
        curl -fsSL "https://github.com/$repo/archive/refs/heads/main.tar.gz" -o "$tmp/src.tgz"
        tar -xzf "$tmp/src.tgz" -C "$tmp"
        src="$tmp/memoir-skill-main"
    fi
}

configure_cli_store_access() {
    if ! command -v python3 >/dev/null 2>&1; then
        echo "[Memoir] python3 not found; skipping automatic CLI store permission setup for $store" >&2
        return 0
    fi
    python3 - "$store" "$HOME" "$tmp/config-edits.jsonl" <<'PY'
import json
import os
import re
import stat
import sys
import tempfile
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
        return {}
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


def same_claude_path(entry: object, store_real: Path, home_real: Path) -> bool:
    if not isinstance(entry, str):
        return False
    val = entry.strip()
    if not val:
        return False
    if val == "~" or val.startswith("~/"):
        cand = expand_home(val, home_real)
    elif val.startswith("//"):
        cand = Path("/" + val[2:])
    elif val.startswith("/"):
        cand = Path(val)
    else:
        return False
    try:
        return cand.resolve() == store_real
    except OSError:
        return False


def configure_claude(home_real: Path, store_real: Path, edits: list[dict]) -> None:
    claude_dir = home_real / ".claude"
    if not claude_dir.is_dir():
        return
    settings_path = claude_dir / "settings.json"
    file_existed = settings_path.exists()
    data = load_json_dict(settings_path, "Claude Code settings")
    if data is None:
        return

    perms = data.get("permissions")
    if perms is not None and not isinstance(perms, dict):
        print(f"[Memoir] Warning: skipping {settings_path}: 'permissions' must be an object", file=sys.stderr)
        return
    if isinstance(perms, dict):
        add_dirs = perms.get("additionalDirectories")
        if add_dirs is not None and not isinstance(add_dirs, list):
            print(f"[Memoir] Warning: skipping {settings_path}: 'permissions.additionalDirectories' must be an array", file=sys.stderr)
            return

    sandbox = data.get("sandbox")
    if sandbox is not None and not isinstance(sandbox, dict):
        print(f"[Memoir] Warning: skipping {settings_path}: 'sandbox' must be an object", file=sys.stderr)
        return
    if isinstance(sandbox, dict):
        fs_cfg = sandbox.get("filesystem")
        if fs_cfg is not None and not isinstance(fs_cfg, dict):
            print(f"[Memoir] Warning: skipping {settings_path}: 'sandbox.filesystem' must be an object", file=sys.stderr)
            return
        if isinstance(fs_cfg, dict):
            allow_write = fs_cfg.get("allowWrite")
            if allow_write is not None and not isinstance(allow_write, list):
                print(f"[Memoir] Warning: skipping {settings_path}: 'sandbox.filesystem.allowWrite' must be an array", file=sys.stderr)
                return

    if store_real == home_real or store_real.is_relative_to(home_real):
        rel = store_real.relative_to(home_real).as_posix()
        claude_entry = "~" if rel == "." else f"~/{rel}"
    else:
        claude_entry = f"//{store_real.as_posix().lstrip('/')}"

    added_entries: list[dict[str, str]] = []
    perms = data.setdefault("permissions", {})
    add_dirs = perms.setdefault("additionalDirectories", [])
    if not any(same_claude_path(item, store_real, home_real) for item in add_dirs):
        add_dirs.append(claude_entry)
        added_entries.append({"key": "permissions.additionalDirectories", "value": claude_entry})

    sandbox = data.setdefault("sandbox", {})
    fs_cfg = sandbox.setdefault("filesystem", {})
    allow_write = fs_cfg.setdefault("allowWrite", [])
    if not any(same_claude_path(item, store_real, home_real) for item in allow_write):
        allow_write.append(claude_entry)
        added_entries.append({"key": "sandbox.filesystem.allowWrite", "value": claude_entry})

    if added_entries:
        atomic_write_text(settings_path, json.dumps(data, indent=2) + "\n")
        edits.append({
            "cli": "claude",
            "path": settings_path.resolve().as_posix(),
            "created_file": not file_existed,
            "entries": added_entries,
        })
        print(f"[Memoir] Configured Claude Code access in {settings_path} ({claude_entry})")


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


def patch_codex_toml(text: str, data: dict, store_abs: str) -> str | None:
    sb = data.get("sandbox_workspace_write")
    existing_roots: list[str] = []
    if isinstance(sb, dict) and "writable_roots" in sb:
        existing_roots = [str(item) for item in sb["writable_roots"]]

    if sb is None:
        sep = "" if not text or text.endswith("\n") else "\n"
        if text.strip():
            sep += "\n"
        return f"{text}{sep}[sandbox_workspace_write]\nwritable_roots = [{json.dumps(store_abs)}]\n"

    # Find [sandbox_workspace_write] section header if present.
    header_match = re.search(r"(?m)^[ \t]*\[\s*sandbox_workspace_write\s*\][ \t]*(?:#[^\n]*)?$", text)
    if header_match is None:
        # Dotted-key configuration without a [sandbox_workspace_write] table header.
        first_table = re.search(r"(?m)^[ \t]*\[", text)
        section_end = first_table.start() if first_table else len(text)
        section = text[:section_end]
        key_match = re.search(r"(?m)^([ \t]*)sandbox_workspace_write\.writable_roots[ \t]*=[ \t]*", section)
        if key_match is None:
            insertion = f"sandbox_workspace_write.writable_roots = [{json.dumps(store_abs)}]\n"
            prefix = section
            if prefix and not prefix.endswith("\n"):
                prefix += "\n"
            return prefix + insertion + text[section_end:]
        open_idx = section.find("[", key_match.end())
        if open_idx < 0:
            return None
        close_idx = find_matching_bracket(section, open_idx)
        if close_idx < 0:
            return None
        new_arr = format_toml_array(existing_roots + [store_abs], key_match.group(1), "\n" in section[open_idx:close_idx])
        return text[:open_idx] + new_arr + text[close_idx + 1:]

    sec_start = header_match.end()
    need_leading_nl = False
    if sec_start < len(text) and text[sec_start] == "\n":
        sec_start += 1
    elif sec_start == len(text):
        need_leading_nl = True
    next_table = re.search(r"(?m)^[ \t]*\[", text[sec_start:])
    sec_end = sec_start + next_table.start() if next_table else len(text)
    section = text[sec_start:sec_end]

    if "writable_roots" not in sb:
        prefix_nl = "\n" if need_leading_nl else ""
        insertion = f"{prefix_nl}writable_roots = [{json.dumps(store_abs)}]\n"
        return text[:sec_start] + insertion + text[sec_start:]

    key_match = re.search(r"(?m)^([ \t]*)writable_roots[ \t]*=[ \t]*", section)
    if key_match is None:
        return None
    open_idx = section.find("[", key_match.end())
    if open_idx < 0:
        return None
    close_idx = find_matching_bracket(section, open_idx)
    if close_idx < 0:
        return None
    multiline = "\n" in section[open_idx:close_idx]
    new_arr = format_toml_array(existing_roots + [store_abs], key_match.group(1), multiline)
    abs_open = sec_start + open_idx
    abs_close = sec_start + close_idx
    return text[:abs_open] + new_arr + text[abs_close + 1:]


def format_toml_array(items: list[str], indent: str, multiline: bool) -> str:
    if not multiline:
        return "[" + ", ".join(json.dumps(item) for item in items) + "]"
    lines = ["["]
    for item in items:
        lines.append(f"{indent}    {json.dumps(item)},")
    lines.append(f"{indent}]")
    return "\n".join(lines)


def configure_codex(home_real: Path, store_real: Path, edits: list[dict]) -> None:
    codex_dir = home_real / ".codex"
    if not codex_dir.is_dir():
        return
    if tomllib is None:
        print("[Memoir] Warning: tomllib requires Python 3.11+; skipping Codex CLI config", file=sys.stderr)
        return

    config_path = codex_dir / "config.toml"
    file_existed = config_path.exists()
    text = ""
    if file_existed:
        try:
            text = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"[Memoir] Warning: cannot read Codex config ({config_path}): {exc}", file=sys.stderr)
            return

    try:
        data = tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        print(f"[Memoir] Warning: skipping invalid TOML in {config_path}: {exc}", file=sys.stderr)
        return

    sb = data.get("sandbox_workspace_write")
    if sb is not None and not isinstance(sb, dict):
        print(f"[Memoir] Warning: skipping {config_path}: 'sandbox_workspace_write' must be a table", file=sys.stderr)
        return
    if isinstance(sb, dict) and "writable_roots" in sb:
        roots = sb["writable_roots"]
        if not isinstance(roots, list):
            print(f"[Memoir] Warning: skipping {config_path}: 'sandbox_workspace_write.writable_roots' must be an array", file=sys.stderr)
            return
        for item in roots:
            if isinstance(item, str) and item.strip():
                try:
                    if expand_home(item.strip(), home_real).resolve() == store_real:
                        return
                except OSError:
                    continue

    store_abs = store_real.as_posix()
    updated = patch_codex_toml(text, data, store_abs)
    if updated is None:
        print(f"[Memoir] Warning: could not safely update {config_path}", file=sys.stderr)
        return

    try:
        parsed = tomllib.loads(updated)
        roots = parsed.get("sandbox_workspace_write", {}).get("writable_roots", [])
        if store_abs not in roots:
            raise ValueError("missing store_abs after TOML patch")
    except Exception as exc:
        print(f"[Memoir] Warning: skipping {config_path}: patched TOML validation failed ({exc})", file=sys.stderr)
        return

    atomic_write_text(config_path, updated)
    edits.append({
        "cli": "codex",
        "path": config_path.resolve().as_posix(),
        "created_file": not file_existed,
        "entries": [{"key": "sandbox_workspace_write.writable_roots", "value": store_abs}],
    })
    print(f"[Memoir] Configured Codex CLI access in {config_path} ({store_abs})")


def configure_antigravity(home_real: Path, store_real: Path, edits: list[dict]) -> None:
    agy_dir = home_real / ".gemini" / "antigravity-cli"
    if not agy_dir.is_dir():
        return
    settings_path = agy_dir / "settings.json"
    file_existed = settings_path.exists()
    data = load_json_dict(settings_path, "Antigravity CLI settings")
    if data is None:
        return

    perms = data.get("permissions")
    if perms is not None and not isinstance(perms, dict):
        print(f"[Memoir] Warning: skipping {settings_path}: 'permissions' must be an object", file=sys.stderr)
        return
    if isinstance(perms, dict):
        allow = perms.get("allow")
        if allow is not None and not isinstance(allow, list):
            print(f"[Memoir] Warning: skipping {settings_path}: 'permissions.allow' must be an array", file=sys.stderr)
            return

    perms = data.setdefault("permissions", {})
    allow = perms.setdefault("allow", [])
    for rule in allow:
        if not isinstance(rule, str):
            continue
        m = re.fullmatch(r"write_file\((.*)\)", rule.strip())
        if not m:
            continue
        target = m.group(1).strip()
        if target == "*":
            return
        if target:
            try:
                if expand_home(target, home_real).resolve() == store_real:
                    return
            except OSError:
                continue

    entry = f"write_file({store_real.as_posix()})"
    allow.append(entry)
    atomic_write_text(settings_path, json.dumps(data, indent=2) + "\n", default_mode=0o600)
    edits.append({
        "cli": "antigravity",
        "path": settings_path.resolve().as_posix(),
        "created_file": not file_existed,
        "entries": [{"key": "permissions.allow", "value": entry}],
    })
    print(f"[Memoir] Configured Antigravity CLI access in {settings_path} ({entry})")


def configure_pi(home_real: Path, store_real: Path, edits: list[dict]) -> None:
    sandbox_path = home_real / ".pi" / "agent" / "sandbox.json"
    if not sandbox_path.is_file():
        return
    data = load_json_dict(sandbox_path, "Pi sandbox config")
    if data is None:
        return

    allow_write = data.get("allowWrite")
    if allow_write is not None and not isinstance(allow_write, list):
        print(f"[Memoir] Warning: skipping {sandbox_path}: 'allowWrite' must be an array", file=sys.stderr)
        return

    allow_write = data.setdefault("allowWrite", [])
    for item in allow_write:
        if not isinstance(item, str) or not item.strip():
            continue
        try:
            if expand_home(item.strip(), home_real).resolve() == store_real:
                return
        except OSError:
            continue

    store_abs = store_real.as_posix()
    allow_write.append(store_abs)
    atomic_write_text(sandbox_path, json.dumps(data, indent=2) + "\n")
    edits.append({
        "cli": "pi",
        "path": sandbox_path.resolve().as_posix(),
        "created_file": False,
        "entries": [{"key": "allowWrite", "value": store_abs}],
    })
    print(f"[Memoir] Configured Pi sandbox access in {sandbox_path} ({store_abs})")


def main() -> None:
    store_arg, home_arg, edits_out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    home_real = Path(home_arg).resolve()
    store_real = expand_home(store_arg, home_real).resolve()
    edits: list[dict] = []
    configure_claude(home_real, store_real, edits)
    configure_codex(home_real, store_real, edits)
    configure_antigravity(home_real, store_real, edits)
    configure_pi(home_real, store_real, edits)
    if edits:
        with edits_out.open("a", encoding="utf-8") as fh:
            for item in edits:
                fh.write(json.dumps(item) + "\n")


if __name__ == "__main__":
    main()
PY
}

record_missing_parents() {
    local cur=$1
    local home_clean=${HOME%/}
    local out=
    while [[ -n $cur && $cur != "$home_clean" && $cur != / ]]; do
        if [[ -e $cur || -L $cur ]]; then
            break
        fi
        out="${out:+$out$'\n'}$cur"
        [[ $cur == */* ]] || break
        cur=${cur%/*}
        [[ -z $cur ]] && cur=/
    done
    printf '%s' "$out"
}

install_skill_copy() {
    local src_dir=$1
    local dest_parent=$2
    local skill_name=$3
    local allow_legacy_symlink=$4
    local from_release=$5
    local dest="$dest_parent/$skill_name"
    local legacy_target="$HOME/.agents/skills/$skill_name"

    if [[ -L $dest ]]; then
        if [[ $allow_legacy_symlink == true && -e $legacy_target && $dest -ef $legacy_target ]]; then
            rm -f "$dest"
        else
            echo "Existing symlink at $dest; move or remove it before installing" >&2
            exit 1
        fi
    elif [[ -e $dest && ! -d $dest ]]; then
        echo "Existing non-directory at $dest; move it before installing" >&2
        exit 1
    fi

    mkdir -p "$dest_parent"
    local stage
    stage=$(mktemp -d "$dest_parent/.${skill_name}.stage.XXXXXX")
    chmod 755 "$stage"
    if ! cp -R "$src_dir/." "$stage/"; then
        rm -rf "$stage"
        exit 1
    fi
    if [[ $from_release != true ]]; then
        rm -f "$stage/VERSION"  # a checkout has none; keep a stale release stamp from lingering
    fi
    rm -rf "$dest"
    mv "$stage" "$dest"
}

record_manifest() {
    if ! command -v python3 >/dev/null 2>&1; then
        return 0
    fi
    python3 - "$store" "$HOME" "$tmp/artifacts.dat" "$tmp/parents.dat" "$tmp/config-edits.jsonl" <<'PY'
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def expand_home(raw: str, home: Path) -> Path:
    if raw == "~":
        return home
    if raw.startswith("~/"):
        return home / raw[2:]
    return Path(raw)


def canon_path(raw: str | Path) -> Path:
    p = Path(raw)
    missing: list[str] = []
    cur = p
    while not cur.exists() and not cur.is_symlink():
        parent = cur.parent
        if parent == cur:
            break
        missing.append(cur.name)
        cur = parent
    resolved = cur.parent.resolve() / cur.name if cur.is_symlink() else cur.resolve()
    for part in reversed(missing):
        resolved = resolved / part
    return resolved


def normalize_parents(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    canon_list: list[str] = []
    for raw in paths:
        if not raw:
            continue
        p = canon_path(raw).as_posix()
        if p not in seen:
            seen.add(p)
            canon_list.append(p)
    canon_list.sort(key=lambda item: (len(Path(item).parts), len(item)), reverse=True)
    return canon_list


def atomic_write_text(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        try:
            tmp.write(contents)
            tmp.flush()
            os.fsync(tmp.fileno())
            os.replace(tmp_path, path)
        finally:
            tmp_path.unlink(missing_ok=True)


def main() -> None:
    store_arg, home_arg, art_file, par_file, edit_file = sys.argv[1:6]
    home_real = Path(home_arg).resolve()
    store_real = expand_home(store_arg, home_real).resolve()
    manifest_path = store_real / "manifest.json"

    existing: dict = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("schema_version") == 1:
                existing = loaded
            else:
                print(f"[Memoir] Warning: replacing incompatible manifest in {manifest_path}", file=sys.stderr)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[Memoir] Warning: replacing unreadable manifest in {manifest_path}: {exc}", file=sys.stderr)

    art_by_path: dict[str, dict] = {}
    for item in existing.get("artifacts", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        norm_path = canon_path(item["path"]).as_posix()
        rec = dict(item)
        rec["path"] = norm_path
        rec["created_parents"] = normalize_parents([str(p) for p in item.get("created_parents", []) if p])
        art_by_path[norm_path] = rec

    parents_by_art: dict[str, list[str]] = {}
    par_path = Path(par_file)
    if par_path.exists():
        for line in par_path.read_text(encoding="utf-8").splitlines():
            if not line or "\x1f" not in line:
                continue
            art_raw, parent_raw = line.split("\x1f", 1)
            parents_by_art.setdefault(art_raw, []).append(parent_raw)

    art_path = Path(art_file)
    if art_path.exists():
        for line in art_path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            parts = line.split("\x1f")
            if len(parts) != 5:
                continue
            kind, component, name, raw_target, ver = parts
            norm_path = canon_path(raw_target).as_posix()
            prev = art_by_path.get(norm_path, {})
            combined_parents = normalize_parents(
                list(prev.get("created_parents", [])) + parents_by_art.get(raw_target, [])
            )
            rec = {
                "kind": kind,
                "component": component,
                "path": norm_path,
                "version": ver,
                "created_parents": combined_parents,
            }
            if kind == "skill_dir":
                rec["skill"] = name
            else:
                rec["name"] = name
            art_by_path[norm_path] = rec

    edit_by_key: dict[tuple[str, str], dict] = {}
    for item in existing.get("config_edits", []):
        if not isinstance(item, dict):
            continue
        cli = item.get("cli")
        raw_cfg = item.get("path")
        if not isinstance(cli, str) or not isinstance(raw_cfg, str):
            continue
        norm_cfg = canon_path(raw_cfg).as_posix()
        edit_by_key[(cli, norm_cfg)] = {
            "cli": cli,
            "path": norm_cfg,
            "created_file": bool(item.get("created_file", False)),
            "entries": list(item.get("entries", [])),
        }

    edit_path = Path(edit_file)
    if edit_path.exists():
        for line in edit_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            cli = item["cli"]
            norm_cfg = canon_path(item["path"]).as_posix()
            key = (cli, norm_cfg)
            prev = edit_by_key.get(key, {"cli": cli, "path": norm_cfg, "created_file": False, "entries": []})
            seen_entries = {(e.get("key"), e.get("value")) for e in prev["entries"] if isinstance(e, dict)}
            merged_entries = list(prev["entries"])
            for entry in item.get("entries", []):
                ek = (entry.get("key"), entry.get("value"))
                if ek not in seen_entries:
                    seen_entries.add(ek)
                    merged_entries.append(entry)
            edit_by_key[key] = {
                "cli": cli,
                "path": norm_cfg,
                "created_file": bool(prev["created_file"]) or bool(item.get("created_file", False)),
                "entries": merged_entries,
            }

    manifest = {
        "schema_version": 1,
        "store": store_real.as_posix(),
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "artifacts": list(art_by_path.values()),
        "config_edits": list(edit_by_key.values()),
    }
    atomic_write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
PY
    : > "$tmp/artifacts.dat"
    : > "$tmp/parents.dat"
    : > "$tmp/config-edits.jsonl"
}

if ! mkdir -p "$store"/{repos,pinned,standalone} 2>/dev/null; then
    echo "No write access to store directory: $store" >&2
    exit 3
fi
probe_file=$(mktemp "$store/.memoir-write-probe.XXXXXX" 2>/dev/null) || {
    echo "No write access to store directory: $store" >&2
    exit 3
}
rm -f "$probe_file"
installed=()

if "$skills"; then
    skills_root=
    from_release=false
    if [[ -z $version && -n $src && -d $src/skills/memoir && -d $src/skills/memoir-wiki ]]; then
        skills_root="$src/skills"
    elif fetch_checksums && curl -fsSL "$release_base/memoir-skills.tar.gz" -o "$tmp/memoir-skills.tar.gz"; then
        verify_checksum "$tmp/memoir-skills.tar.gz" "memoir-skills.tar.gz"
        mkdir -p "$tmp/skills"
        tar -xzf "$tmp/memoir-skills.tar.gz" -C "$tmp/skills"
        skills_root="$tmp/skills"
        from_release=true
    elif [[ -n $version ]]; then
        echo "Failed to download memoir-skills.tar.gz for release $version" >&2
        exit 1
    else
        source_tree
        skills_root="$src/skills"
    fi

    skill_parents=("$HOME/.agents/skills")
    allow_migration=(false)
    for cli_root in "$HOME/.claude" "$HOME/.codex" "$HOME/.pi/agent" "$HOME/.gemini/antigravity"; do
        if [[ -d $cli_root ]]; then
            skill_parents+=("$cli_root/skills")
            allow_migration+=(true)
        fi
    done

    idx=0
    while (( idx < ${#skill_parents[@]} )); do
        dest_parent=${skill_parents[$idx]}
        migrate=${allow_migration[$idx]}
        missing_parents=$(record_missing_parents "$dest_parent")
        for name in memoir memoir-wiki; do
            install_skill_copy "$skills_root/$name" "$dest_parent" "$name" "$migrate" "$from_release"
            dest="$dest_parent/$name"
            ver=$(cat "$dest/VERSION" 2>/dev/null || echo dev)
            printf '%s\037%s\037%s\037%s\037%s\n' "skill_dir" "skills" "$name" "$dest" "$ver" >> "$tmp/artifacts.dat"
            if [[ -n $missing_parents ]]; then
                while IFS= read -r mp; do
                    if [[ -n $mp ]]; then
                        printf '%s\037%s\n' "$dest" "$mp" >> "$tmp/parents.dat"
                    fi
                done <<< "$missing_parents"
            fi
            if [[ $dest_parent == "$HOME/.agents/skills" ]]; then
                installed+=("$name $ver")
            fi
        done
        idx=$((idx + 1))
    done

    configure_cli_store_access
    record_manifest
fi

if "$ui"; then
    os=$(uname -s | tr '[:upper:]' '[:lower:]')
    case $(uname -m) in
        arm64|aarch64) arch=arm64 ;;
        x86_64|amd64) arch=amd64 ;;
        *) arch=unknown ;;
    esac
    asset="memoir-ui-$os-$arch"
    if fetch_checksums && curl -fsSL "$release_base/$asset" -o "$tmp/memoir-ui"; then
        verify_checksum "$tmp/memoir-ui" "$asset"
    elif [[ -n $version ]]; then
        echo "Failed to download $asset for release $version" >&2
        exit 1
    else
        source_tree
        if [[ ! -f $src/dashboard/go.mod ]] || ! command -v go >/dev/null; then
            echo "No release binary available. Building locally requires Go and dashboard/go.mod." >&2
            exit 1
        fi
        mkdir -p "$tmp/bin"
        (cd "$src/dashboard" && GOBIN="$tmp/bin" go install -ldflags="-s -w -X main.version=${version:-dev}" .)
        mv "$tmp"/bin/* "$tmp/memoir-ui"
    fi
    ui_missing_parents=$(record_missing_parents "$HOME/.local/bin")
    mkdir -p "$HOME/.local/bin"
    install -m 755 "$tmp/memoir-ui" "$HOME/.local/bin/memoir-ui"
    ui_ver=$("$HOME/.local/bin/memoir-ui" --version 2>/dev/null || echo unknown)
    installed+=("memoir-ui $ui_ver")
    printf '%s\037%s\037%s\037%s\037%s\n' "binary" "ui" "memoir-ui" "$HOME/.local/bin/memoir-ui" "$ui_ver" >> "$tmp/artifacts.dat"
    if [[ -n $ui_missing_parents ]]; then
        while IFS= read -r mp; do
            if [[ -n $mp ]]; then
                printf '%s\037%s\n' "$HOME/.local/bin/memoir-ui" "$mp" >> "$tmp/parents.dat"
            fi
        done <<< "$ui_missing_parents"
    fi
    record_manifest
fi

printf -v summary '%s, ' "${installed[@]}"
echo "Installed ${summary%, }"
