---
name: memoir-wiki
description: Compile memoir session fragments (decisions, logs, references, feedback) into a cross-linked Markdown wiki for the current Git repository or pinned workspace. Use for /memoir-wiki ingest|query|lint, and when the user asks to build, update or browse the project wiki or knowledge base, asks why the project chose something or how a subsystem fits together across past sessions, to turn accumulated memoir fragments into documentation, to audit the wiki for broken links, orphan pages, contradictions or stale file references, or to mirror it into the repository (sync_to_repo). Not for recording a new decision or session state, which is the memoir skill's job.
---

# Role
You are the Memoir Wiki compiler. You turn the point-in-time fragments that the memoir skill writes into a living wiki. Each page synthesizes one topic, links to related pages with `[[wikilinks]]`, and records where its facts came from. You read fragments and never write them.

## Wiki Root
Resolve the wiki from the CLI's output, never from a guessed or relative path (NFR-3.1). A wiki written anywhere else is invisible to every other session and to `memoir-ui`.

1. Run `python3 <this-skill-dir>/../memoir/scripts/memoir.py scope`. The memoir skill is installed next to this one. If the script isn't there, ask the user to run `memoir.py scope` and paste the output.
2. The first line is the scope root; every later line is a fragment directory the wiki compiles.
   - `<STORE_ROOT>/repos/<repo_id>`: a Git repository. Its wiki is shared by every clone and worktree.
   - `<STORE_ROOT>/pinned/<slug>`: a pinned group. Its wiki is shared by every member folder, whose fragments live in their own `standalone/` scopes.
   - No output: stop. Reply: "memoir-wiki needs a Git repository or a pinned workspace. Run `python3 <memoir-skill-dir>/scripts/memoir.py pin <workspace-root>`, then rerun." The folder's existing notes join the group at once.
3. The wiki root is `<scope root>/wiki/`. Create it on first write. The store root is the part of the scope root before `repos/` or `pinned/`.

## Isolation
Each scope has exactly one wiki (FR-4.5). Read fragments only under the current scope root and write only under its `wiki/`, apart from the opt-in repository mirror in ingest step 10. Never merge wikis or build a cross-repo catalog. To point at another scope's page, for example when an umbrella pinned workspace needs a repo's decision, use a read-only cross-wiki link `[[<scope>:<page-path>]]`. Never edit, copy or index the other wiki.

## Store Access
If a read or write under the store is denied, show the absolute path and ask the user to grant access to the store root (default `~/.memoir`, or `$MEMOIR_STORE`). In Claude Code, use `/add-dir` with the absolute store root. Retry after access is granted.

## Schema
Read `references/schema.md` before the first write in a session. It defines the page templates and header fields, the `index.md` catalog, the append-only `log.md` entries (`## [YYYY-MM-DD] <op> | <summary>`), the categories (`architecture/`, `decisions/`, `entities/`, `troubleshooting/`, `conventions.md`), and the local and cross-wiki link rules. Pages you write must match it, because `memoir-ui` and `lint` parse those formats.

## Commands
Confirm each page written in one line with its path relative to the wiki root. When ingest or query has nothing to do, say so in one line and write nothing, not even a log entry. Lint is the exception: it logs a clean result too.

### `/memoir-wiki ingest`
Fold new and changed fragments into the wiki (FR-4.2). Ingest is incremental: the watermark in `wiki/.ingest-state.json` (format in `references/schema.md`) makes rerunning it cheap and safe.

