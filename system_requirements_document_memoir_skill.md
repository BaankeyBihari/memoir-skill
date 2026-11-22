# System Requirements Document: Memoir Monorepo (v2.0)

**Repository:** `BaankeyBihari/memoir-skill`  
**Status:** Approved for Implementation  
**Scope:** Monorepo restructure, centralized `~/.memoir` store migration (`memoir`), Karpathy-style cumulative knowledge compiler (`memoir-wiki`), local Go web browser (`memoir-ui`), and unified `scripts/install.sh` installer.

---

## 1. Introduction

### 1.1 Purpose
This document defines the system requirements, storage schema, and component contracts for **Memoir v2.0**—a local-first memory, session-compaction, and cumulative knowledge-management system for LLM CLI harnesses (Claude Code, OpenAI Codex CLI, Antigravity/`agy`, and Pi).

### 1.2 Problem Statement (Lessons from v1)
While v1 proved that deterministic CLI path resolution paired with typed Markdown fragments (`decision`, `log`, `reference`, `feedback`, `state`) prevents context entropy, storing memory inside `<repo-root>/.agents/memoir` introduced four friction points:
1. **Worktree Sandbox Prompts:** Invoking an agent inside a Git worktree (`Project-X/Worktrees/wt-*`) resolved writes to the main checkout above the workspace root, repeatedly triggering out-of-workspace write permission prompts.
2. **Multi-Clone Collisions:** Cloning the same repository in two local paths (`~/work/Project-X` and `~/scratch/Project-X`) risked state collisions if keyed solely by remote URL, whereas pure path keying fractured shared architectural knowledge across worktrees.
3. **Fragment Accumulation Without Synthesis:** Point-in-time session fragments accumulated in `active/` and `archive/` without rolling up into a living, cross-linked architectural knowledge base.
4. **Non-Git Workspace Fragmentation:** Directories outside Git lacked a parent-root anchor unless the user manually set `$MEMOIR_STORE`.

### 1.3 Solution Overview
Memoir v2.0 centralizes all state under **`~/.memoir`** (requiring only a single global sandbox permission grant) while partitioning storage deterministically by **Repository → Clone (`<slug>--<sha8>`) → Worktree/Subpath**, and splits responsibilities across three decoupled components in one monorepo:
1. **`skills/memoir` (Session Compactor):** High-frequency, in-context extraction of typed session fragments into `~/.memoir/.../active/` for instant `CLEAR` / `RESUME` cycles.
2. **`skills/memoir-wiki` (Knowledge Compiler):** Low-frequency, cumulative synthesis of pre-distilled `memoir` fragments across all clones and subpaths into an interlinked Markdown `wiki/` (`index.md`, `log.md`, `[[wikilinks]]`).
3. **`dashboard/` (`memoir-ui` Go Web Browser):** Zero-dependency, single-binary HTTP server with `embed.FS` and `fsnotify` SSE live reload for browsing wikis, clones, worktrees, backlinks, and decision supersession chains.

---

## 2. Monorepo Architecture

```text
memoir-skill/
├── README.md
├── SPEC.md                                        # Canonical ~/.memoir filesystem & schema contract
├── system_requirements_document_memoir_skill.md   # This SRD (v2.0)
├── scripts/
│   ├── install.sh                                 # Unified curl-able installer (skills + Go binary)
│   ├── next-version.sh                            # Next YYYY.M.N release tag (FR-6.2)
│   └── test_install.py                            # Stdlib installer checks
├── .github/
│   └── workflows/
│       └── release.yml                            # Dispatch-only CalVer release (skills + Go binary)
├── skills/
│   ├── memoir/                                    # Skill 1: Session compaction & state persistence
│   │   ├── SKILL.md
│   │   ├── references/
│   │   │   └── always-on.md
│   │   └── scripts/
│   │       └── memoir.py                          # Zero-dependency stdlib Python 3.11+ CLI
│   └── memoir-wiki/                               # Skill 2: Karpathy-style cumulative wiki compiler
│       ├── SKILL.md
│       └── references/
│           └── schema.md
└── dashboard/                                     # Component 3: Local Go web dashboard (memoir-ui)
    ├── go.mod
    ├── go.sum
    ├── main.go
    └── internal/
        ├── store/                                 # ~/.memoir scanner, frontmatter & git root checks
        ├── render/                                # Goldmark Markdown, [[wikilink]], backlinks & graphs
        └── web/                                   # embed.FS frontend assets + fsnotify SSE hub
```

