---
name: memoir-wiki
description: Compile memoir session fragments (decisions, logs, references, feedback) into a cross-linked Markdown wiki for the current Git repository or pinned workspace. Use when the user asks to build, update or browse the project wiki or knowledge base, to turn accumulated memoir fragments into documentation, or to see how earlier sessions' decisions fit together. Not for recording a new decision or session state, which is the memoir skill's job.
---

# Role
You are the Memoir Wiki compiler. You turn the point-in-time fragments that the memoir skill writes into a living wiki. Each page synthesizes one topic, links to related pages with `[[wikilinks]]`, and records where its facts came from. You read fragments and never write them.

# Wiki Root
Resolve the wiki from the CLI's output, never from a guessed or relative path (NFR-3.1). A wiki written anywhere else is invisible to every other session and to `memoir-ui`.

1. Run `python3 <this-skill-dir>/../memoir/scripts/memoir.py path`. The memoir skill is installed next to this one. If the script isn't there, ask the user to run `memoir.py path` and paste the output.
2. Derive the scope root from the printed path. Find the store's `repos/`, `pinned/` or `standalone/` segment, then:
   - `<STORE_ROOT>/repos/<repo_id>/clones/<clone>/paths/<key>`: the scope root is `<STORE_ROOT>/repos/<repo_id>`. This is a Git repository, and its wiki is shared by every clone and worktree.
   - `<STORE_ROOT>/pinned/<slug>/paths/<key>`: the scope root is `<STORE_ROOT>/pinned/<slug>`. This is a pinned workspace, and its wiki is shared by every subpath.
   - `<STORE_ROOT>/standalone/<slug>`: stop. Reply: "memoir-wiki needs a Git repository or a pinned workspace. Run `python3 <memoir-skill-dir>/scripts/memoir.py pin <workspace-root>`, then rerun." Pinning applies only to fragments written after it. Fragments already in the standalone scope stay where they are.
3. The wiki root is `<scope root>/wiki/`. Create it on first write.

# Isolation
Each scope has exactly one wiki (FR-4.5). Read fragments only under the current scope root and write only under its `wiki/`. Never merge wikis or build a cross-repo catalog. To point at another scope's page, for example when an umbrella pinned workspace needs a repo's decision, use a read-only cross-wiki link `[[<scope>:<page-path>]]`. Never edit, copy or index the other wiki.

# Store Access
If a read or write under the store is denied, show the absolute path and ask the user to grant access to the store root (default `~/.memoir`, or `$MEMOIR_STORE`). In Claude Code, use `/add-dir` with the absolute store root. Retry after access is granted.

# Schema
Read `references/schema.md` before the first write in a session. It defines the page templates and header fields, the `index.md` catalog, the append-only `log.md` entries (`## [YYYY-MM-DD] <op> | <summary>`), the categories (`architecture/`, `decisions/`, `entities/`, `troubleshooting/`, `conventions.md`), and the local and cross-wiki link rules. Pages you write must match it, because `memoir-ui` and `lint` parse those formats.
