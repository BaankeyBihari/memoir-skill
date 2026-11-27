#!/usr/bin/env bash
# Build the skills archive from the repository root. A release tag stamps the packaged copies.
set -euo pipefail
out=${1:?missing output directory}
src=skills
if (( $# == 2 )); then
    tag=$2
    [[ $tag =~ ^[0-9]{4}\.([1-9]|1[0-2])\.[1-9][0-9]*$ ]] || { echo "Invalid release tag: $tag" >&2; exit 1; }
    src=$(mktemp -d)
    trap 'rm -rf "$src"' EXIT
    for skill in memoir memoir-wiki; do
        cp -R "skills/$skill" "$src/"
        awk -v tag="$tag" '{ print } NR == 1 { print "metadata:"; printf "  version: \"%s\"\n", tag }' \
            "skills/$skill/SKILL.md" > "$src/$skill/SKILL.md"
        printf '%s\n' "$tag" > "$src/$skill/VERSION"
    done
fi
mkdir -p "$out"
tar -czf "$out/memoir-skills.tar.gz" --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' -C "$src" memoir memoir-wiki