### 2.1 Component Decoupling Rules
* **No Transcript Parsing:** Neither `memoir` nor `memoir-wiki` reads vendor-specific CLI `.jsonl` logs. `memoir` operates in-context using native agent file-writing tools; `memoir-wiki` reads only structured `memoir` Markdown fragments.
* **No Daemon Dependency:** `memoir` and `memoir-wiki` MUST function identically whether `memoir-ui` is installed or running.
* **Zero Working-Tree Pollution:** Neither `memoir` nor `memoir-wiki` writes files into repository working trees or modifies `.gitignore` (unless the user explicitly opts into `sync_to_repo` in `meta.json`).

---

## 3. Canonical `~/.memoir` Store Layout

Default store root (`$STORE_ROOT`) SHALL resolve from `$MEMOIR_STORE` if set, otherwise `~/.memoir`.

```text
~/.memoir/
├── config.toml                                    # Optional global configuration
├── pinned.json                                    # Canonical realpaths of user-pinned non-Git roots
├── repos/                                         # Scope 1: Git-backed repositories
│   └── <repo_id>/                                 # e.g., github.com__baankeybihari__memoir-skill
│       ├── meta.json                              # {"remote": "...", "sync_to_repo": false, "sync_target": "docs/wiki"}
│       ├── wiki/                                  # Compiled by memoir-wiki (shared across all clones)
│       │   ├── .ingest-state.json                 # Watermarks of processed fragment paths + sha256
│       │   ├── index.md                           # Master catalog: one-line summary + link per page
│       │   ├── log.md                             # Append-only chronological audit trail
│       │   ├── conventions.md                     # Synthesized from feedback-*.md
│       │   ├── architecture/
│       │   ├── decisions/                         # Synthesized from decision-*.md + archive/
│       │   ├── entities/                          # Synthesized from reference-*.md
│       │   └── troubleshooting/                   # Synthesized from log-*.md
│       └── clones/
│           └── <project-slug>--<sha8>/            # e.g., memoir-skill--a1b2c3d4
│               ├── clone.json                     # {"root": "/abs/path/to/main/checkout", "last_seen": "..."}
│               └── paths/
│                   ├── _main/                     # Primary checkout root
│                   │   ├── active/
│                   │   │   ├── state-current.md
│                   │   │   ├── decision-*.md
│                   │   │   ├── log-*.md
│                   │   │   ├── reference-*.md
│                   │   │   └── feedback-*.md
│                   │   └── archive/
│                   └── Worktrees__wt-feature/     # Worktree relative to --show-toplevel
│                       ├── active/
│                       └── archive/
├── pinned/                                        # Scope 2: User-pinned non-Git workspaces
│   └── <project-slug>--<sha8>/                    # e.g., research--4d5e6f7a
│       ├── workspace.json                         # {"root": "/abs/path/to/pinned/root", "last_seen": "..."}
│       ├── wiki/                                  # Compiled by memoir-wiki across all pinned subpaths
│       └── paths/
│           ├── _root/                             # Invoked directly at pinned root
│           │   ├── active/
│           │   └── archive/
│           └── sub__dir/                          # Invoked in subdirectory under pinned root
│               ├── active/
│               └── archive/
└── standalone/                                    # Scope 3: Unpinned non-Git directories (flat)
    └── <project-slug>--<sha8>/                    # e.g., scratch-script--8b9c0d1e
        ├── active/
        └── archive/
```

