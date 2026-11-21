# AGENTS.md

Memoir v2.0 is a monorepo composed of two agent skills (`skills/memoir` and `skills/memoir-wiki`) and a single-binary Go web dashboard (`dashboard/`), all operating on a centralized local store under `~/.memoir` (`$MEMOIR_STORE`).

## Layout

- `system_requirements_document_memoir_skill.md`: the SRD, the source of truth for behavior (FR/NFR numbers).
- `SPEC.md`: canonical `~/.memoir` filesystem layout, scope routing, JSON records, and fragment/wikilink rules.
- `skills/memoir/`: session compaction skill (`SKILL.md`, `references/always-on.md`, `scripts/memoir.py` CLI).
- `skills/memoir-wiki/`: cumulative Markdown knowledge compiler skill (`SKILL.md`, `references/schema.md`).
- `dashboard/`: zero-dependency single-binary Go web browser (`memoir-ui`) with `embed.FS` and `fsnotify` SSE live reload.
- `scripts/install.sh`: unified installer for both skills and `memoir-ui`.
- `test_memoir.py`: self-check for `memoir.py` and `README.md` / `SKILL.md` invariants.
- `scripts/test_install.py`: stdlib test suite for `scripts/install.sh`.

## Rules

- Change the SRD first. Any behavior or layout change updates `system_requirements_document_memoir_skill.md` (and `SPEC.md` if storage/schema changes) before updating skills, CLI, scripts, or `dashboard/`.
- `skills/memoir/scripts/memoir.py` uses only the Python 3.11+ standard library and keeps its PEP 723 header so `uv run` works (NFR-1.1).
- `dashboard/` (`memoir-ui`) MUST compile with `CGO_ENABLED=0` to a single static binary with zero runtime dependencies (NFR-1.2). `memoir` and `memoir-wiki` MUST function identically without `memoir-ui` installed or running (SRD Section 2.1).
- All memory, wiki, and search index data MUST remain strictly local on the user's filesystem (NFR-2.1).
- Fragment filenames are lowercase kebab-case: `decision-*`, `log-*`, `reference-*`, or `feedback-*` with an `.md` extension, plus the single `state-current.md`.
- The LLM never guesses storage paths. It uses only the exact absolute path printed by `memoir.py` (NFR-3.1).
- Releases use bare, zero-padded, 1-based CalVer tags (`YYYY.MM.N`, e.g., `2026.11.1`) via `.github/workflows/release.yml`.
- Run `python3 test_memoir.py`, `python3 scripts/test_install.py`, and `cd dashboard && go test -race ./...` before calling a change done.
- Never add AI attribution to commits, PRs, issues, or files.
