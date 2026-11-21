# memoir-wiki schema

The layout, page formats and link rules for a compiled wiki. `SPEC.md` in the
memoir repository is the source of truth for the store layout. This file covers
only what lives under `wiki/`.

## Scope and layout

One wiki per scope, never merged:

- Git repository: `<STORE_ROOT>/repos/<repo_id>/wiki/`, compiled from
  `clones/*/paths/*/active/` and `clones/*/paths/*/archive/`.
- Pinned workspace: `<STORE_ROOT>/pinned/<slug>/wiki/`, compiled from
  `paths/*/active/` and `paths/*/archive/`.
- Standalone directory: no wiki.

```text
wiki/
├── .ingest-state.json     # Processed fragments and their sha256
├── index.md               # Catalog: one line per page
├── log.md                 # Append-only audit trail
├── conventions.md         # From feedback-*.md
├── architecture/          # Cross-cutting syntheses (query filings, subsystem overviews)
├── decisions/             # From decision-*.md, active and archive/
├── entities/              # From reference-*.md
└── troubleshooting/       # From log-*.md
```

Page filenames are lowercase kebab-case `.md`, named for the topic rather than
the fragment (`decisions/store-location.md`, not
`decisions/decision-use-home-dir-2.md`). Keep a page name stable once it
exists, because other pages and other scopes link to it.

## Links

- Local link: `[[<page-path>]]`, where the page path is relative to the wiki
  root and has no `.md`, e.g. `[[decisions/store-location]]` or
  `[[conventions]]`. Add a label with `[[decisions/store-location|store location]]`.
- Cross-wiki link: `[[<scope>:<page-path>]]`, where `<scope>` is a `repo_id`
  (`github.com__owner__repo`, `local__<clone_id>`) or a pinned slug
  (`research--4d5e6f7a`). Scope IDs never contain `:`, so the first `:` splits
  scope from page. It resolves to `<STORE_ROOT>/repos/<scope>/wiki/<page-path>.md`,
  else `<STORE_ROOT>/pinned/<scope>/wiki/<page-path>.md`.
- Cross-wiki links are read-only pointers. Use one when, for example, an
  umbrella pinned workspace needs a specific repo's decision. Never copy the
  other page in, never add it to this wiki's `index.md`, and never edit the
  other wiki.
- Link the first mention of another page's topic in each page, not every
  mention.
- Cite fragments as backticked relative paths (on the `Sources:` line), never as
  wikilinks: fragments are not wiki pages.

## Page header

Pages follow the memoir fragment convention: a `# Title`, then plain
`Field: value` lines directly below it. Don't use YAML frontmatter.

    # <Title>
    Type: decision | entity | troubleshooting | conventions | architecture
    Updated: YYYY-MM-DD
    Sources: <comma-separated fragment paths relative to the scope root | wiki pages for architecture>

Decision pages add `Status: active | superseded`. A superseded page whose
replacement lives on a different page adds `Superseded-By: [[decisions/<page>]]`.

## Page templates

Decision (`decisions/<topic>.md`): one page per decision topic. A newer
decision that supersedes an older one updates the same page.

    # <Topic>
    Type: decision
    Updated: YYYY-MM-DD
    Status: active
    Sources: clones/<clone>/paths/<key>/active/decision-<slug>.md, clones/<clone>/paths/<key>/archive/YYYYMMDD-decision-<old>.md

    ## Current
    <Decision, stated in one or two sentences.> Why: <reason>.

    ## Alternatives
    - <rejected option>: <why>

    ## Deferred
    - <postponed item>: <when to revisit>

    ## History
    - YYYY-MM-DD: <earlier decision>. Superseded YYYY-MM-DD by <newer decision> because <reason>.

    ## Related
    - [[entities/<page>]]

Entity (`entities/<name>.md`): one page per file, repository, service or API
that references point at. References to the same `Target:` merge.

    # <Name>
    Type: entity
    Updated: YYYY-MM-DD
    Sources: <reference fragment paths>

    Target: <absolute path | URL>
    <What it is, in one or two sentences.>

    ## When to consult
    - <situation, from each reference's Why:>

    ## Related
    - [[decisions/<page>]]

Troubleshooting (`troubleshooting/<area>.md`): one page per subsystem or
symptom. Each log becomes a dated entry. Blocking errors keep their fix, and
milestones keep what they changed.

    # <Area>
    Type: troubleshooting
    Updated: YYYY-MM-DD
    Sources: <log fragment paths>

    ## Known issues
    - <symptom>: <cause>. Fix: <fix | open>.

    ## Timeline
    - YYYY-MM-DD: <event>. Impact: <impact>.

    ## Related
    - [[decisions/<page>]]

Conventions (`conventions.md`): the single page for feedback. Group the rules
under themed headings. Each rule keeps its date and why.

    # Conventions
    Type: conventions
    Updated: YYYY-MM-DD
    Sources: <feedback fragment paths>

    ## <Theme, e.g. Code review>
    - <rule> (YYYY-MM-DD). Why: <why>.

Architecture (`architecture/<topic>.md`): a synthesis across several pages,
written by `query` or when several decisions describe one subsystem.

    # <Topic>
    Type: architecture
    Updated: YYYY-MM-DD
    Sources: [[decisions/<a>]], [[entities/<b>]]

    <The synthesis, with a link at each claim's source page.>

    ## Open questions
    - <what the wiki can't answer yet | none>

## Contradictions

When two sources disagree and no `Supersedes:` chain explains it, keep both
claims on the page under a callout, and record it in `log.md`:

    > Contradiction: <claim A> (`<source A>`) vs <claim B> (`<source B>`). Unresolved.

## index.md

The catalog. Every page except `index.md` and `log.md` appears exactly once,
under its category, sorted by page path, with one line of summary. Leave a
category heading out when it has no pages.

    # Wiki Index
    Updated: YYYY-MM-DD

    ## Architecture
    - [[architecture/<topic>]]: <one-line summary>
    ## Decisions
    - [[decisions/<topic>]]: <one-line summary> (superseded)
    ## Entities
    - [[entities/<name>]]: <one-line summary>
    ## Troubleshooting
    - [[troubleshooting/<area>]]: <one-line summary>
    ## Conventions
    - [[conventions]]: <one-line summary>

Mark superseded decision pages with a trailing `(superseded)`.

## log.md

Append-only. Add each entry at the end and never edit or delete an earlier one.
Its history is the audit trail. The file starts with `# Wiki Log`.

    ## [YYYY-MM-DD] <op> | <summary>
    - <created|updated|filed|finding|synced> <detail with [[links]]>

`<op>` is `ingest`, `query` or `lint`. The summary is one line, e.g.
`## [2026-11-21] ingest | 5 fragments: 2 decisions, 2 references, 1 feedback`.

## .ingest-state.json

The ingest watermark, as UTF-8 JSON. Keys are fragment paths relative to the
scope root (`repos/<repo_id>/` or `pinned/<slug>/`), using `/` separators.

```json
{
  "version": 1,
  "fragments": {
    "clones/memoir-skill--a1b2c3d4/paths/_main/active/decision-use-env-vars.md": {
      "sha256": "<64 lowercase hex digits>",
      "pages": ["decisions/configuration.md"]
    }
  }
}
```

`pages` lists the wiki pages the fragment fed, relative to the wiki root, so a
changed fragment can be traced to the pages that need revisiting. A missing
file means nothing has been ingested yet.