---

## 4. Functional Requirements: `memoir` Core (`skills/memoir`)

### 4.1 Storage & Path Resolution
* **FR-1.1 (Store Root):** Resolve `$STORE_ROOT` from `$MEMOIR_STORE` if non-empty, else `~/.memoir`.
* **FR-1.2 (Git `repo_id`):** Inside a Git worktree/repo, query `git remote get-url origin`. Normalize into `<host>__<owner>__<repo>` (lowercase, strip `.git` suffix and URL scheme/user, replace `:` and `/` with `__`). If no `origin` remote exists, fall back to `local__<project-slug>--<sha8(realpath(--git-common-dir))>`.
* **FR-1.3 (Git `clone_id` & `path_key`):**
  * Compute `MAIN_ROOT = dirname(realpath(git rev-parse --git-common-dir))`.
  * Compute `project-slug` from `basename(MAIN_ROOT)` (lowercase, non-alphanumeric sequences collapsed to a single `-`, trimmed of leading/trailing `-`).
  * Compute `sha8 = sha256(realpath(git rev-parse --git-common-dir))[:8]`.
  * Set `clone_id = "<project-slug>--<sha8>"`. Persist/update `clone.json` at `<STORE_ROOT>/repos/<repo_id>/clones/<clone_id>/clone.json` with `{"root": MAIN_ROOT, "last_seen": "<ISO-8601>"}`.
  * Compute `TOPLEVEL = realpath(git rev-parse --show-toplevel)`. If `TOPLEVEL == MAIN_ROOT`, `path_key = "_main"`. Otherwise, if `TOPLEVEL` is inside `MAIN_ROOT`, use `relpath(TOPLEVEL, MAIN_ROOT).replace("/", "__")`; else use `basename(TOPLEVEL)`.
  * Set `$BASE_DIR = <STORE_ROOT>/repos/<repo_id>/clones/<clone_id>/paths/<path_key>`.
* **FR-1.4 (Non-Git Pinned & Standalone Resolution):**
  * Store canonical `realpath` strings in `<STORE_ROOT>/pinned.json` (JSON array of strings).
  * For non-Git `REAL_CWD = realpath($PWD)`, find all entries `PIN` in `pinned.json` where `REAL_CWD == PIN` or `REAL_CWD` starts with `PIN + "/"`.
  * **Pinned Match (Longest Prefix Wins):**
    * `slug = "<slugify(basename(PIN))>--<sha256(PIN)[:8]>"`
    * `subpath = "_root"` if `REAL_CWD == PIN` else `relpath(REAL_CWD, PIN).replace("/", "__")`
    * Persist/update `workspace.json` at `<STORE_ROOT>/pinned/<slug>/workspace.json` with `{"root": PIN, "last_seen": "<ISO-8601>"}`.
    * Set `$BASE_DIR = <STORE_ROOT>/pinned/<slug>/paths/<subpath>`.
  * **Standalone Fallback (No Pinned Ancestor):**
    * `slug = "<slugify(basename(REAL_CWD))>--<sha256(REAL_CWD)[:8]>"`
    * Set `$BASE_DIR = <STORE_ROOT>/standalone/<slug>`.