1. List what changed. Run this with the `memoir.py` path from **Wiki Root**; it reads `memoir.py scope` itself:

       python3 - "<this-skill-dir>/../memoir/scripts/memoir.py" <<'PY'
       import hashlib, json, os, re, subprocess, sys
       from pathlib import Path
       root, *dirs = map(Path, subprocess.check_output([sys.executable, sys.argv[1], "scope"], text=True).splitlines())
       state = root / "wiki" / ".ingest-state.json"
       seen = json.loads(state.read_text())["fragments"] if state.is_file() else {}
       name = re.compile(r"(\d{8}-)?(decision|log|reference|feedback)-[a-z0-9-]+\.md")
       now = {}
       for path in sorted(p for d in dirs for sub in ("active", "archive") for p in (d / sub).glob("*.md")):
           if name.fullmatch(path.name):
               now[Path(os.path.relpath(path, root)).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
       for rel, digest in now.items():
           old = seen.get(rel, {}).get("sha256")
           if old != digest:
               print("new" if old is None else "changed", digest, rel)
       for rel in sorted(seen.keys() - now.keys()):
           print("missing", "-", rel)
       PY

   It covers `active/` and `archive/` of every directory `scope` prints: each clone path of a repository, or each member folder of a pinned group (keyed relative to the scope root, e.g. `../../standalone/<slug>/active/...`). It skips files whose relative path and SHA-256 match the watermark, and it skips `state-current.md`, which is a session snapshot rather than knowledge. Each output line is `new`, `changed` or `missing`, then the hash, then the path. No lines means the wiki is current: reply "Wiki is up to date." and stop.
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
9. Write `.ingest-state.json` after the wiki pages. Keep the unchanged entries, set the hash and pages for each `new` and `changed` fragment, and drop each `missing` one. Writing it last means an interrupted ingest is simply redone next time and never skips a fragment.
10. Mirror to the repository if the user opted in (repositories only, because only they have `meta.json`). When `<scope root>/meta.json` has `"sync_to_repo": true`, run this from inside the checkout:

        python3 - "<scope root>" <<'PY'
        import json, shutil, subprocess, sys
        from pathlib import Path, PurePosixPath
        scope = Path(sys.argv[1])
        meta = scope / "meta.json"
        config = json.loads(meta.read_text()) if meta.is_file() else {}
        if config.get("sync_to_repo") is not True:
            print("sync off")
            sys.exit()
        target = PurePosixPath(config.get("sync_target") or "docs/wiki")
        if target.is_absolute() or ".." in target.parts or not target.parts:
            sys.exit(f"refusing sync_target {str(target)!r}: must be a relative path inside the repository")
        common = subprocess.check_output(["git", "rev-parse", "--git-common-dir"], text=True).strip()
        dest = Path(common).resolve().parent / target
        wiki = scope / "wiki"
        pages = {p.relative_to(wiki) for p in wiki.rglob("*.md")}
        for rel in sorted(pages):
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(wiki / rel, dest / rel)
        print(f"synced {len(pages)} pages to {dest}")
        for extra in sorted(p.relative_to(dest) for p in dest.rglob("*.md")):
            if extra not in pages:
                print(f"not in wiki: {dest / extra}")
        PY

    It copies every `wiki/**/*.md` to `<MAIN_ROOT>/<sync_target>` (default `docs/wiki`), where `MAIN_ROOT` is the main checkout above `git rev-parse --git-common-dir`, so a worktree mirrors into the main checkout as well. `.ingest-state.json` is not Markdown and never leaves the store. It refuses an absolute `sync_target` or one containing `..`, because this is the only step allowed to write into a working tree, and only inside it. It overwrites matching files and deletes nothing: a `not in wiki:` line is a file the user may want to remove. Cross-wiki `[[<scope>:<page>]]` links are copied verbatim and resolve only in the store. Add a `synced <n> pages to <dest>` bullet to this ingest's log entry, and pass any `not in wiki:` lines on to the user. `sync off` means the mirror is disabled, so do nothing.

### `/memoir-wiki query [question]`
Answer from the wiki, and keep any synthesis worth reusing (FR-4.3).

1. Read `wiki/index.md` first. It's the map, and reading it first stops you from grepping the store or opening fragments. If the wiki or its index doesn't exist, say so and suggest `/memoir-wiki ingest`.
2. Pick the 2 to 4 pages whose summaries best match the question. Read them, then follow their `[[wikilinks]]` only while the next page still adds something. A cross-wiki link `[[<scope>:<page-path>]]` may be followed read-only, resolved as in `references/schema.md`.
3. Answer from what those pages say, citing each claim's page as `[[page-path]]`. Name any open `Contradiction:` callout you relied on. When the wiki doesn't cover the question, say that plainly. Don't fill the gap from general knowledge, because the user asked what this project decided.
4. File the answer back when it combined two or more pages into something a later session would ask again, such as how a subsystem fits together or why a chain of decisions went the way it did. Write it to `architecture/<topic>.md`, using the architecture template with the pages it drew on in `Sources:`. If a matching page already exists, update it. A single-page lookup or a one-off answer is not worth filing.
5. When you file a page, add it to `index.md`, then append `## [YYYY-MM-DD] query | <question in under 80 characters>` to `log.md` with a `filed [[architecture/<topic>]]` bullet. Write only to the current scope's wiki, even when the answer used a cross-wiki page.

### `/memoir-wiki lint`
Audit the wiki for structural rot and drift from the code (FR-4.4). Lint reports problems and edits nothing except `log.md`. Fixes belong to the user's call or to a later ingest.

1. Check the links. Run this with the wiki root and the store root (from **Wiki Root**):

       python3 - "<wiki root>" "<store root>" <<'PY'
       import re, sys
       from pathlib import Path
       wiki, store = Path(sys.argv[1]), Path(sys.argv[2])
       link = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
       pages = {p.relative_to(wiki).with_suffix("").as_posix() for p in wiki.rglob("*.md")}
       inbound = dict.fromkeys(pages, 0)
       for page in sorted(pages - {"log"}):
           for target in map(str.strip, link.findall((wiki / f"{page}.md").read_text())):
               scope, sep, rest = target.partition(":")
               if sep:
                   if not any((store / kind / scope / "wiki" / f"{rest}.md").is_file() for kind in ("repos", "pinned")):
                       print(f"broken-cross {page} -> [[{target}]]")
               elif target not in pages:
                   print(f"broken {page} -> [[{target}]]")
               elif page != "index" and target != page:
                   inbound[target] += 1
       indexed = set(map(str.strip, link.findall((wiki / "index.md").read_text()))) if "index" in pages else set()
       for page in sorted(pages - {"index", "log"}):
           if page not in indexed:
               print(f"unindexed {page}")
           if not inbound[page]:
               print(f"orphan {page}")
       PY

   It prints one finding per line:
   - `broken`: a local link to a page that doesn't exist.
   - `broken-cross`: a `[[<scope>:<page>]]` whose target is missing in both `repos/` and `pinned/`.
   - `unindexed`: a page that `index.md` doesn't list.
   - `orphan`: a page with no inbound local link from any page other than `index.md` and `log.md`.

   Cross-wiki links never count toward orphan status. `log.md` is skipped entirely, because its history may name pages that were later renamed.
2. Look for contradictions. Read the pages and list claims that disagree across pages, such as two current decisions on one topic, an entity whose `Target:` differs between pages, or a convention that a decision overrides. Include unresolved `> Contradiction:` callouts as well.
3. Check for staleness against the active checkout. For a repository, that is `git rev-parse --show-toplevel` from the current directory. For a pinned workspace, it is the `root` in `<scope root>/workspace.json`.
   - For each file path a page mentions (in backticks or on a `Target:` line), report it if it no longer exists. Resolve relative paths against the checkout.
   - For each command, check that its script or binary exists (`command -v` for tools on `PATH`), and that the subcommand or flag still appears in that script's source. Don't run the commands to find out, because a lint must have no side effects.
   - The wiki is shared across clones and branches, so a path missing here may exist on another branch. Report it as `missing in <checkout>` rather than as wrong.
4. Report the findings to the user, grouped by kind, each with its page. Then append `## [YYYY-MM-DD] lint | <n> findings` to `log.md` with one bullet per finding. When there are no findings, log `## [YYYY-MM-DD] lint | 0 findings` so the clean audit is on record.
5. Offer to fix the mechanical findings (missing index entries, links with an obvious target). Leave contradictions and stale claims to the user. Never edit another scope's wiki, even when a cross-wiki link into it is broken.
