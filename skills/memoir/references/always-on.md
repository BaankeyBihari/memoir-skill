# Always On

Paste this block into `~/.claude/CLAUDE.md` (all projects), a repository's `CLAUDE.md` (one project), or `AGENTS.md` (Codex and other agents) to make memoir the default memory.

```markdown
## Memory: memoir
- Record decisions with the `memoir` skill. When I choose among alternatives or say "decision:" / "let's go with X", write a decision fragment (`/memoir decision`) without being asked. Don't keep decisions anywhere else.
- Record milestones and blocking errors with `/memoir log`, and external paths or docs with `/memoir reference`.
- When I state a standing preference for how we work (communication, review, structure), record it with `/memoir feedback`.
- After finishing a task step, or before the context gets long, update `/memoir state`.
- When I say "resume" or start a session on unfinished work, run `/memoir reload`.
```