* **FR-1.5 (Internal Directories & Write Probe):** Every command except `path`, `pin`, `unpin`, and `gc` MUST ensure `$BASE_DIR/active/` and `$BASE_DIR/archive/` exist and probe a write before proceeding. On failure, print `[Memoir] No write access to <absolute path> (<OS error>)` and exit `3` without falling back to another path. The LLM MUST stop, show the user the absolute path (`~/.memoir`), and ask them to grant directory access before retrying.
* **FR-1.6 (No Repo `.gitignore` Mutation):** Remove v1 `.gitignore` injection logic; `memoir.py` MUST NOT touch files inside user repositories.
* **FR-1.7 (Lazy v1 Store Migration):** After the write probe (FR-1.5), if `$BASE_DIR/active/` and `$BASE_DIR/archive/` are both empty, look for the first v1 store with an `active/` or `archive/` directory among `<ROOT>/.agents/memoir`, `<ROOT>/.claude/memoir`, and `${XDG_CONFIG_HOME:-~/.config}/memoir/memories/<sha256(realpath($PWD))[:8]>`, where `<ROOT>` is `realpath(git rev-parse --show-toplevel)` inside Git, else `realpath($PWD)`. Copy its `active/` and `archive/` contents into `$BASE_DIR` (never move or delete the v1 store) and print `[Memoir] Migrated <n> files from <legacy> to <BASE_DIR>; delete <legacy> once verified.` to stderr (stdout stays the `prompt`/`resume` contract). If `$BASE_DIR` already holds files, do not merge. When every v1 file is already in `$BASE_DIR` (same relative path, or a v1 `active/<name>` archived as `archive/<YYYYMMDD>-<name>`; contents are not compared because v2 files keep changing after the copy), print `[Memoir] Legacy store <legacy> is already migrated to <BASE_DIR>; delete <legacy> to silence this.` to stderr; otherwise print `[Memoir] Legacy store <legacy> not migrated: <BASE_DIR> already has files.` to stderr. No dedicated migration command exists.
* **FR-1.8 (v1 `MEMOIR_STORE` Guard):** In v1, `$MEMOIR_STORE` named a base directory; in v2 it names the store root. If `$STORE_ROOT/active` is a directory, every command MUST exit `1` with `[Memoir] <STORE_ROOT> is a v1 store (has active/); unset or repoint MEMOIR_STORE to a v2 store root.` without creating anything.

### 4.2 CLI Commands (`skills/memoir/scripts/memoir.py`)
* **FR-2.1 (`init`):** Create `$BASE_DIR/active/` and `$BASE_DIR/archive/` and write scope metadata (`clone.json` or `workspace.json`).
* **FR-2.2 (`prompt`):** Output the system instruction string containing the exact absolute path to `$BASE_DIR/active/`.
* **FR-2.3 (`archive`):** Move specified superseded files from `active/` to `archive/`, prepending `YYYYMMDD-`. With `--superseded`, move every active decision named on another active decision's `Supersedes:` line into `archive/`, writing `Superseded-By: <new-file.md>` into the active copy prior to moving so the operation is crash-safe and idempotent.
* **FR-2.4 (`resume`):** Output the `prompt` instruction followed by a copy-paste ready list of exact absolute paths of all active files, `state-current.md` first.
* **FR-2.5 (`path`):** Print the resolved `$BASE_DIR` for user inspection.
* **FR-2.6 (`pin [path]` & `unpin [path]`):** Resolve `realpath(path)` (defaulting to `.`) and add or remove it from `<STORE_ROOT>/pinned.json` (idempotent). Print the resolved pinned workspace slug and path.
* **FR-2.7 (`gc [--prune]`):** Scan `clone.json` and `workspace.json` across `<STORE_ROOT>/repos/` and `<STORE_ROOT>/pinned/`. Report entries whose `root` directory no longer exists on disk (`--dry-run` default); remove those orphaned staging directories when `--prune` is passed.

