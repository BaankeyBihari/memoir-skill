# Memoir filesystem contract

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
├── pinned/                                        # Scope 2: Groups over standalone scopes (no fragments)
│   └── <project-slug>--<sha8>/                    # e.g., research--4d5e6f7a
│       ├── workspace.json                         # {"root": "/abs/path/to/pinned/root", "last_seen": "..."}
│       ├── wiki/                                  # Compiled by memoir-wiki across all group members
│       └── paths/                                 # Legacy pre-group fragments, copied out lazily
└── standalone/                                    # Scope 3: Every non-Git directory (flat), pinned or not
    └── <project-slug>--<sha8>/                    # e.g., scratch-script--8b9c0d1e
        ├── scope.json                             # {"root": "/abs/path/to/directory", "last_seen": "..."}
        ├── active/
        └── archive/
```

## Identity and routing

Use canonical absolute paths. Hash the UTF-8 path string with SHA-256 and take
the first eight lowercase hexadecimal digits. A scope ID is a lowercase basename
with runs outside `[a-z0-9]` replaced by one hyphen and outer hyphens trimmed
(use `root` for an empty slug), followed by `--` and the hash.

* Git takes precedence. Lowercase the origin host and path, discard scheme,
  credentials, query, fragment and trailing `.git`, and join components with
  `__`. SSH scp syntax and HTTPS identify the same repo. For a local remote,
  use the canonical filesystem path components. Without origin use `local__<clone_id>`.
* The clone slug comes from the parent of the canonical Git common directory.
  Hash the common directory itself. Use `_main` for the main checkout, the
  worktree's relative path for nested worktrees, or its basename for external
  worktrees. Join path components with `__`. Invocation from a Git subdirectory
  uses its checkout's key.
* Outside Git, always hash the current directory and use its flat
  `standalone/` scope, recording the directory in `scope.json`. A pin is a
  group, not a location: the longest pinned ancestor by directory component
  names the group, and its members are the standalone scopes whose
  `scope.json` root has that pin as longest ancestor. Group reads (`resume`,
  `archive --superseded`, `scope`, wiki ingest) flatten members' fragments,
  except `state-current.md`, which stays per directory. Unpinning moves
  nothing.
* v1 stores (`<toplevel-or-cwd>/.agents/memoir`, `.claude/memoir`,
  `~/.config/memoir/memories/<sha8>`) are copied into an empty resolved scope
  on first use and left in place (SRD FR-1.7). Legacy pre-group
  `pinned/<slug>/paths/<key>` fragments are copied into the directory's
  standalone scope, and a standalone scope into its repository scope after
  `git init`, the same way. A store root containing
  `active/` is a v1 base directory and is rejected (SRD FR-1.8).

## Wiki scopes and links

Each Git repository has one wiki at `repos/<repo_id>/wiki/`, shared by all of
its clones and worktrees. Each pinned group has one wiki at
`pinned/<slug>/wiki/`, shared by all of its members. Ungrouped standalone
directories have no wiki. Wikis are never merged into a global cross-repo wiki: a wiki is
compiled only from its own scope's fragments, and tools write only to it.

A local link is `[[<page-path>]]`, the page path relative to the wiki root
without `.md` (e.g. `[[decisions/use-env-vars]]`), optionally with a label as
`[[<page-path>|<label>]]`. A cross-wiki link is `[[<scope>:<page-path>]]`,
where `<scope>` is a `repo_id` or a pinned slug. Scope IDs never contain `:`,
so the first `:` separates scope from page. It resolves to
`repos/<scope>/wiki/<page-path>.md`, else `pinned/<scope>/wiki/<page-path>.md`.
Cross-wiki links are read-only pointers: they never add entries to the other
wiki's `index.md` or edit its pages.

## JSON records

All five files are UTF-8 JSON. Missing pinned.json means an empty array.

| File | JSON shape | Meaning |
| --- | --- | --- |
| clone.json | `{"root":"/main/checkout","last_seen":"2026-01-01T00:00:00+00:00"}` | Required strings, canonical main checkout and ISO-8601 timestamp |
| scope.json | `{"root":"/directory","last_seen":"2026-01-01T00:00:00+00:00"}` | Required strings, canonical non-Git directory of a standalone scope and ISO-8601 timestamp |
| workspace.json | `{"root":"/workspace","last_seen":"2026-01-01T00:00:00+00:00"}` | Required strings, canonical pinned root and ISO-8601 timestamp |
| meta.json | `{"remote":"https://host/owner/repo","sync_to_repo":false,"sync_target":"docs/wiki"}` | Optional repo configuration. Remote is a string, mirror flag a boolean (default false), target a repo-relative directory string (default docs/wiki). |
| pinned.json | `["/absolute/workspace"]` | Array of unique canonical absolute directory strings |

## Fragment headers

Fragments are Markdown with plain line-oriented fields directly below the title.
Archive names prepend the local date as `YYYYMMDD-`. Automatic supersession
inserts `Superseded-By: decision-<slug>.md` after the older decision's
`Supersedes:` field before moving the file.

Filenames are lowercase kebab-case with no underscores, spaces or uppercase letters (e.g. `decision-use-env-vars.md`), because `archive` and the `Supersedes:` matcher only recognize that shape; any other name can never be archived or superseded. Use exactly these prefixes:
1. `decision-{slug}.md`: explicit architectural choices, constraints or tool selections.
2. `state-current.md`: the single dynamic snapshot of current progress.
3. `log-{slug}.md`: major events, milestones or blocking errors.
4. `reference-{slug}.md`: pointers to local file paths, Git repositories or API docs.
5. `feedback-{slug}.md`: durable collaboration or working-style preferences (e.g. "show trade-off axes before a recommendation", "prefer minimal diffs"). Retention is judgement-based like decisions, logs and references; there is no active-count cap.

The slug is 2 to 5 words describing the content. If the file already exists, append `-2`, `-3`, and so on. Only `state-current.md` is ever overwritten.

Decision:

    # <Title>
    Date: YYYY-MM-DD
    Supersedes: <decision-filename.md | none>
    Decision: <one or two sentences>
    Why: <one or two sentences>
    Alternatives: <rejected options and why | none>
    Deferred: <what was postponed and when to revisit | none>

Log:

    # <Title>
    Date: YYYY-MM-DD
    Event: <what happened>
    Impact: <what it changes or blocks>

Reference:

    # <Title>
    Target: <absolute path | URL>
    Why: <when to consult it>

Feedback:

    # <Title>
    Date: YYYY-MM-DD
    Feedback: <the durable collaboration or style preference, stated as a rule>
    Why: <when it applies, or the correction that prompted it>

State (max 3 bullets per section):

    # Session State
    Updated: YYYY-MM-DD
    ## Goal
    - <current objective>
    ## Completed
    - <what was just done>
    ## Blocked/Pending
    - <current errors or open threads>
    ## Next Action
    - <the exact next step>
