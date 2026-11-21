---
name: memoir-wiki
description: Compile memoir session fragments (decisions, logs, references, feedback) into a cross-linked Markdown wiki for the current Git repository or pinned workspace. Use for /memoir-wiki ingest|query, and when the user asks to build, update or browse the project wiki or knowledge base, asks why the project chose something or how a subsystem fits together across past sessions, to turn accumulated memoir fragments into documentation, or to see how earlier sessions' decisions fit together. Not for recording a new decision or session state, which is the memoir skill's job.
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

# Commands
Confirm each page written in one line with its path relative to the wiki root. When a command finds nothing to do, say so in one line and write nothing, not even a log entry.

## `/memoir-wiki ingest`
Fold new and changed fragments into the wiki (FR-4.2). Ingest is incremental: the watermark in `wiki/.ingest-state.json` (format in `references/schema.md`) makes rerunning it cheap and safe.

1. List what changed. Run this with the scope root from **Wiki Root**:

       python3 - "<scope root>" <<'PY'
       import hashlib, json, re, sys
       from pathlib import Path
       root = Path(sys.argv[1])
       state = root / "wiki" / ".ingest-state.json"
       seen = json.loads(state.read_text())["fragments"] if state.is_file() else {}
       name = re.compile(r"(\d{8}-)?(decision|log|reference|feedback)-[a-z0-9-]+\.md")
       now = {}
       for path in sorted(root.glob("**/paths/*/*/*.md")):
           if path.parent.name in ("active", "archive") and name.fullmatch(path.name):
               now[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
       for rel, digest in now.items():
           old = seen.get(rel, {}).get("sha256")
           if old != digest:
               print("new" if old is None else "changed", digest, rel)
       for rel in sorted(seen.keys() - now.keys()):
           print("missing", "-", rel)
       PY

   It covers `clones/*/paths/*/active/` and `archive/` for a repository, and `paths/*/active/` and `archive/` for a pinned workspace. It skips files whose relative path and SHA-256 match the watermark, and it skips `state-current.md`, which is a session snapshot rather than knowledge. Each output line is `new`, `changed` or `missing`, then the hash, then the path. No lines means the wiki is current: reply "Wiki is up to date." and stop.
2. Read each `new` and `changed` fragment. For `changed`, also read the pages its watermark entry lists. Read `index.md` and every page you're about to touch before editing it, so you merge with what's there rather than overwrite it.
3. Synthesize each fragment into the page for its topic, using the templates in `references/schema.md`:
   - `decision-*.md`, active or archived, goes to `decisions/<topic>.md`.
   - `reference-*.md` goes to `entities/<name>.md`. References with the same `Target:` share a page.
   - `log-*.md` goes to `troubleshooting/<area>.md`.
   - `feedback-*.md` goes to `conventions.md`.

   Write the fact in the page's own words and merge it into the existing page; never paste the fragment in. A wiki of raw copies is just a second, worse archive. Add `[[wikilinks]]` to related pages, and add the fragment's path to `Sources:`.
4. Keep supersession history. A decision whose `Supersedes:` names an older decision updates that decision's page: the new choice becomes `## Current`, and the old one moves to `## History` with its date and the reason it was replaced. An archived `YYYYMMDD-decision-<slug>.md` with a `Superseded-By:` line is usually the same decision as an already-ingested `active/decision-<slug>.md` that now shows as `missing`. Treat that as a move: update `Sources:` and `Status:`, and don't create a second page. If the replacement lives on a different topic page, set `Status: superseded` and `Superseded-By: [[decisions/<page>]]`.
5. Flag conflicts instead of resolving them silently. When a fragment contradicts a page and no supersession chain explains it, for example two worktrees that decided differently, keep both claims under a `> Contradiction:` callout and list it in the log entry. Only the user can say which one is right.
6. For a `missing` fragment that isn't a move, keep the wiki content, because knowledge outlives a pruned clone. Drop only its watermark entry.
7. Update `index.md` so every page appears once, with a one-line summary.
8. Append one entry to `log.md` (create the file with `# Wiki Log` if it's absent): `## [YYYY-MM-DD] ingest | <n> fragments: <counts by type>`, with one bullet per page created or updated and one per contradiction.
9. Write `.ingest-state.json` last. Keep the unchanged entries, set the hash and pages for each `new` and `changed` fragment, and drop each `missing` one. Writing it last means an interrupted ingest is simply redone next time and never skips a fragment.

## `/memoir-wiki query [question]`
Answer from the wiki, and keep any synthesis worth reusing (FR-4.3).

1. Read `wiki/index.md` first. It's the map, and reading it first stops you from grepping the store or opening fragments. If the wiki or its index doesn't exist, say so and suggest `/memoir-wiki ingest`.
2. Pick the 2 to 4 pages whose summaries best match the question. Read them, then follow their `[[wikilinks]]` only while the next page still adds something. A cross-wiki link `[[<scope>:<page-path>]]` may be followed read-only, resolved as in `references/schema.md`.
3. Answer from what those pages say, citing each claim's page as `[[page-path]]`. Name any open `Contradiction:` callout you relied on. When the wiki doesn't cover the question, say that plainly. Don't fill the gap from general knowledge, because the user asked what this project decided.
4. File the answer back when it combined two or more pages into something a later session would ask again, such as how a subsystem fits together or why a chain of decisions went the way it did. Write it to `architecture/<topic>.md`, using the architecture template with the pages it drew on in `Sources:`. If a matching page already exists, update it. A single-page lookup or a one-off answer is not worth filing.
5. When you file a page, add it to `index.md`, then append `## [YYYY-MM-DD] query | <question in under 80 characters>` to `log.md` with a `filed [[architecture/<topic>]]` bullet. Write only to the current scope's wiki, even when the answer used a cross-wiki page.