### 4.3 LLM Operations & Commands (`skills/memoir/SKILL.md`)
All v1 fragment schemas and slash commands remain unchanged:
* **FR-3.1:** Strict lowercase kebab-case filenames (`decision-{slug}.md`, `log-{slug}.md`, `reference-{slug}.md`, `feedback-{slug}.md`, `state-current.md`; collision suffix `-2`, `-3`).
* **FR-3.2 (`/memoir decision [text]`):** Write `active/decision-{slug}.md` with `Date:`, `Supersedes:`, `Decision:`, `Why:`, `Alternatives:`, `Deferred:`.
* **FR-3.3 (`/memoir log [text]`):** Write `active/log-{slug}.md` with `Date:`, `Event:`, `Impact:`.
* **FR-3.4 (`/memoir reference [text]`):** Write `active/reference-{slug}.md` with verified `Target:` and `Why:`.
* **FR-3.5 (`/memoir state`):** Overwrite `active/state-current.md` (max 3 bullets per section: `Goal`, `Completed`, `Blocked/Pending`, `Next Action`).
* **FR-3.6 (`/memoir coach`):** Run capture (FR-3.9), then output exactly one template (`CLEAR` > `COMPACT` > `CONTINUE`) with concrete session evidence.
* **FR-3.7 (`/memoir reload`):** Run `memoir.py archive --superseded`, then `memoir.py resume`, read every listed file starting with `state-current.md`, and report restored Goal and Next Action.
* **FR-3.8 (Automatic decisions):** Automatically record `decision-{slug}.md` when the user chooses among alternatives or says `"decision:"` or `"let's go with X"`.
* **FR-3.9 (`/memoir capture`):** Sweep active conversation for unrecorded decisions, logs, references, and feedback, write missing fragments, update `state-current.md`, and print `Captured: <n> decisions, <n> logs, <n> references, <n> feedback, state updated`.
* **FR-3.10 (`/memoir feedback [text]`):** Record durable collaboration/style preferences in `active/feedback-{slug}.md`.

---

## 5. Functional Requirements: `memoir-wiki` Skill (`skills/memoir-wiki`)

### 5.1 Knowledge Compiler Workflows
* **FR-4.1 (Scope Resolution):** Resolve the target wiki root for the current working directory:
  * Git repo → `<STORE_ROOT>/repos/<repo_id>/wiki/`
  * Pinned workspace → `<STORE_ROOT>/pinned/<slug>/wiki/`
  * Standalone directory → inform user that wikis require a Git repo or pinned workspace (`memoir.py pin`).
* **FR-4.2 (`/memoir-wiki ingest`):**
  * Scan all `clones/*/paths/*/active/` and `archive/` (or `paths/*/active/` and `archive/` for pinned workspaces).
  * Compare relative fragment paths and SHA-256 content hashes against `wiki/.ingest-state.json`; skip unchanged files.
  * Synthesize new facts into existing wiki pages (updating superseded decisions, flagging contradictions, and adding `[[wikilinks]]`):
    * `decision-*.md` & `archive/` → `wiki/decisions/`
    * `reference-*.md` → `wiki/entities/`
    * `log-*.md` → `wiki/troubleshooting/`
    * `feedback-*.md` → `wiki/conventions.md`
  * Update `wiki/index.md` (one-line summary + link per page) and append `## [YYYY-MM-DD] ingest | <summary>` to `wiki/log.md`.
  * **Optional Repo Mirror:** If `<STORE_ROOT>/repos/<repo_id>/meta.json` contains `"sync_to_repo": true`, copy `wiki/*.md` and wiki subdirectories (excluding `.ingest-state.json`) into `<MAIN_ROOT>/<sync_target>` (default `docs/wiki/`).
* **FR-4.3 (`/memoir-wiki query [question]`):** Read `wiki/index.md` first, traverse 2–4 relevant `[[wikilink]]` pages, answer the question, and file valuable multi-page syntheses back into `wiki/` (registering in `index.md` and `log.md`).
* **FR-4.4 (`/memoir-wiki lint`):** Audit `wiki/` for orphan pages (zero inbound `[[wikilinks]]`), pages omitted from `index.md`, broken `[[wikilinks]]`, contradictory claims, and stale file paths and commands verified against the current checkout; append findings to `wiki/log.md`.
* **FR-4.5 (Wiki Isolation & Cross-Wiki Links):** Each Git repository owns exactly one wiki (shared by its clones and worktrees) and each pinned workspace owns exactly one wiki (shared by its subpaths). `ingest`, `query`, and `lint` read fragments only from the current scope and write only to its `wiki/`; wikis are never merged into a global cross-repo wiki. Pages MAY reference another scope with read-only `[[<scope>:<page-path>]]` links (`<scope>` = `repo_id` or pinned slug), resolved to `<STORE_ROOT>/repos/<scope>/wiki/<page-path>.md`, else `<STORE_ROOT>/pinned/<scope>/wiki/<page-path>.md`. Following such a link never edits the other wiki or its `index.md`; `lint` checks that its target exists and excludes it from orphan counts; `sync_to_repo` copies it verbatim.

