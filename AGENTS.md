# AGENTS.md

Memoir is an agent skill: an LLM prompt (`skills/memoir/SKILL.md`) plus a Python CLI (`skills/memoir/scripts/memoir.py`). Together they persist session context to project-local files so chats can be cleared and reloaded.

## Layout

- `system_requirements_document_memoir_skill.md`: the SRD, the source of truth for behavior (FR/NFR numbers).
- `skills/memoir/SKILL.md`: the skill prompt loaded by the agent CLI.
- `skills/memoir/scripts/memoir.py`: the CLI for store resolution, archiving and resume output.
- `test_memoir.py`: a self-check for the CLI.

## Rules

- Change the SRD first. Any behavior change updates the relevant FR/NFR text, then `skills/memoir/SKILL.md` and the CLI, so all three stay in agreement.
- The CLI uses only the standard library, on Python 3.11+, and keeps its PEP 723 header so `uv run` works (NFR-1.1). No MCP servers or daemons (NFR-1.2).
- Fragment filenames are lowercase kebab-case: `decision-*`, `log-*`, `reference-*` or `feedback-*` with an `.md` extension, plus the single `state-current.md`.
- The LLM never guesses paths. It uses only the absolute path printed by the CLI (NFR-3.1).
- Run `python3 test_memoir.py` before calling a change done. It must print `ok`.
- Never add AI attribution to commits, PRs or files.
