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
            [[ -n ${2:-} ]] || { echo "--version requires a YYYY.MM.N tag" >&2; exit 2; }
            if [[ ! $2 =~ ^[0-9]{4}\.(0[1-9]|1[0-2])\.[1-9][0-9]*$ ]]; then
                echo "Invalid --version '$2': expected YYYY.MM.N (e.g. 2026.11.1)" >&2
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

mkdir -p "$store"/{repos,pinned,standalone}
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