---

## 6. Functional Requirements: `memoir-ui` Go Dashboard (`dashboard/`)

### 6.1 Single-Binary Web Viewer
* **FR-5.1 (Zero-Dependency Binary):** Build under `dashboard/go.mod` using Go `embed.FS` for all HTML/CSS/JS assets. Support `--port` (default `7337`), `--store` (default `~/.memoir`), and `--open` on the default (no-subcommand) foreground server; lifecycle subcommands are in FR-5.6.
* **FR-5.2 (Live Reload via SSE):** Watch `$STORE_ROOT` recursively with `fsnotify` and broadcast file-change events over `/events` (Server-Sent Events) so open browser tabs refresh automatically when agents write fragments or wiki pages.
* **FR-5.3 (Hierarchical Sidebar):** Group top-level navigation into **Repos**, **Pinned Workspaces**, and **Standalone**, expanding into shared **Wiki** (`index.md`, `log.md`, categories) and **Clones → Worktrees** (`state-current.md`, `active/`, `archive/`).
* **FR-5.4 (Markdown, `[[wikilinks]]`, Backlinks & Supersession Graphs):**
  * Render Markdown via `goldmark` with clickable `[[wikilink]]` routing.
  * Parse frontmatter/header fields (`Date`, `Supersedes`, `Superseded-By`, `Target`) into metadata badges.
  * Compute and render inbound **Backlinks** on every page and visual supersession chains across active and `archive/` `decision-*.md` files.
* **FR-5.5 (Search & Safe Housekeeping):**
  * Maintain an in-memory full-text search index refreshed on `fsnotify` events, accessible via `Cmd+K` with scope (`repo`, `pinned`, `standalone`) and type (`decision`, `log`, `reference`, `feedback`, `wiki`) filters.
  * Badge orphaned clones/workspaces whose `root` path no longer exists on disk and provide a confirmed prune action equivalent to `memoir.py gc --prune`.
* **FR-5.6 (Lifecycle & Update Subcommands):** `memoir-ui` with no subcommand runs the FR-5.1 foreground server unchanged. `GET /api/health` additionally reports `app` (`"memoir-ui"`), `pid`, and `version`; a port "runs memoir-ui" only when its health answers with `app == "memoir-ui"`. Subcommands (each accepting `--port`, default `7337`):
  * `dashboard [--store S]`: if memoir-ui already runs on the port, only open the browser; otherwise start the server as a detached background process logging to `<user cache dir>/memoir-ui/memoir-ui.log`, wait up to 5 s for its health, open the browser, and print the URL, PID, and log path. Fail if the port is held by anything else.
  * `shutdown`: send `SIGTERM` to the PID from health and wait up to 5 s for it to stop; print `not running` and exit `0` when nothing runs. There is no HTTP shutdown endpoint, because any browser page can reach localhost.
  * `status`: print `running <url> pid=<pid> version=<v> store=<s>` and exit `0`, else `not running on <port>` and exit `1`.
  * `check-update`: only when invoked, fetch the latest GitHub Release tag once and compare it (numeric `YYYY.M.N`) with the binary version and `~/.agents/skills/{memoir,memoir-wiki}/VERSION` (`unknown` for `dev` or a missing file); print each as current, behind, or unknown and, when any is not current, the `scripts/install.sh` curl command. No self-update; exit `1` on network failure.
  * `help` (also `-h`, `--help`): print usage for every subcommand.
  * Browsers open through `$BROWSER` when set, else the platform opener.

