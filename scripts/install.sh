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
    python3 - "$store" "$HOME" <<'PY'
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


def configure_claude(home_real: Path, store_real: Path) -> None:
    claude_dir = home_real / ".claude"
    if not claude_dir.is_dir():
        return
    settings_path = claude_dir / "settings.json"
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

    changed = False
    perms = data.setdefault("permissions", {})
    add_dirs = perms.setdefault("additionalDirectories", [])
    if not any(same_claude_path(item, store_real, home_real) for item in add_dirs):
        add_dirs.append(claude_entry)
        changed = True

    sandbox = data.setdefault("sandbox", {})
    fs_cfg = sandbox.setdefault("filesystem", {})
    allow_write = fs_cfg.setdefault("allowWrite", [])
    if not any(same_claude_path(item, store_real, home_real) for item in allow_write):
        allow_write.append(claude_entry)
        changed = True

    if changed:
        atomic_write_text(settings_path, json.dumps(data, indent=2) + "\n")
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


def configure_codex(home_real: Path, store_real: Path) -> None:
    codex_dir = home_real / ".codex"
    if not codex_dir.is_dir():
        return
    if tomllib is None:
        print("[Memoir] Warning: tomllib requires Python 3.11+; skipping Codex CLI config", file=sys.stderr)
        return

    config_path = codex_dir / "config.toml"
    text = ""
    if config_path.exists():
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
    print(f"[Memoir] Configured Codex CLI access in {config_path} ({store_abs})")


def configure_antigravity(home_real: Path, store_real: Path) -> None:
    agy_dir = home_real / ".gemini" / "antigravity-cli"
    if not agy_dir.is_dir():
        return
    settings_path = agy_dir / "settings.json"
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
    print(f"[Memoir] Configured Antigravity CLI access in {settings_path} ({entry})")


def configure_pi(home_real: Path, store_real: Path) -> None:
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
    print(f"[Memoir] Configured Pi sandbox access in {sandbox_path} ({store_abs})")


def main() -> None:
    store_arg, home_arg = sys.argv[1], sys.argv[2]
    home_real = Path(home_arg).resolve()
    store_real = expand_home(store_arg, home_real).resolve()
    configure_claude(home_real, store_real)
    configure_codex(home_real, store_real)
    configure_antigravity(home_real, store_real)
    configure_pi(home_real, store_real)


if __name__ == "__main__":
    main()
PY
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

if "$skills"; then
    skills_root=
    if [[ -z $version && -n $src && -d $src/skills/memoir && -d $src/skills/memoir-wiki ]]; then
        skills_root="$src/skills"
    elif fetch_checksums && curl -fsSL "$release_base/memoir-skills.tar.gz" -o "$tmp/memoir-skills.tar.gz"; then
        verify_checksum "$tmp/memoir-skills.tar.gz" "memoir-skills.tar.gz"
        mkdir -p "$tmp/skills"
        tar -xzf "$tmp/memoir-skills.tar.gz" -C "$tmp/skills"
        skills_root="$tmp/skills"
    elif [[ -n $version ]]; then
        echo "Failed to download memoir-skills.tar.gz for release $version" >&2
        exit 1
    else
        source_tree
        skills_root="$src/skills"
    fi

    mkdir -p "$HOME/.agents/skills"
    for name in memoir memoir-wiki; do
        dest="$HOME/.agents/skills/$name"
        if [[ -L $dest ]]; then
            echo "Existing symlink at $dest; choose a directory for the installed copy" >&2
            exit 1
        fi
        mkdir -p "$dest"
        cp -R "$skills_root/$name/." "$dest/"
        for dir in "$HOME"/{.claude/skills,.codex/skills,.pi/agent/skills,.gemini/antigravity/skills}; do
            [[ -d $dir ]] || continue
            link="$dir/$name"
            [[ $link -ef $dest ]] && continue
            if [[ -e $link && ! -L $link ]]; then
                echo "Existing skill at $link; move it before installing" >&2
                exit 1
            fi
            ln -snf "$dest" "$link"
        done
    done
    configure_cli_store_access
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
    mkdir -p "$HOME/.local/bin"
    install -m 755 "$tmp/memoir-ui" "$HOME/.local/bin/memoir-ui"
fi
