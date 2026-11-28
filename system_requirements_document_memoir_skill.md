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
│                   │   ├── worktree.json          # {"root": "/abs/path/to/worktree/toplevel", "last_seen": "..."}
│                   │   ├── active/
│                   │   │   ├── state-current.md
│                   │   │   ├── decision-*.md
│                   │   │   ├── log-*.md
│                   │   │   ├── reference-*.md
│                   │   │   └── feedback-*.md
│                   │   └── archive/
│                   └── Worktrees__wt-feature/     # Worktree relative to --show-toplevel
│                       ├── worktree.json
│                       ├── active/
│                       └── archive/
├── pinned/                                        # Scope 2: Groups over standalone scopes (no fragments)
│   └── <project-slug>--<sha8>/                    # e.g., research--4d5e6f7a
│       ├── workspace.json                         # {"root": "/abs/path/to/pinned/root", "last_seen": "..."}
│       ├── wiki/                                  # Compiled by memoir-wiki across all group members
│       └── paths/                                 # Legacy pre-group fragments, copied out lazily (FR-1.7)
└── standalone/                                    # Scope 3: Every non-Git directory (flat), pinned or not
    └── <project-slug>--<sha8>/                    # e.g., scratch-script--8b9c0d1e
        ├── scope.json                             # {"root": "/abs/path/to/directory", "last_seen": "..."}
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
  * Compute `TOPLEVEL = realpath(git rev-parse --show-toplevel)`. If `TOPLEVEL == MAIN_ROOT`, `path_key = "_main"`. Otherwise, if `TOPLEVEL` is inside `MAIN_ROOT`, use `relpath(TOPLEVEL, MAIN_ROOT).replace("/", "__")`; else (a worktree outside `MAIN_ROOT`) use `"<slugify(basename(TOPLEVEL))>--<sha256(TOPLEVEL)[:8]>"`, the scope-ID shape of FR-1.4, so two outside worktrees with the same folder name, or one named `_main` or like an inside key, never share a folder.
  * Set `$BASE_DIR = <STORE_ROOT>/repos/<repo_id>/clones/<clone_id>/paths/<path_key>`. Persist/update `$BASE_DIR/worktree.json` with `{"root": TOPLEVEL, "last_seen": "<ISO-8601>"}` whenever `clone.json` is written. Siblings (FR-2.4, FR-2.9) learn whether their worktree still exists from this record. They never decode `path_key`, because `__` joins are ambiguous and outside-worktree keys are hashed.
* **FR-1.4 (Non-Git Pinned & Standalone Resolution):**
  * Store canonical `realpath` strings in `<STORE_ROOT>/pinned.json` (JSON array of strings).
  * For non-Git `REAL_CWD = realpath($PWD)`, find all entries `PIN` in `pinned.json` where `REAL_CWD == PIN` or `REAL_CWD` starts with `PIN + "/"`.
  * **Standalone Scope (Always):** `slug = "<slugify(basename(REAL_CWD))>--<sha256(REAL_CWD)[:8]>"`; set `$BASE_DIR = <STORE_ROOT>/standalone/<slug>` and persist/update `<BASE_DIR>/scope.json` with `{"root": REAL_CWD, "last_seen": "<ISO-8601>"}`. Fragments are always written here, pinned or not.
  * **Pinned Group (Longest Prefix Wins):** A pin is a group, not a storage location. The group of `REAL_CWD` is its longest matching `PIN`, with `slug = "<slugify(basename(PIN))>--<sha256(PIN)[:8]>"`; persist/update `<STORE_ROOT>/pinned/<slug>/workspace.json` with `{"root": PIN, "last_seen": "<ISO-8601>"}`. Its **members** are the standalone scopes whose `scope.json` root has that `PIN` as its longest matching pin. Membership is computed on each read, never stored, so unpinning or nesting pins regroups scopes without moving any file. Group reads (FR-2.3, FR-2.4, FR-2.8, FR-4.2) flatten every member's `decision-`, `log-`, `reference-`, and `feedback-` fragments; `state-current.md` is read only from `$BASE_DIR`.
