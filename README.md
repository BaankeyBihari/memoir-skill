# Memoir

Local-first memory, session compaction, and cumulative knowledge management for LLM CLI sessions (Claude Code, Codex CLI, Antigravity, Pi). Memoir stores structured Markdown fragments and compiled project wikis under `~/.memoir` (or `$MEMOIR_STORE`) without polluting repository working trees, paired with a zero-dependency Go web browser (`memoir-ui`).

Full specifications: [system_requirements_document_memoir_skill.md](system_requirements_document_memoir_skill.md) and [SPEC.md](SPEC.md).

## Components

- **`skills/memoir`**: High-frequency session compaction into typed Markdown fragments (`decision`, `log`, `reference`, `feedback`, `state-current.md`) for instant `CLEAR` / `reload` cycles.
- **`skills/memoir-wiki`**: Cumulative knowledge compiler (`ingest`, `query`, `lint`) that synthesizes fragments across clones and worktrees into interlinked `wiki/` pages with `[[wikilinks]]`.
- **`dashboard/` (`memoir-ui`)**: Single-binary Go HTTP viewer with `embed.FS` assets, 7 color themes, `fsnotify` SSE live reload, `[[wikilink]]` & backlink navigation, decision supersession graphs, `Cmd+K` search, and safe orphan pruning.

## Install

