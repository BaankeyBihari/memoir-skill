#!/usr/bin/env bash
# Print the next YYYY.M.N release tag (SRD FR-6.2). Optional arg: YYYY.M prefix, default current UTC month.
set -euo pipefail
prefix=${1:-$(date -u +%Y).$((10#$(date -u +%m)))}
last=$(git tag -l "$prefix.*" | sed -nE "s/^${prefix//./\\.}\\.([1-9][0-9]*)$/\\1/p" | sort -n | tail -1)
echo "$prefix.$((${last:-0} + 1))"