* **FR-1.5 (Internal Directories & Write Probe):** Every command except `path`, `pin`, `unpin`, and `gc` MUST ensure `$BASE_DIR/active/` and `$BASE_DIR/archive/` exist and probe a write before proceeding. On failure, print `[Memoir] No write access to <absolute path> (<OS error>)` and exit `3` without falling back to another path. The LLM MUST stop, show the user the absolute path (`~/.memoir`), and ask them to grant directory access before retrying.
* **FR-1.6 (No Repo `.gitignore` Mutation):** Remove v1 `.gitignore` injection logic; `memoir.py` MUST NOT touch files inside user repositories.
* **FR-1.7 (Lazy v1 Store Migration):** After the write probe (FR-1.5), if `$BASE_DIR/active/` and `$BASE_DIR/archive/` are both empty, look for the first v1 store with an `active/` or `archive/` directory among `<ROOT>/.agents/memoir`, `<ROOT>/.claude/memoir`, and `${XDG_CONFIG_HOME:-~/.config}/memoir/memories/<sha256(realpath($PWD))[:8]>`, then, outside Git, the legacy pre-group pinned path `<STORE_ROOT>/pinned/<group-slug>/paths/<subpath>` (`subpath` = `_root` at the pin, else `relpath(REAL_CWD, PIN)` joined with `__`), then, inside Git, the standalone scope `<STORE_ROOT>/standalone/<slug(realpath($PWD))>`, and last, for a worktree outside `MAIN_ROOT`, its pre-hash folder `<STORE_ROOT>/repos/<repo_id>/clones/<clone_id>/paths/<basename(TOPLEVEL)>` (FR-1.3), but only when that folder's `worktree.json` is absent or names `TOPLEVEL`, so another worktree's notes are never copied in, where `<ROOT>` is `realpath(git rev-parse --show-toplevel)` inside Git, else `realpath($PWD)`. The standalone candidate carries a folder's notes into its repository scope after `git init`. Copy its `active/` and `archive/` contents into `$BASE_DIR` (never move or delete the v1 store) and print `[Memoir] Migrated <n> files from <legacy> to <BASE_DIR>; delete <legacy> once verified.` to stderr (stdout stays the `prompt`/`resume` contract). If `$BASE_DIR` already holds files, do not merge. When every v1 file is already in `$BASE_DIR` (same relative path, or a v1 `active/<name>` archived as `archive/<YYYYMMDD>-<name>`; contents are not compared because v2 files keep changing after the copy), print `[Memoir] Legacy store <legacy> is already migrated to <BASE_DIR>; delete <legacy> to silence this.` to stderr; otherwise print `[Memoir] Legacy store <legacy> not migrated: <BASE_DIR> already has files.` to stderr. No dedicated migration command exists.
* **FR-1.8 (v1 `MEMOIR_STORE` Guard):** In v1, `$MEMOIR_STORE` named a base directory; in v2 it names the store root. If `$STORE_ROOT/active` is a directory, every command MUST exit `1` with `[Memoir] <STORE_ROOT> is a v1 store (has active/); unset or repoint MEMOIR_STORE to a v2 store root.` without creating anything.