Requires Python 3.11+. [`uv`](https://docs.astral.sh/uv/) is optional; Go 1.23+ is only needed if building `memoir-ui` from source when no release binary matches.

**Unified installer** (copies both skills to `~/.agents/skills/` and detected agent CLIs, configures store permissions for `~/.memoir` in detected CLI configs, installs `memoir-ui` to `~/.local/bin/memoir-ui` with SHA-256 verification, and records written artifacts in `~/.memoir/manifest.json`):

```sh
curl -fsSL https://raw.githubusercontent.com/BaankeyBihari/memoir-skill/main/scripts/install.sh | bash
```

Installer flags:

| Flag | Effect |
|---|---|
| `--skills-only` | Install only `memoir` and `memoir-wiki` skills |
| `--ui-only` | Install only the `memoir-ui` binary |
| `--store <path>` | Initialize a custom store path instead of `~/.memoir` |
| `--version <YYYY.M.N>` | Pin a specific release tag (e.g. `2026.11.3`) |

### Uninstall

Uses `$MEMOIR_STORE/manifest.json` (`~/.memoir/manifest.json` by default) to remove copied skills, `memoir-ui`, empty installer-created parent directories, and CLI config entries added during install while preserving all stored memories and wikis:

```sh
curl -fsSL https://raw.githubusercontent.com/BaankeyBihari/memoir-skill/main/scripts/uninstall.sh | bash
```

Uninstaller flags:

| Flag | Effect |
|---|---|
| `--skills-only` | Remove installed skills and revert CLI store permissions only |
| `--ui-only` | Remove the `memoir-ui` binary only |
| `--store <path>` | Read manifest from a custom store path instead of `~/.memoir` |
| `--dry-run` | Print planned removals and config reversions without modifying disk |

### Manual skill symlinks (Claude Code)

```sh
ln -s "$PWD/skills/memoir" ~/.claude/skills/memoir
ln -s "$PWD/skills/memoir-wiki" ~/.claude/skills/memoir-wiki
```

### Antigravity (`agy`)

```sh
agy plugin install https://github.com/BaankeyBihari/memoir-skill
```

Or inside an interactive `agy` session: `/plugin install https://github.com/BaankeyBihari/memoir-skill`.

## Usage

### Session compaction (`memoir`)

| Command | Effect |
|---|---|
| `/memoir decision [text]` | Writes `decision-{slug}.md`, recording any decision it supersedes |
| `/memoir log [text]` | Writes `log-{slug}.md` |
| `/memoir reference [text]` | Writes `reference-{slug}.md` |
| `/memoir feedback [text]` | Writes `feedback-{slug}.md`, a durable collaboration or working-style preference |
| `/memoir state` | Overwrites `state-current.md` (Goal, Completed, Blocked/Pending, Next Action) |
| `/memoir capture` | Writes every unrecorded decision, log, reference and feedback from the conversation, then updates `state-current.md` |
| `/memoir coach` | Captures, then recommends CONTINUE, COMPACT or CLEAR with evidence and paste-ready next steps |
| `/memoir reload` | Archives superseded decisions and loads the last recorded session |
| `/memoir pin [path]` | Groups a non-Git workspace and its subfolders (default current directory): each folder keeps its own notes, `reload` loads the whole group's, state stays per folder |
| `/memoir unpin [path]` | Removes the group; every folder keeps its own notes |

The clear loop:

```
/memoir coach
/clear
/memoir reload
```

When `[text]` is empty, the content is extracted from the recent conversation.

### Knowledge compiler (`memoir-wiki`)

| Command | Effect |
|---|---|
| `/memoir-wiki ingest` | Incrementally synthesizes new/changed fragments across clones, worktrees and pinned group members into the scope's shared `wiki/` (and mirrors to the repo when `meta.json` sets `"sync_to_repo": true`) |
| `/memoir-wiki query [question]` | Reads `wiki/index.md` first, traverses `[[wikilinks]]`, answers with citations, and files reusable syntheses under `wiki/architecture/` |
| `/memoir-wiki lint` | Audits `wiki/` for broken local or cross-wiki `[[wikilinks]]`, unindexed pages, orphans, contradictions, and stale file/command references |

### Local web viewer (`memoir-ui`)

```sh
memoir-ui --port 7337 --store ~/.memoir --open
```

- Flags: `--port` (default `7337`), `--store` (defaults to `$MEMOIR_STORE` or `~/.memoir`), `--open`, `--version`.
- Subcommands (each takes `--port`):

| Command | Effect |
|---|---|
| `memoir-ui dashboard` | Start the server in the background (log in your user cache dir under `memoir-ui/`) unless one already runs, then open it in the browser |
| `memoir-ui status` | Print URL, PID, version, and store; exit 1 when not running |
| `memoir-ui shutdown` | Stop the running server (sends `SIGTERM`; there is no HTTP shutdown endpoint) |
| `memoir-ui check-update` | Compare `memoir-ui` and the installed skills with the latest release and print the installer command when behind (the only network call, made only on request) |
| `memoir-ui help` | Show usage |

- Set `$BROWSER` to choose which browser `--open` and `dashboard` launch.
- Features: hierarchical Repos / Pinned Workspaces / Standalone navigation, live `fsnotify` SSE reload (`/events`), Goldmark Markdown with clickable `[[page]]` and `[[scope:page]]` links, inbound backlinks, visual decision supersession chains, `Cmd+K` full-text search with scope/type filters, 7 color themes, and confirmed pruning for orphaned clones/workspaces.

## Always on

To make memoir the default memory, paste this block into `~/.claude/CLAUDE.md` (all projects), a repository's `CLAUDE.md` (one project), or `AGENTS.md` (Codex and other agents). The same block lives in [skills/memoir/references/always-on.md](skills/memoir/references/always-on.md).

```markdown
## Memory: memoir
- Record decisions with the `memoir` skill. When I choose among alternatives or say "decision:" / "let's go with X", write a decision fragment (`/memoir decision`) without being asked. Don't keep decisions anywhere else.
- Record milestones and blocking errors with `/memoir log`, and external paths or docs with `/memoir reference`.
- When I state a standing preference for how we work (communication, review, structure), record it with `/memoir feedback`.
- After finishing a task step, or before the context gets long, update `/memoir state`.
- When I say "resume" or start a session on unfinished work, run `/memoir reload`.
```

## CLI

`skills/memoir/scripts/memoir.py` runs directly through its `uv` shebang, or with `python3`.

| Command | Effect |
|---|---|
| `gc [--dry-run] [--prune]` | Reports scopes with missing source directories. Use `--prune` to delete each reported clone or pinned workspace, including its stored contents. |
| `pin [path]` / `unpin [path]` | Register or remove a non-Git workspace root (default current directory). The longest matching ancestor wins. Pinning moves no files. |
| `init` | Creates `active/` and `archive/` |
| `prompt` | Prints the absolute `active/` path for LLM injection |
| `path` | Prints the resolved store directory |
| `scope` | Prints the wiki scope root (repository or pinned group), then each fragment directory it covers |
| `archive <files>` | Moves fragments to `archive/` as `YYYYMMDD-<name>` and never overwrites |
| `archive --superseded` | Archives every decision named on another decision's `Supersedes:` line, writing a `Superseded-By:` back-link into each archived copy |
| `resume` | Prints the path and the files to load, `state-current.md` first |

For agents without shell access, run `memoir.py resume | pbcopy`, clear the chat, and paste.

## Store location

The default store is `~/.memoir`. Set `MEMOIR_STORE` to override its root. Run `memoir.py path` in your working directory to find its fragment store. Grant your agent write access to the store root if the CLI reports exit code 3. See [SPEC.md](SPEC.md) for the project, clone, worktree, pinned, and standalone layout.

## Releases

Releases use bare, 1-based, non-zero-padded CalVer tags (`YYYY.M.N`, e.g., `2026.11.3`, `2027.1.1`), so every version is also valid semver. The tag is the only version: skills and `plugin.json` carry none. Maintainers cut a release with `gh workflow run release.yml --ref main`, which computes the next tag, marks the release Latest, and fast-forwards the `stable` branch. Each release publishes:

- `memoir-skills.tar.gz` (`memoir` and `memoir-wiki`)
- `memoir-ui-{darwin,linux}-{arm64,amd64}` static binaries
- `SHA256SUMS` covering all release assets

With [athena](https://github.com/BaankeyBihari/athena), follow releases through the `stable` branch, or pin one release by its tag:

```sh
athena add github.com:BaankeyBihari/memoir-skill#stable:/skills/memoir
athena add github.com:BaankeyBihari/memoir-skill#2026.11.3:/skills/memoir
```

## Test

```sh
python3 test_memoir.py
python3 scripts/test_install.py
cd dashboard && go test -race ./...
```

## License

[MIT](LICENSE)
