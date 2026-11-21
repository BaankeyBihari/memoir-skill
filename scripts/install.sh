#!/usr/bin/env bash
set -eu

repo=BaankeyBihari/memoir-skill
store=${MEMOIR_STORE:-"$HOME/.memoir"}
skills=true
ui=true
while (( $# )); do
    case $1 in
        --skills-only) ui=false ;;
        --ui-only) skills=false ;;
        --store) [[ -n ${2:-} ]] || { echo "--store requires a path" >&2; exit 2; }; store=$2; shift ;;
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
source_tree() {
    if [[ -z $src || ! -d $src/skills/memoir ]]; then
        curl -fsSL "https://github.com/$repo/archive/refs/heads/main.tar.gz" -o "$tmp/src.tgz"
        tar -xzf "$tmp/src.tgz" -C "$tmp"
        src="$tmp/memoir-skill-main"
    fi
}

mkdir -p "$store"/{repos,pinned,standalone}
if "$skills"; then
    source_tree
    mkdir -p "$HOME/.agents/skills"
    for name in memoir memoir-wiki; do
        dest="$HOME/.agents/skills/$name"
        if [[ -L $dest ]]; then
            echo "Existing symlink at $dest; choose a directory for the installed copy" >&2
            exit 1
        fi
        mkdir -p "$dest"
        cp -R "$src/skills/$name/." "$dest/"
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
    if ! curl -fsSL "https://github.com/$repo/releases/latest/download/$asset" -o "$tmp/memoir-ui"; then
        source_tree
        if [[ ! -f $src/dashboard/go.mod ]] || ! command -v go >/dev/null; then
            echo "No release binary available. Building locally requires Go and dashboard/go.mod." >&2
            exit 1
        fi
        mkdir -p "$tmp/bin"
        (cd "$src/dashboard" && GOBIN="$tmp/bin" go install .)
        mv "$tmp"/bin/* "$tmp/memoir-ui"
    fi
    mkdir -p "$HOME/.local/bin"
    install -m 755 "$tmp/memoir-ui" "$HOME/.local/bin/memoir-ui"
fi