### 4.2 CLI Commands (`skills/memoir/scripts/memoir.py`)
* **FR-2.1 (`init`):** Create `$BASE_DIR/active/` and `$BASE_DIR/archive/` and write scope metadata (`clone.json`, or `scope.json` plus the group's `workspace.json`).
* **FR-2.2 (`prompt`):** Output the system instruction string containing the exact absolute path to `$BASE_DIR/active/`.
* **FR-2.3 (`archive`):** Move specified superseded files from `active/` to `archive/`, prepending `YYYYMMDD-`. With `--superseded`, move every active decision named on another active decision's `Supersedes:` line into `archive/`, writing `Superseded-By: <new-file.md>` into the active copy prior to moving so the operation is crash-safe and idempotent. In a pinned group, `Supersedes:` lines are read from every member; a named file is looked up in the superseding decision's own scope first, else in the only member holding it, and archived inside its own scope. A name held by several other members is skipped with a warning. Explicit `archive <files>` acts on `$BASE_DIR` only.
* **FR-2.4 (`resume`):** Output the `prompt` instruction followed by a copy-paste ready list of exact absolute paths of all active files, `state-current.md` first. In a pinned group the list holds `$BASE_DIR`'s `state-current.md`, then the active fragments of every member (FR-1.4); other members' `state-current.md` files are never listed.
  * **Wiki lag:** When the shared wiki directory exists and FR-2.10 finds changes, print one line: `Wiki: <N> pending fragment changes (<counts>); run /memoir-wiki ingest`. Count each diff row, listing nonzero categories in new, changed, missing order. For example, a missing-only diff prints `Wiki: 1 pending fragment change (1 missing); run /memoir-wiki ingest`. Report lag even with an empty local session. Omit the line for an absent or current wiki. A malformed watermark produces a diagnostic without preventing session restore.
  * **Sibling paths (Git only):** A *sibling* is every other `paths/<key>/` of the same clone that has at least one `decision-`, `log-`, `reference-`, or `feedback-` fragment in its `active/`. After the file list, `resume` prints one line per sibling, sorted by key: `- <key>: <d> decisions, <l> logs, <r> references, <f> feedback; newest <YYYY-MM-DD>; worktree present|missing|unknown`. `newest` is the local date of the most recent fragment file modification time. `worktree` is `present` if the sibling's `worktree.json` `root` is an existing directory, `missing` if it is not, and `unknown` if the record is absent or unreadable. The sibling block is introduced by `Sibling worktrees with fragments (not loaded; add with resume --with <key>):` and is omitted when there are no siblings. It also prints when the current scope has no files, in which case "No recorded session found" stays the first result line. Siblings are listed, never loaded by default.
  * **`--with <key>` (repeatable):** Append the named sibling's active `decision-`, `log-`, `reference-`, and `feedback-` fragments to the file list for this invocation only. The sibling's `state-current.md` is never listed. `<key>` MUST be the name of an existing directory directly under the clone's `paths/` that is not `$BASE_DIR`. Any other value, or `--with` outside a Git scope, exits `1` with `[Memoir] No sibling path <key> in <clone dir>`. `--with` is read-only: `archive --superseded` keeps acting on the current scope only.
  * **Peek at other clones (`--peek`):** Siblings are per clone: worktrees of one clone are never siblings of another clone's checkouts, even of the same repository. With `--peek`, `resume` also prints the other clones under the same `<STORE_ROOT>/repos/<repo_id>/clones/`, sorted by `clone_id`, after the sibling block. The block is introduced by `Other clones with fragments (peek; add with resume --with <clone_id>/<key>):`. Each clone that has at least one `paths/<key>/` with fragments gets a heading line `clone <clone_id>: root <clone.json root | unknown>, <present|missing|unknown>`, followed by its checkouts in the sibling line format, indented by two spaces. Clones with no fragments are omitted, as is the whole block when none remain. `--peek` loads nothing and prints nothing extra outside a Git scope.
  * **`--with <clone_id>/<key>`:** A value containing one `/` names `paths/<key>/` of another clone of the same repository and loads it exactly like a sibling (fragments only, never `state-current.md`, this invocation only). It does not need `--peek`. `<clone_id>` MUST be an existing directory directly under `clones/` and `<key>` an existing directory under its `paths/`, and the target MUST NOT be `$BASE_DIR`. Otherwise exit `1` with `[Memoir] No clone path <value> in <repo dir>`.
  * **Rejected: cross-clone `adopt`.** `adopt` (FR-2.9) takes only a key of the current clone. Another clone is a separate, possibly active working area that merges code on its own, so moving its fragments would remove notes its sessions still use. Merged knowledge already crosses clones through the shared repository wiki (FR-4.2).
  * **Rejected: auto-loading every sibling.** Making `members_of` return every `paths/*` of the clone was rejected. Sibling folders outlive their worktrees, so `reload` would keep loading decisions from dropped or never-merged branches as current, and the load set would grow without bound. A branch's decisions become project truth only when the branch merges, which `adopt` (FR-2.9) expresses.
* **FR-2.5 (`path`):** Print the resolved `$BASE_DIR` for user inspection.
* **FR-2.6 (`pin [path]` & `unpin [path]`):** Resolve `realpath(path)` (defaulting to `.`) and add or remove it from `<STORE_ROOT>/pinned.json` (idempotent). Print the resolved pinned workspace slug and path. Pinning moves no fragment: the folder and every folder under it join the group at once (FR-1.4). `unpin` only removes the group's entry; each folder keeps its notes in its own standalone scope, and `pinned/<slug>/` (wiki included) stays. The `memoir` skill exposes both as `/memoir pin [path]` and `/memoir unpin [path]`.
* **FR-2.7 (`gc [--prune]`):** Scan `clone.json`, `workspace.json`, and `scope.json` across `<STORE_ROOT>/repos/`, `<STORE_ROOT>/pinned/`, and `<STORE_ROOT>/standalone/`. Report entries whose `root` directory no longer exists on disk (`--dry-run` default); remove those orphaned staging directories when `--prune` is passed.
* **FR-2.8 (`scope`):** Read-only like `path`. Print the wiki scope root (`<STORE_ROOT>/repos/<repo_id>` or `<STORE_ROOT>/pinned/<slug>`) on the first line, then one fragment directory per line: every `clones/*/paths/*` for a repository, every member's `$BASE_DIR` for a pinned group. Print nothing for a directory outside Git and outside any pin.
* **FR-2.9 (`adopt <key>`):** Git only. `<key>` is validated as a plain FR-2.4 `--with <key>` of the current clone, with the same error; a `<clone_id>/<key>` value is rejected that way too (no cross-clone adopt). Move every `decision-`, `log-`, `reference-`, and `feedback-` fragment from the sibling's `active/` into `$BASE_DIR/active/`, keeping its content. The sibling's `state-current.md` and `archive/` stay where they are. A name that already exists in `$BASE_DIR/active/` gets `-2`, `-3`, and so on, appended to its stem: the first free name (FR-3.1). In every adopted file, each `Supersedes:` and `Superseded-By:` line that names a renamed adopted file is rewritten to the new name. Other lines and files in `$BASE_DIR` are not touched. Each target is written atomically before its source is removed, so a crash leaves a duplicate, never a lost fragment. Output: `[Memoir] Adopted <n> files from <key>.`, then one absolute target path per line, followed by a space and `(renamed from <old name>)` when renamed. With nothing to adopt, print `[Memoir] Adopted 0 files from <key>.` and exit `0`. After adopt, `archive --superseded` (FR-2.3) treats adopted decisions like any other active file. Sibling folders whose worktree is gone are not pruned: `gc` (FR-2.7) does not read `worktree.json`.
* **FR-2.10 (`wiki-diff`):** Read the FR-2.8 scope without creating metadata or a wiki. Compare eligible active and date-prefixed archived files by relative path and SHA-256 against the existing watermark. Emit `new <sha256> <path>` or `changed <sha256> <path>` in sorted file order, then `missing - <path>` in sorted watermark-key order. An absent watermark means all eligible fragments are new. A standalone scope prints nothing. Malformed watermark data fails explicitly.

### 4.3 LLM Operations & Commands (`skills/memoir/SKILL.md`)
All v1 fragment schemas and slash commands remain unchanged:
* **FR-3.1:** Strict lowercase kebab-case filenames (`decision-{slug}.md`, `log-{slug}.md`, `reference-{slug}.md`, `feedback-{slug}.md`, `state-current.md`; collision suffix `-2`, `-3`).
* **FR-3.2 (`/memoir decision [text]`):** Write `active/decision-{slug}.md` with `Date:`, `Supersedes:`, `Decision:`, `Why:`, `Alternatives:`, `Deferred:`.
* **FR-3.3 (`/memoir log [text]`):** Write `active/log-{slug}.md` with `Date:`, `Event:`, `Impact:`.
* **FR-3.4 (`/memoir reference [text]`):** Write `active/reference-{slug}.md` with verified `Target:` and `Why:`.
* **FR-3.5 (`/memoir state`):** Overwrite `active/state-current.md` (max 3 bullets per section: `Goal`, `Completed`, `Blocked/Pending`, `Next Action`).
* **FR-3.6 (`/memoir coach`):** Run capture (FR-3.9), then output exactly one template (`CLEAR` > `COMPACT` > `CONTINUE`) with concrete session evidence.
* **FR-3.7 (`/memoir reload [--peek] [key ...]`):** Run `memoir.py archive --superseded`, then `memoir.py resume` (passing `--peek` when given and `--with <key>` for each given key, where a key may be `<clone_id>/<key>`), read every listed file starting with `state-current.md`, and report restored Goal and Next Action plus the wiki lag line (including on an empty local session), the sibling list and any other-clone block `resume` printed (FR-2.4).
* **FR-3.8 (Automatic decisions):** Automatically record `decision-{slug}.md` when the user chooses among alternatives or says `"decision:"` or `"let's go with X"`.
* **FR-3.9 (`/memoir capture`):** Sweep active conversation for unrecorded decisions, logs, references, and feedback, write missing fragments, update `state-current.md`, and print `Captured: <n> decisions, <n> logs, <n> references, <n> feedback, state updated`.
* **FR-3.10 (`/memoir feedback [text]`):** Record durable collaboration/style preferences in `active/feedback-{slug}.md`.
* **FR-3.11 (`/memoir adopt <key>`):** Run `memoir.py adopt <key>` (FR-2.9) and report the moved and renamed files it prints. Use it once a sibling worktree's branch has merged.
* **FR-3.12 (`/memoir init`):** Install the recommended capture and reload block from `references/always-on.md` in the project's instruction file. Adopt an exact unguarded copy in place. If the user customized the original section, report it for reconciliation.
* **Project instruction setup (FR-3.12, FR-4.6):** Each command manages only its own paired HTML comments and is idempotent. Preserve surrounding bytes and reject malformed or overlapping guards. Use the current Git worktree root, the enclosing pinned workspace root, or the current directory. Use the existing `AGENTS.md` or `CLAUDE.md`, defaulting to `AGENTS.md` when neither exists. When Claude imports `AGENTS.md`, update the shared file once. When both files are independent, ask which to update. Initialization is project-local and requires neither an existing wiki nor enabling the other skill.

---

## 5. Functional Requirements: `memoir-wiki` Skill (`skills/memoir-wiki`)

### 5.1 Knowledge Compiler Workflows
* **FR-4.1 (Scope Resolution):** Resolve the target wiki root for the current working directory from `memoir.py scope` (FR-2.8):
  * Git repo → `<STORE_ROOT>/repos/<repo_id>/wiki/`
  * Pinned workspace → `<STORE_ROOT>/pinned/<slug>/wiki/`
  * Standalone directory → inform user that wikis require a Git repo or pinned workspace (`memoir.py pin`).
* **FR-4.2 (`/memoir-wiki ingest`):**
  * Use `memoir.py wiki-diff` (FR-2.10) for the change list across every fragment directory printed by `memoir.py scope`.
  * Compare fragment paths relative to the scope root (`../../standalone/<slug>/...` for group members) and SHA-256 content hashes against `wiki/.ingest-state.json`; skip unchanged files.
  * Synthesize new facts into existing wiki pages (updating superseded decisions, flagging contradictions, and adding `[[wikilinks]]`):
    * `decision-*.md` & `archive/` → `wiki/decisions/`
    * `reference-*.md` → `wiki/entities/`
    * `log-*.md` → `wiki/troubleshooting/`
    * `feedback-*.md` → `wiki/conventions.md`
  * Update `wiki/index.md` (one-line summary + link per page) and append `## [YYYY-MM-DD] ingest | <summary>` to `wiki/log.md`.
  * **Optional Repo Mirror:** If `<STORE_ROOT>/repos/<repo_id>/meta.json` contains `"sync_to_repo": true`, copy `wiki/*.md` and wiki subdirectories (excluding `.ingest-state.json`) into `<MAIN_ROOT>/<sync_target>` (default `docs/wiki/`).
* **FR-4.3 (`/memoir-wiki query [question]`):** Read `wiki/index.md` first, traverse 2–4 relevant `[[wikilink]]` pages, answer the question, and file valuable multi-page syntheses back into `wiki/` (registering in `index.md` and `log.md`).
* **FR-4.4 (`/memoir-wiki lint`):** Audit `wiki/` for orphan pages (zero inbound `[[wikilinks]]`), pages omitted from `index.md`, broken `[[wikilinks]]`, contradictory claims, and stale file paths and commands verified against the current checkout; append findings to `wiki/log.md`.
* **FR-4.5 (Wiki Isolation & Cross-Wiki Links):** Each Git repository owns exactly one wiki (shared by its clones and worktrees) and each pinned group owns exactly one wiki (shared by its members). `ingest`, `query`, and `lint` read fragments only from the current scope and write only to its `wiki/`; wikis are never merged into a global cross-repo wiki. Pages MAY reference another scope with read-only `[[<scope>:<page-path>]]` links (`<scope>` = `repo_id` or pinned slug), resolved to `<STORE_ROOT>/repos/<scope>/wiki/<page-path>.md`, else `<STORE_ROOT>/pinned/<scope>/wiki/<page-path>.md`. Following such a link never edits the other wiki or its `index.md`; `lint` checks that its target exists and excludes it from orphan counts; `sync_to_repo` copies it verbatim.
* **FR-4.6 (`/memoir-wiki init`):** Install a separate project instruction block for read-only wiki lookup during any project knowledge search. If the current scope has a wiki index, prefer an Explore subagent using the `memoir-wiki` query workflow. Fall back to direct lookup when delegation or skill access is unavailable. Return page citations and gaps, verify current behavior against the checkout, and continue the original search when evidence is missing. Automatic lookup never ingests or files answers. Explicit queries retain FR-4.3 behavior.

---

## 6. Functional Requirements: `memoir-ui` Go Dashboard (`dashboard/`)

### 6.1 Single-Binary Web Viewer
* **FR-5.1 (Zero-Dependency Binary):** Build under `dashboard/go.mod` using Go `embed.FS` for all HTML/CSS/JS assets. Support `--port` (default `7337`), `--store` (default `~/.memoir`), and `--open` on the default (no-subcommand) foreground server; lifecycle subcommands are in FR-5.6.
* **FR-5.2 (Live Reload via SSE):** Watch `$STORE_ROOT` recursively with `fsnotify` and broadcast file-change events over `/events` (Server-Sent Events) so open browser tabs refresh automatically when agents write fragments or wiki pages.
* **FR-5.3 (Hierarchical Sidebar):** Group top-level navigation into **Repos**, **Pinned Workspaces**, and **Standalone**, expanding into shared **Wiki** (`index.md`, `log.md`, categories) and **Clones → Worktrees** (`state-current.md`, `active/`, `archive/`). A pinned group lists its member standalone scopes (labelled by directory relative to the pin) next to any legacy `pinned/<slug>/paths/<key>`, and **Standalone** lists only scopes in no group. On desktop viewports, the sidebar MUST be user-resizable (persisted in `localStorage`) and display concise file labels with full store-relative paths available on hover.
* **FR-5.4 (Markdown, `[[wikilinks]]`, Backlinks & Supersession Graphs):**
  * Render Markdown via `goldmark` with clickable `[[wikilink]]` routing.
  * Parse frontmatter/header fields (`Date`, `Supersedes`, `Superseded-By`, `Target`) into metadata badges.
  * Compute and render inbound **Backlinks** on every page and visual supersession chains across active and `archive/` `decision-*.md` files.
* **FR-5.5 (Search & Safe Housekeeping):**
  * Maintain an in-memory full-text search index refreshed on `fsnotify` events, accessible via `Cmd+K` with scope (`repo`, `pinned`, `standalone`; a group member's fragments count as `pinned` under its group) and type (`decision`, `log`, `reference`, `feedback`, `wiki`) filters.
  * Badge orphaned clones, workspaces and standalone scopes whose `root` path no longer exists on disk and provide a confirmed prune action equivalent to `memoir.py gc --prune`.
* **FR-5.6 (Lifecycle & Update Subcommands):** `memoir-ui` with no subcommand runs the FR-5.1 foreground server unchanged. `GET /api/health` additionally reports `app` (`"memoir-ui"`), `pid`, and `version`; a port "runs memoir-ui" only when its health answers with `app == "memoir-ui"`. Subcommands (each accepting `--port`, default `7337`):
  * `dashboard [--store S]`: if memoir-ui already runs on the port, only open the browser; otherwise start the server as a detached background process logging to `<user cache dir>/memoir-ui/memoir-ui.log`, wait up to 5 s for its health, open the browser, and print the URL, PID, and log path. Fail if the port is held by anything else, with `port <n> is in use by another program (maybe an older memoir-ui); stop it or pass --port <other>`.
  * `shutdown`: send `SIGTERM` to the PID from health and wait up to 5 s for it to stop; print `not running` and exit `0` when nothing runs. There is no HTTP shutdown endpoint, because any browser page can reach localhost.
  * `status`: print `running <url> pid=<pid> version=<v> store=<s>` and exit `0`, else `not running on <port>` and exit `1`.
  * `check-update`: only when invoked, fetch the latest GitHub Release tag once and compare it (numeric `YYYY.M.N`) with the binary version and `~/.agents/skills/{memoir,memoir-wiki}/VERSION` (`unknown` for `dev` or a missing file); print each as current, behind, or unknown and, when any is not current, the `scripts/install.sh` curl command. No self-update; exit `1` on network failure.
  * `help` (also `-h`, `--help`): print usage for every subcommand.
  * Browsers open through `$BROWSER` when set, else the platform opener.

---

## 7. Installer & Release Requirements

Both skills declare the MIT license and their pre-approved file tools in `SKILL.md` frontmatter and include the repository's license notice in their skill directory. In hosts that honor path-scoped tool rules, `memoir` pre-approves writes to active Markdown fragments in the default store and `memoir-wiki` pre-approves writes to wiki files there. Shell commands, custom store locations, and repository mirror writes use the host's configured permissions.

* **FR-6.1 (`scripts/install.sh`):** Idempotent Bash installer supporting `--skills-only`, `--ui-only`, `--store <path>`, and `--version <YYYY.M.N>`:
  1. When `--version` is unset inside a local checkout, install skills from `skills/`; otherwise download `memoir-skills.tar.gz` from the target (or latest) GitHub Release and verify its SHA-256 against `SHA256SUMS` (falling back to `main.tar.gz` only when `--version` is unset and no release archive is available).
  2. Copy `memoir` and `memoir-wiki` as real directories (no symlinks) into `~/.agents/skills/` and into `~/.claude/skills/`, `~/.codex/skills/`, `~/.pi/agent/skills/`, and `~/.gemini/antigravity/skills/` whenever each CLI's root directory (`~/.claude`, `~/.codex`, `~/.pi/agent`, `~/.gemini/antigravity`) exists (creating the `skills/` subdirectory if absent, migrating any legacy symlink pointing to `~/.agents/skills/<name>` into a real copy, and refusing foreign symlinks or non-directory files).
  3. Download the matching OS/arch `memoir-ui` binary from GitHub Releases, verify its SHA-256 against `SHA256SUMS`, and install into `~/.local/bin/memoir-ui` (falling back to `go install ./dashboard` when `--version` is unset and Go is installed locally).
  4. Initialize `~/.memoir/` if absent and verify write access to `$STORE_ROOT`.
  5. When installing skills (default or `--skills-only`), idempotently grant read/write access to `$STORE_ROOT` in detected CLI configurations (`~/.claude/settings.json`, `~/.codex/config.toml`, `~/.gemini/antigravity-cli/settings.json`, and `~/.pi/agent/sandbox.json` if present) without overwriting malformed user configs.
  6. Record all written artifacts (copied skill directories, newly created parent directories, `memoir-ui` binary) and CLI config edits (`created_file` and exact entries added) in `$STORE_ROOT/manifest.json` (`schema_version: 1`), atomically merging across repeat and partial installs so prior `created_parents`, `created_file`, and `config_edits` records are preserved.
  7. Finish by printing one line naming each installed component and its version, e.g. `Installed memoir 2026.11.4, memoir-wiki 2026.11.4, memoir-ui 2026.11.4`. A skill's version is its `VERSION` file, or `dev` when installed from a checkout (any stale `VERSION` from an earlier release is removed first); `memoir-ui`'s is its `--version` output, or `unknown` if that fails.
* **FR-6.2 (Versioning & Unified Release Workflow):** Releases use bare, 1-based, non-zero-padded CalVer tags (`YYYY.M.N`, e.g., `2026.11.3`, `2027.1.1`, validated by `^[0-9]{4}\.([1-9]|1[0-2])\.[1-9][0-9]*$`) so every version is also valid semver. The release tag supplies every artifact version. Packaging writes the tag to both the `VERSION` file and the `SKILL.md` frontmatter string `metadata.version` in each skill folder of `memoir-skills.tar.gz`. The dashboard embeds the tag via `-ldflags` for `--version`. Source skill files, `plugin.json`, and `memoir.py` stay unversioned. Tags are never pushed by hand: `.github/workflows/release.yml` runs only on `workflow_dispatch` from `main` (one run at a time), computes the next tag with `scripts/next-version.sh` (the current UTC year and month, `N` = highest existing `N` for that month + 1), runs the CLI, installer, and dashboard test suites, packages `memoir-skills.tar.gz` (`memoir/` and `memoir-wiki/`), cross-compiles static `memoir-ui` binaries (`darwin-arm64`, `darwin-amd64`, `linux-amd64`, `linux-arm64`), and publishes all assets alongside a unified `SHA256SUMS` file as the GitHub Release marked Latest, creating the tag at the built commit. It then fast-forwards (never force-pushes) the `stable` branch to that commit, so rev-pinning managers such as athena can follow releases with `#stable` or pin one with `#<tag>`.
* **FR-6.3 (`scripts/uninstall.sh`):** Idempotent, self-contained Bash + stdlib Python 3.11+ uninstaller supporting `--skills-only`, `--ui-only`, `--store <path>`, and `--dry-run`:
  1. Read `$STORE_ROOT/manifest.json`; exit `0` cleanly when absent, and fail non-zero without side effects on malformed or unsupported manifests.
  2. Validate canonical safety boundaries (never removing `/`, `$HOME`, `$STORE_ROOT`, or any user data directory; only removing recorded skill copies named `memoir`/`memoir-wiki`, the recorded `memoir-ui` binary, and empty `created_parents` strictly inside `$HOME`).
  3. Roll back recorded CLI `config_edits` (`~/.claude/settings.json`, `~/.codex/config.toml`, `~/.gemini/antigravity-cli/settings.json`, `~/.pi/agent/sandbox.json`), removing only the entries added by `install.sh` while preserving user keys, comments, formatting, and file permissions; remove a config file only when `created_file` is `true` and no user keys remain.
  4. On partial uninstalls (`--skills-only` or `--ui-only`), write the remaining `manifest.json` entries atomically; when nothing remains, remove `manifest.json`. Always preserve all Memoir store data (`repos/`, `pinned/`, `standalone/`, `pinned.json`, `config.toml`).

---

## 8. Non-Functional Requirements

* **NFR-1.1 (Python Portability):** `memoir.py` MUST run on Python 3.11+ using only standard library modules (`pathlib`, `hashlib`, `json`, `subprocess`, `argparse`, `datetime`, `shutil`).
* **NFR-1.2 (Go Portability):** `dashboard/` MUST compile to a single static binary with zero runtime dependencies.
* **NFR-2.1 (Local-First Privacy):** All memory, wiki, and search index data MUST remain strictly local on the user's filesystem.
* **NFR-3.1 (Path Determinism):** LLMs MUST NEVER guess storage paths; all fragment writes MUST target the exact path returned by `memoir.py prompt`.