---

## 7. Installer & Release Requirements

* **FR-6.1 (`scripts/install.sh`):** Idempotent Bash installer supporting `--skills-only`, `--ui-only`, `--store <path>`, and `--version <YYYY.M.N>`:
  1. When `--version` is unset inside a local checkout, install skills from `skills/`; otherwise download `memoir-skills.tar.gz` from the target (or latest) GitHub Release and verify its SHA-256 against `SHA256SUMS` (falling back to `main.tar.gz` only when `--version` is unset and no release archive is available).
  2. Copy `memoir` and `memoir-wiki` into `~/.agents/skills/` and symlink both skills into `~/.claude/skills/`, `~/.codex/skills/`, `~/.pi/agent/skills/`, and `~/.gemini/antigravity/skills/` when those parent directories exist.
  3. Download the matching OS/arch `memoir-ui` binary from GitHub Releases, verify its SHA-256 against `SHA256SUMS`, and install into `~/.local/bin/memoir-ui` (falling back to `go install ./dashboard` when `--version` is unset and Go is installed locally).
  4. Initialize `~/.memoir/` if absent and verify write access to `$STORE_ROOT`.
  5. When installing skills (default or `--skills-only`), idempotently grant read/write access to `$STORE_ROOT` in detected CLI configurations (`~/.claude/settings.json`, `~/.codex/config.toml`, `~/.gemini/antigravity-cli/settings.json`, and `~/.pi/agent/sandbox.json` if present) without overwriting malformed user configs.
* **FR-6.2 (Versioning & Unified Release Workflow):** Releases use bare, 1-based, non-zero-padded CalVer tags (`YYYY.M.N`, e.g., `2026.11.3`, `2027.1.1`, validated by `^[0-9]{4}\.([1-9]|1[0-2])\.[1-9][0-9]*$`) so every version is also valid semver. The tag is the single source of truth: `SKILL.md`, `plugin.json`, and `memoir.py` carry no version field; only built artifacts are stamped (`memoir-ui` via `-ldflags` for `--version`, and a `VERSION` file in each skill folder of `memoir-skills.tar.gz`). Tags are never pushed by hand: `.github/workflows/release.yml` runs only on `workflow_dispatch` from `main` (one run at a time), computes the next tag with `scripts/next-version.sh` (the current UTC year and month, `N` = highest existing `N` for that month + 1), runs the CLI, installer, and dashboard test suites, packages `memoir-skills.tar.gz` (`memoir/` and `memoir-wiki/`), cross-compiles static `memoir-ui` binaries (`darwin-arm64`, `darwin-amd64`, `linux-amd64`, `linux-arm64`), and publishes all assets alongside a unified `SHA256SUMS` file as the GitHub Release marked Latest, creating the tag at the built commit. It then fast-forwards (never force-pushes) the `stable` branch to that commit, so rev-pinning managers such as athena can follow releases with `#stable` or pin one with `#<tag>`.

---

## 8. Non-Functional Requirements

* **NFR-1.1 (Python Portability):** `memoir.py` MUST run on Python 3.11+ using only standard library modules (`pathlib`, `hashlib`, `json`, `subprocess`, `argparse`, `datetime`, `shutil`).
* **NFR-1.2 (Go Portability):** `dashboard/` MUST compile to a single static binary with zero runtime dependencies.
* **NFR-2.1 (Local-First Privacy):** All memory, wiki, and search index data MUST remain strictly local on the user's filesystem.
* **NFR-3.1 (Path Determinism):** LLMs MUST NEVER guess storage paths; all fragment writes MUST target the exact path returned by `memoir.py prompt`.
