# Memoir

Project-scoped memory for LLM CLI sessions (Claude Code, Codex, Antigravity). Memoir writes decisions, logs, references, feedback and a compact state snapshot as Markdown files inside your repository. You can clear a long chat whenever it starts to drift and reload a curated context with one command. It needs no MCP server, no daemon and no global config, so it works inside sandboxes that block writes to global memory.

Full requirements: [system_requirements_document_memoir_skill.md](system_requirements_document_memoir_skill.md).

## Install

Requires Python 3.11+. [`uv`](https://docs.astral.sh/uv/) is optional.

```sh
ln -s "$PWD/skills/memoir" ~/.claude/skills/memoir
```

Restart Claude Code. `/memoir` is now available in every project.

## Usage

Inside the agent CLI:

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

The clear loop:

```
/memoir coach
/clear
/memoir reload
```

When `[text]` is empty, the content is extracted from the recent conversation.

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
| `init` | Creates `active/` and `archive/` |
| `prompt` | Prints the absolute `active/` path for LLM injection |
| `path` | Prints the resolved store directory |
| `archive <files>` | Moves fragments to `archive/` as `YYYYMMDD-<name>` and never overwrites |
| `archive --superseded` | Archives every decision named on another decision's `Supersedes:` line, writing a `Superseded-By:` back-link into each archived copy |
| `resume` | Prints the path and the files to load, `state-current.md` first |

For agents without shell access, run `memoir.py resume | pbcopy`, clear the chat, and paste.

## Store location

First match wins:

1. `$MEMOIR_STORE`
2. Git root: `<git-root>/.agents/memoir/`
3. Outside Git, with `MEMOIR_USE_GLOBAL=true`: `${XDG_CONFIG_HOME:-~/.config}/memoir/memories/{hash}/`
4. `$PWD/.agents/memoir/`

For the default Git-root store, every `memoir.py` command except `path` adds `.agents/memoir/` to the repository `.gitignore` (idempotent, append-only) so local memory stays out of version control and never pollutes pull requests. It is skipped when `$MEMOIR_STORE` points elsewhere, outside Git, or when `.gitignore` already names `.agents/`.

## Test

```sh
python3 test_memoir.py
```

## License

[MIT](LICENSE)
