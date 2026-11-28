"""Set up and grade memoir skill eval runs.

    python3 evals/harness.py setup <iteration-dir> [eval-id ...]   # seed run dirs from evals/fixtures
    python3 evals/harness.py observe <run-dir>  # after first response, before delivering the follow-up
    python3 evals/harness.py grade <iteration-dir> [eval-id ...]   # write grading.json + outputs/files-after-run.md

Layout per run: <iteration>/eval-<id>-<name>/<config>/run-1/{store,project,outputs}.
Run the chosen skill and its matching CLI in project/ with MEMOIR_STORE set to
the run's absolute store/ path. Save the user-facing reply in outputs/response.md
and reload operations in outputs/transcript.md. For a case with a followup, run
observe after the first reply, then deliver the followup in the same session.
Save the second reply in outputs/response.md before grading.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

UTF8 = "utf-8"
RESPONSE_MD = "response.md"
TRANSCRIPT_MD = "transcript.md"
STATE_CURRENT_MD = "state-current.md"
DECISION_PREFIX = "decision-"
DECISION_GLOB = "decision-*.md"
DECISION_SQLITE = "decision-use-sqlite.md"
DECISION_PNPM = "decision-use-pnpm.md"
SEC_NEXT_ACTION = "Next Action"
SEC_BLOCKED = "Blocked/Pending"
MISSING = "(missing)"
CMD_CLEAR = "/clear"

ROOT = Path(__file__).resolve().parent.parent
EVALS = json.loads((ROOT / "evals" / "evals.json").read_text(encoding=UTF8))["evals"]
PROMPTS = {e["id"]: e["prompt"] for e in EVALS}
CONFIGS = ("with_skill", "old_skill")
TODAY = datetime.now(UTC).astimezone().date()
KEBAB = r"[a-z0-9]+(?:-[a-z0-9]+)*"
ONLY: set[int] = set()


def text(p: Path) -> str:
    return p.read_text(encoding=UTF8) if p.is_file() else ""


def fixture_scope(run: Path) -> Path:
    cli = ROOT / "skills" / "memoir" / "scripts" / "memoir.py"
    path = subprocess.check_output(
        [sys.executable, cli, "path"], cwd=run / "project",
        env={**os.environ, "MEMOIR_STORE": str(run / "store")}, text=True,
    )
    return Path(path.strip())


def fixture_files(root: Path):
    for directory, dirs, names in os.walk(root):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in sorted(names):
            yield Path(directory) / name


def field(doc: str, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}:\s*(.*)$", doc, re.M)
    return m.group(1).strip() if m else ""


def sections(doc: str) -> dict[str, list[str]]:
    out, cur = {}, None
    for line in doc.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur and line.lstrip().startswith("- "):
            out[cur].append(line)
    return out


def in_order(doc: str, prefixes: list[str]) -> bool:
    lines = doc.splitlines()
    idx = [next((i for i, line in enumerate(lines) if line.startswith(p)), -1) for p in prefixes]
    return -1 not in idx and idx == sorted(idx)


def refs_grounded(active: Path, prompt: str) -> tuple[bool, str]:
    """Every reference Target is a URL, an existing path, or stated verbatim in the prompt."""
    bad = [
        t
        for p in active.glob("reference-*.md")
        if (t := field(text(p), "Target"))
        and not (t.startswith(("http://", "https://")) or Path(t).exists() or t in prompt)
    ]
    return (not bad, f"ungrounded: {bad}")


DURABLE_NAME = rf"(?:decision|reference|feedback)-{KEBAB}\.md"
CAPTURED = r"^Captured: \d+ decisions?, \d+ logs?, \d+ references?, \d+ feedback, \d+ tasks? opened, \d+ tasks? done, state updated\s*$"


def coach_shape(r: str, outcome: str) -> list:
    """Shared coach template: header, Why: with bullets, exactly one Captured: after Why:."""
    lines = r.splitlines()
    head = next((i for i, line in enumerate(lines) if line.strip() == f"[Memoir Coach] {outcome}"), -1)
    why = next((i for i, line in enumerate(lines) if line.strip() == "Why:"), -1)
    caps = [i for i, line in enumerate(lines) if re.match(CAPTURED, line.strip())]
    bullets = why >= 0 and why + 1 < len(lines) and lines[why + 1].lstrip().startswith("- ")
    return [
        (
            f"Header line is exactly '[Memoir Coach] {outcome}'",
            (head >= 0, next((line for line in lines if "Memoir Coach" in line), "(no header)")),
        ),
        (
            "Why: line after the header, followed by a bullet",
            (head >= 0 and why > head and bullets, lines[why + 1] if 0 <= why < len(lines) - 1 else MISSING),
        ),
        (
            "Exactly one Captured: line, after Why:",
            (len(caps) == 1 and caps[0] > why >= 0, f"{len(caps)} Captured: lines"),
        ),
    ]


def files_line_lists_new(r: str, active: Path, fx: Path) -> tuple:
    new = sorted(
        p.name
        for p in active.glob("*.md")
        if p.name != STATE_CURRENT_MD and not (fx / "active" / p.name).exists()
    )
    line = next((raw_line for raw_line in r.splitlines() if raw_line.startswith("Files:")), "")
    return ("Files: line names every new fragment", (bool(line) and all(n in line for n in new), f"{line!r} vs {new}"))


def superseded_line_matches_disk(lines: list[str], active: Path) -> tuple:
    """Superseded: names exactly the active decisions some other decision supersedes (always incl. the REST one)."""
    want = {
        n
        for p in active.glob("*.md") if re.fullmatch(DURABLE_NAME, p.name)
        for n in re.findall(DURABLE_NAME, field(text(p), "Supersedes"))
        if n != p.name
    }
    line = next((raw_line for raw_line in lines if raw_line.startswith("Superseded:")), "")
    got = set(re.findall(DURABLE_NAME, line))
    return (
        "Superseded line matches the Supersedes: chain on disk",
        (bool(line) and got == want and "decision-use-rest-api.md" in got, f"{line!r} vs {sorted(want)}"),
    )


def count_said(reply: str, n: int, kind: str) -> bool:
    return bool(re.search(rf"\b{n}\b[^\n\d]{{0,20}}{kind}|{kind}s?\W{{0,5}}{n}\b", reply, re.I))


# Each check: (assertion text, fn(run_dir, fixture_dir) -> (passed, evidence)).
def checks_auto_decision(run, fx):
    active = fixture_scope(run) / "active"
    new = sorted(p for p in active.glob(DECISION_GLOB) if p.name != DECISION_SQLITE)
    d = text(new[0]) if new else ""
    name = new[0].name if new else "(none)"
    return [
        ("Exactly one new decision fragment written", (len(new) == 1, f"new: {[p.name for p in new]}")),
        (f"Filename is lowercase kebab-case {DECISION_GLOB}", (bool(re.fullmatch(rf"{DECISION_PREFIX}{KEBAB}\.md", name)), name)),
        ("Has all 7 template fields in order", (in_order(d, ["# ", "Date:", "Supersedes:", "Decision:", "Why:", "Alternatives:", "Deferred:"]), d[:300])),
        ("Date is today", (field(d, "Date") == str(TODAY), field(d, "Date"))),
        (f"Supersedes names {DECISION_SQLITE}", (field(d, "Supersedes") == DECISION_SQLITE, field(d, "Supersedes"))),
        ("Alternatives names both WAL and Redis", (all(k in field(d, "Alternatives").lower() for k in ("wal", "redis")), field(d, "Alternatives"))),
        ("Deferred mentions read replicas", ("replica" in field(d, "Deferred").lower(), field(d, "Deferred"))),
        ("Old decision left in active (archiving happens on reload)", ((active / DECISION_SQLITE).is_file(), "")),
    ]


def checks_state(run, fx):
    s = text(fixture_scope(run) / "active" / STATE_CURRENT_MD)
    sec = sections(s)
    want = ["Goal", "Completed", SEC_BLOCKED, SEC_NEXT_ACTION]
    return [
        ("Updated: is today", (field(s, "Updated") == str(TODAY), field(s, "Updated"))),
        ("Stale CI state replaced", ("ci pipeline" not in s.lower() and "lint job" not in s.lower(), s[:200])),
        (f"Has Goal, Completed, {SEC_BLOCKED}, {SEC_NEXT_ACTION} in order", (list(sec) == want, str(list(sec)))),
        ("Every section has 1 to 3 bullets", (bool(sec) and all(1 <= len(v) <= 3 for v in sec.values()), str({k: len(v) for k, v in sec.items()}))),
        (f"{SEC_BLOCKED} mentions the missing Redis credentials", ("redis" in " ".join(sec.get(SEC_BLOCKED, [])).lower(), str(sec.get(SEC_BLOCKED)))),
        (f"{SEC_NEXT_ACTION} mentions app.py", ("app.py" in " ".join(sec.get(SEC_NEXT_ACTION, [])), str(sec.get(SEC_NEXT_ACTION)))),
    ]


def checks_coach(run, fx):
    active = fixture_scope(run) / "active"
    r = text(run / "outputs" / RESPONSE_MD)
    lines = [line.strip() for line in r.splitlines() if line.strip()]
    i = lines.index(CMD_CLEAR) if CMD_CLEAR in lines else -1
    s = text(active / STATE_CURRENT_MD)
    goal = " ".join(sections(s).get("Goal", [])).lower()
    return [
        *coach_shape(r, "CLEAR"),
        files_line_lists_new(r, active, fx),
        (
            "State saved line has the absolute active path",
            (f"State saved -> {active}/{STATE_CURRENT_MD}" in r, next((line for line in lines if line.startswith("State saved")), MISSING)),
        ),
        superseded_line_matches_disk(lines, active),
        (f"{CMD_CLEAR} then /memoir reload as bare consecutive lines", (i >= 0 and i + 1 < len(lines) and lines[i + 1] == "/memoir reload", str(lines[i:i + 2]) if i >= 0 else f"no bare {CMD_CLEAR} line")),
        ("No hand-written resume prompt", ("Load the following files" not in r and "Based on the state file" not in r, "")),
        ("State updated to the CI migration goal", (field(s, "Updated") == str(TODAY) and ("github actions" in goal or "travis" in goal), f"Updated {field(s, 'Updated')}; goal {goal!r}")),
        ("Coach does not archive (REST decision still active)", ((active / "decision-use-rest-api.md").is_file(), "")),
        ("Every reference Target is a URL, existing path or user-stated path", refs_grounded(active, PROMPTS[3])),
    ]


def checks_reload(run, fx):
    base = fixture_scope(run)
    active, archive = base / "active", base / "archive"
    r = text(run / "outputs" / RESPONSE_MD)
    t = text(run / "outputs" / TRANSCRIPT_MD)
    archived = archive / f"{TODAY:%Y%m%d}-decision-use-session-cookies.md"
    others = [p for p in (fx / "active").glob("*.md") if p.name != "decision-use-session-cookies.md"]
    changed = [p.name for p in others if text(active / p.name) != p.read_text(encoding=UTF8).replace("{{today}}", str(TODAY))]
    # Listing paths in archive/resume output does not demonstrate a file read.
    reads = "\n".join(line for line in t.splitlines() if re.search(r"\b(read|cat)\b", line, re.I))
    names = re.findall(rf"(?:state-current|(?:decision|reference|log|feedback|task)-{KEBAB})\.md", reads)
    project_files = [str(p.relative_to(run)) for p in fixture_files(run / "project")]
    return [
        ("Superseded decision moved to archive/YYYYMMDD-…", (archived.is_file() and not (active / archived.name[9:]).exists(), str(sorted(p.name for p in archive.glob("*"))))),
        ("Other fragments untouched", (not changed, f"changed: {changed}")),
        (f"Read {STATE_CURRENT_MD} before other fragments (self-reported transcript)", (bool(names) and names[0] == STATE_CURRENT_MD, str(names[:4]))),
        ("Reply states the PKCE goal", ("pkce" in r.lower(), "")),
        ("Reply states the token-refresh next action", ("refresh" in r.lower(), "")),
        ("Reply names the archived file", ("decision-use-session-cookies" in r, "")),
        ("Reply counts 2 decisions, 1 reference, 1 log", (all(count_said(r, n, k) for n, k in ((2, "decision"), (1, "reference"), (1, "log"))), r[:400])),
        ("Reply reports the measured active size", (str(sum(p.stat().st_size for p in active.glob("*.md"))) in r.replace(",", ""), r[:600])),
        ("Waited: no project files written", (not project_files, str(project_files))),
    ]


def checks_wiki_lag(run, fx):
    r = text(run / "outputs" / RESPONSE_MD)
    wiki = fixture_scope(run).parents[3] / "wiki"
    return [
        *checks_reload(run, fx),
        ("Reports the CLI wiki lag", ("Wiki: 5 pending fragment changes (5 new); run /memoir-wiki ingest" in r, r)),
        ("Wiki and watermark untouched", (
            sorted(p.name for p in wiki.iterdir()) == [".ingest-state.json", "index.md"]
            and text(wiki / "index.md") == "# Wiki Index\n"
            and text(wiki / ".ingest-state.json") == '{"fragments":{}}\n', str(wiki))),
    ]


def checks_backlog(run, fx):
    base = fixture_scope(run)
    active, archive = base / "active", base / "archive"
    r = text(run / "outputs" / RESPONSE_MD)
    files = list(active.glob("*.md"))
    size = sum(f.stat().st_size for f in files)
    return [
        *checks_reload(run, fx),
        ("Restored open tasks and archived both retired kinds", (len(list(active.glob("task-*.md"))) == 46
            and all(list(archive.glob(f"*-{name}.md")) for name in ("task-shipped", "log-expired")), str(archive))),
        ("Relays the backlog hint and counts", (f"Active: 51 files, {size} bytes; run /memoir prune" in r and count_said(r, 46, "task"), r)),
    ]


def checks_trivial(run, fx):
    decisions = [p.name for p in (fixture_scope(run) / "active").glob(DECISION_GLOB)]
    u = text(run / "project" / "users.py")
    return [
        ("(proposed) No decision fragment for a parameter-naming choice", (not decisions, str(decisions))),
        ("users.py written with a user_id parameter", ("def " in u and "user_id" in u, u[:200])),
    ]


def checks_reload_no_uv(run, fx):
    t = text(run / "outputs" / TRANSCRIPT_MD)
    return [
        *checks_reload(run, fx),
        ("No `uv run` attempted (self-reported transcript)", ("uv run" not in t, "")),
        # Only uv errors count: the host's rtk hook also fails on the stripped PATH.
        ("No uv 'command not found' errors", (not re.search(r"not found: uv\b|\buv: (?:command not found|not found|No such file)", t), "")),
    ]


def checks_slug_collision(run, fx):
    active = fixture_scope(run) / "active"
    old = "decision-use-redis-cache.md"
    new = sorted(p for p in active.glob(DECISION_GLOB) if p.name != old)
    d = text(new[0]) if new else ""
    return [
        ("Session-cache decision left unchanged", (text(active / old) == text(fx / "active" / old), "")),
        ("Exactly one new kebab-case decision file", (len(new) == 1 and bool(re.fullmatch(rf"{DECISION_PREFIX}{KEBAB}\.md", new[0].name)), str([p.name for p in new]))),
        ("New decision is about the catalog with a 5-minute TTL", ("catalog" in d.lower() and "5" in field(d, "Decision"), field(d, "Decision"))),
        ("Supersedes: none (session cache still stands)", (field(d, "Supersedes") == "none", field(d, "Supersedes"))),
        ("Alternatives names the per-instance LRU", ("lru" in field(d, "Alternatives").lower(), field(d, "Alternatives"))),
    ]


def checks_coach_continue(run, fx):
    active = fixture_scope(run) / "active"
    r = text(run / "outputs" / RESPONSE_MD)
    s = text(active / STATE_CURRENT_MD)
    return [
        *coach_shape(r, "CONTINUE"),
        ("Next: line follows Captured:", (bool(re.search(r"^Captured:.*\n\s*Next: \S", r, re.M)), next((line for line in r.splitlines() if line.startswith("Next:")), MISSING))),
        (f"No {CMD_CLEAR}, /compact or /memoir reload", (not re.search(r"^\s*/(?:clear|compact|memoir reload)\b", r, re.M), "")),
        ("State updated with the Export button as next action", ("button" in " ".join(sections(s).get(SEC_NEXT_ACTION, [])).lower(), str(sections(s).get(SEC_NEXT_ACTION)))),
        ("Nothing archived", (not any((fixture_scope(run) / "archive").iterdir()), "")),
    ]


def checks_capture(run, fx):
    active = fixture_scope(run) / "active"
    r = text(run / "outputs" / RESPONSE_MD)
    decisions = sorted(p for p in active.glob(DECISION_GLOB) if p.name != DECISION_PNPM)
    logs, refs = sorted(active.glob("log-*.md")), sorted(active.glob("reference-*.md"))
    d = text(decisions[0]) if decisions else ""
    s = text(active / STATE_CURRENT_MD)
    pending = sections(s)
    blocked = " ".join(pending.get(SEC_BLOCKED, []) + pending.get(SEC_NEXT_ACTION, [])).lower()
    opened = [p for p in active.glob("task-*.md") if field(text(p), "Status") == "open"]
    finished = text(active / "task-configure-vitest.md")
    first = text(run / "outputs" / "first-response.md")
    state_key = str((active / STATE_CURRENT_MD).relative_to(run))
    before_repeat, after_repeat = observed_files(run), snapshot(run)
    before_repeat.pop(state_key, None)
    after_repeat.pop(state_key, None)
    return [
        ("One open CI task, one completed setup task", (
            len(opened) == 1 and "node" in field(text(opened[0]), "Task").lower()
            and field(finished, "Status") == "done" and field(finished, "Done") == str(TODAY), str(opened))),
        ("State points to the open task and respects bullet limit", (
            len(opened) == 1 and opened[0].name in s and all(len(v) <= 3 for v in pending.values()), s)),
        ("Repeated capture is idempotent", (bool(first) and before_repeat == after_repeat, first[:300])),
        ("Exactly one new decision, about Vitest", (len(decisions) == 1 and "vitest" in field(d, "Decision").lower(), str([p.name for p in decisions]))),
        ("No duplicate pnpm decision", (not any("pnpm" in text(p).lower().split("alternatives:")[0] for p in decisions), "")),
        ("pnpm decision unchanged", (text(active / DECISION_PNPM) == text(fx / "active" / DECISION_PNPM), "")),
        ("Exactly one log, about the Node 18 ESM crash", (len(logs) == 1 and "node 18" in text(logs[0]).lower(), str([p.name for p in logs]))),
        ("Exactly one reference, targeting the runbook path", (len(refs) == 1 and field(text(refs[0]), "Target") == "/srv/docs/platform/node-upgrade.md", str([p.name for p in refs]))),
        ("Every reference Target is a URL, existing path or user-stated path", refs_grounded(active, PROMPTS[9])),
        ("State records the pending Node 20 upgrade", (field(s, "Updated") == str(TODAY) and "node 20" in blocked, f"Updated {field(s, 'Updated')}; blocked {blocked!r}")),
        ("First capture reports task transitions", (bool(re.search(r"Captured: 1 decisions?, 1 logs?, 1 references?, 0 feedback, 1 tasks? opened, 1 tasks? done", first)), first[:300])),
        ("Repeat reports no new transitions", (bool(re.search(r"Captured: 0 decisions?, 0 logs?, 0 references?, 0 feedback, 0 tasks? opened, 0 tasks? done", r)), r[:300])),
    ]


def checks_coach_compact(run, fx):
    active = fixture_scope(run) / "active"
    r = text(run / "outputs" / RESPONSE_MD)
    compact = [line.strip() for line in r.splitlines() if line.strip().startswith("/compact")]
    focus = compact[0].lower() if compact else ""
    return [
        *coach_shape(r, "COMPACT"),
        ("Exactly one /compact line", (len(compact) == 1, str(compact))),
        ("/compact focus names the billing/tax refactor", ("billing" in focus or "tax" in focus, focus[:200])),
        ("/compact focus names the absolute active path", (str(active) in (compact[0] if compact else ""), focus[:200])),
        ("/compact focus is at most 300 chars excluding the path", (bool(compact) and len(compact[0].replace(str(active), "")) <= 300, f"{len(compact[0].replace(str(active), '')) if compact else 0} chars")),
        (f"No {CMD_CLEAR} or /memoir reload", (not re.search(r"^\s*/(?:clear|memoir reload)\b", r, re.M), "")),
    ]


def checks_coach_friction(run, fx):
    active = fixture_scope(run) / "active"
    r = text(run / "outputs" / RESPONSE_MD)
    lines = [line.strip() for line in r.splitlines() if line.strip()]
    i = lines.index(CMD_CLEAR) if CMD_CLEAR in lines else -1
    decisions = sorted(active.glob(DECISION_GLOB))
    inline = [
        p
        for p in decisions
        if re.search(r"inline|(?:under|below)[^.]*?(?:field|input)", field(text(p), "Decision"), re.I)
        and "toast" in field(text(p), "Alternatives").lower()
    ]
    why = r.split("Why:", 1)[1].split("Captured:", 1)[0].lower() if "Why:" in r and "Captured:" in r else ""
    return [
        *coach_shape(r, "CLEAR"),
        ("Decision records inline errors with toasts as the rejected alternative", (bool(inline), str([p.name for p in decisions]))),
        files_line_lists_new(r, active, fx),
        ("Why: cites the repeated toast/inline correction", (("toast" in why or "inline" in why) and bool(re.search(r"\b(3|three|twice|repeat|re-?correct)", why)), why[:200])),
        (f"{CMD_CLEAR} then /memoir reload as bare consecutive lines", (i >= 0 and i + 1 < len(lines) and lines[i + 1] == "/memoir reload", str(lines[i:i + 2]) if i >= 0 else f"no bare {CMD_CLEAR} line")),
    ]


def checks_capture_feedback(run, fx):
    active = fixture_scope(run) / "active"
    r = text(run / "outputs" / RESPONSE_MD)
    old = "feedback-imperative-commits.md"
    feedback = sorted(p for p in active.glob("feedback-*.md") if p.name != old)
    decisions = sorted(active.glob(DECISION_GLOB))
    f = text(feedback[0]) if feedback else ""
    d = text(decisions[0]) if decisions else ""
    s = text(active / STATE_CURRENT_MD)
    recap = re.compile(r"recap|summar", re.I)
    return [
        ("Exactly one new kebab-case feedback, about recaps", (len(feedback) == 1 and bool(re.fullmatch(rf"feedback-{KEBAB}\.md", feedback[0].name)) and bool(recap.search(field(f, "Feedback"))), str([p.name for p in feedback]))),
        ("Feedback Why: names the rejected recaps", (bool(recap.search(field(f, "Why"))), field(f, "Why"))),
        ("Imperative-commit feedback unchanged, not duplicated", (text(active / old) == text(fx / "active" / old) and not any("imperative" in text(p).lower() for p in feedback), "")),
        ("Exactly one decision, about zod, not about recaps", (len(decisions) == 1 and "zod" in field(d, "Decision").lower() and not recap.search(d), str([p.name for p in decisions]))),
        ("One-off rename not recorded as feedback or decision", (not any("format.ts" in text(p) for p in [*feedback, *decisions]), "")),
        ("State written today", (field(s, "Updated") == str(TODAY), field(s, "Updated"))),
        ("Reply has 'Captured: 1 decisions, <n> logs, 0 references, 1 feedback, 0 tasks opened, 0 tasks done, state updated'", (bool(re.search(r"Captured: 1 decisions?, \d+ logs?, 0 references?, 1 feedback, 0 tasks? opened, 0 tasks? done, state updated", r)), next((line for line in r.splitlines() if "Captured" in line), MISSING))),
    ]


def checks_no_write_access(run, fx):
    r = text(run / "outputs" / RESPONSE_MD)
    t = text(run / "outputs" / TRANSCRIPT_MD)
    written = [str(p.relative_to(run)) for base in ("store", "project") for p in fixture_files(run / base)]
    candidate_lines = "\n".join(
        line
        for line in r.splitlines()
        if re.search(r"approve|retry|retrying", line, re.I)
        and not re.search(r"\b(won't|will not|not|never|without)\b", line, re.I)
    )
    return [
        ("No fragment written in the store or the project", (not written, str(written))),
        ("Reply tells the user to grant access via /add-dir or MEMOIR_STORE", (bool(re.search(r"/add-dir|MEMOIR_STORE", r)), r[:300])),
        ("Reply names an absolute store path", (bool(re.search(r"/[\w.-]+/[\w./-]*memoir", r)), r[:300])),
        ("Did not retry outside the sandbox or bypass it", (not re.search(r"dangerouslyDisableSandbox|unsandboxed|chmod", t, re.I), "")),
        ("Did not offer to retry outside the sandbox", (not re.search(r"outside the sandbox", candidate_lines, re.I), r[:300])),
        ("Did not claim the decision was saved", (not re.search(r"\b(I|it|decision)\b[^.\n]{0,30}\b(saved|written|recorded)\b", re.sub(r"\b(not|n't|never|would have|will)\b[^.\n]*", "", r, flags=re.I), re.I), r[:300])),
    ]


def snapshot(run: Path) -> dict[str, str]:
    """Hash fixture content, excluding CLI scope metadata refreshed on ordinary reads."""
    return {str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest()
            for root in (run / "store", run / "project") for p in fixture_files(root)
            if p.name not in {"clone.json", "worktree.json", "scope.json", "workspace.json"}}


def observed_files(run: Path) -> dict[str, str]:
    return json.loads(text(run / "outputs/after-first.json") or "{}")


def observe(run: Path):
    output = run / "outputs"
    if not text(output / RESPONSE_MD).strip():
        raise ValueError("Record the first reply before observing the run")
    with (output / "after-first.json").open("x", encoding=UTF8) as f:
        json.dump(snapshot(run), f, indent=2)
    (output / RESPONSE_MD).rename(output / "first-response.md")


def checks_prune(run, fx):
    base = fixture_scope(run)
    first = text(run / "outputs/first-response.md").lower()
    tasks = list((base / "active").glob("task-*.md"))
    approved = list((base / "archive").glob("*-log-pilot-shipped.md"))
    before = json.loads(text(run / "before.json") or "{}")
    after = snapshot(run)
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    allowed = {str(p.relative_to(run)) for p in [base / "active/log-pilot-shipped.md", *approved, *tasks]}
    return [
        ("Review requested approval and identified the follow-up", (
            bool(re.search(r"approv|confirm|proceed", first)) and "invoice" in first and "log-pilot-shipped.md" in first, first[:500])),
        ("First turn preserved store and project", (bool(first) and observed_files(run) == before, first[:200])),
        ("Only the approved archive and task changed", (changed == allowed and len(approved) == 1 and text(approved[0]) == text(fx / "active/log-pilot-shipped.md")
            and not (base / "active/log-pilot-shipped.md").exists()
            and text(base / "active/log-dry-run.md") == text(fx / "active/log-dry-run.md")
            and text(base / "active/decision-keep-canary.md") == text(fx / "active/decision-keep-canary.md"), str(approved))),
        ("Recovered exactly one open invoice task from the archived log", (len(tasks) == 1
            and field(text(tasks[0]), "Status") == "open" and "invoice" in field(text(tasks[0]), "Task").lower()
            and "log-pilot-import.md" in field(text(tasks[0]), "Origin"), str(tasks))),
    ]


PILOT_PAGE = "troubleshooting/pilot.md"


def seed_wiki_move(run: Path, base: Path):
    root = base.parents[3]
    wiki = root / "wiki"
    other = root / "clones/second/paths/_main/active/log-pilot-check.md"
    other.parent.mkdir(parents=True)
    other.write_text("# Second pilot\nEvent: Two records passed.\n", encoding=UTF8)
    pages = {"log-pilot-check.md": (PILOT_PAGE, "Eleven records passed the pilot validation."),
             "reference-pilot-guide.md": ("entities/guide.md", "Use the old pilot guide."),
             "feedback-email-pilot.md": ("conventions.md", "Send pilot updates by email.")}
    seen = {}
    for name, (page, content) in pages.items():
        src = base / "active" / name
        key = src.relative_to(root).as_posix()
        sources = [key]
        if page == PILOT_PAGE:
            sources.append(other.relative_to(root).as_posix())
            seen[sources[-1]] = {"sha256": hashlib.sha256(other.read_bytes()).hexdigest(), "pages": [page]}
        seen[key] = {"sha256": hashlib.sha256(src.read_bytes()).hexdigest(), "pages": [page]}
        target = wiki / page
        target.parent.mkdir(exist_ok=True, parents=True)
        target.write_text(f"# {target.stem}\nSources: " + ", ".join(f"`{k}`" for k in sources) + f"\n\n{content}\n", encoding=UTF8)
    (wiki / "index.md").write_text("# Wiki Index\n" + "".join(f"- [[{page[:-3]}]]\n" for page, _ in pages.values()), encoding=UTF8)
    (wiki / ".ingest-state.json").write_text(json.dumps({"version": 1, "fragments": seen}), encoding=UTF8)
    cli = ROOT / "skills/memoir/scripts/memoir.py"
    for flag in ("log-pilot-check.md", "--superseded"):
        subprocess.run([sys.executable, cli, "archive", flag], cwd=run / "project",
                       env={**os.environ, "MEMOIR_STORE": str(run / "store")}, check=True, stdout=subprocess.DEVNULL)
    (run / "pilot-before.md").write_text(text(wiki / PILOT_PAGE), encoding=UTF8)


def checks_wiki_move(run, fx):
    base = fixture_scope(run)
    root = base.parents[3]
    wiki = root / "wiki"
    key = (base / "active/log-pilot-check.md").relative_to(root).as_posix()
    moved = next((base / "archive").glob("*-log-pilot-check.md")).relative_to(root).as_posix()
    seen = json.loads(text(wiki / ".ingest-state.json"))["fragments"]
    pages = "\n".join(text(p) for p in wiki.rglob("*.md")).lower()
    guide = text(wiki / "entities/guide.md").lower()
    convention = text(wiki / "conventions.md").lower()
    guide_links = re.findall(r"\[\[([^#|\]]+)", guide)
    current_guides = {p.relative_to(wiki).with_suffix("").as_posix() for p in (wiki / "entities").glob("*.md")
                      if "guide-v2" in text(p).lower()}
    has_current_guide_link = bool(current_guides.intersection(guide_links))
    return [
        ("Only the local source changed on the existing log page", (
            text(wiki / PILOT_PAGE) == text(run / "pilot-before.md").replace(key, moved), text(wiki / PILOT_PAGE))),
        ("Watermark moved with its page; tasks excluded", (key not in seen and seen.get(moved, {}).get("pages") == [PILOT_PAGE]
            and not any("task-" in k for k in seen) and "task-local-debug" not in pages and "task-finished" not in pages, str(list(seen)))),
        ("Reference and convention keep linked replacement history", (
            all(any(word in text(wiki / p).lower() for word in ("history", "previous", "replaced", "retired", "superseded", "formerly"))
                for p in ("entities/guide.md", "conventions.md"))
            and has_current_guide_link and "[[" in convention and "chat" in convention and "email" in convention, pages[:1000])),
        ("Second ingest leaves files unchanged and reports current", (
            bool(observed_files(run)) and observed_files(run) == snapshot(run) and "up to date" in text(run / "outputs" / RESPONSE_MD).lower(),
            text(run / "outputs" / RESPONSE_MD))),
    ]


CHECKS = {
    1: checks_auto_decision,
    2: checks_state,
    3: checks_coach,
    4: checks_reload,
    5: checks_trivial,
    6: checks_reload_no_uv,
    7: checks_slug_collision,
    8: checks_coach_continue,
    9: checks_capture,
    10: checks_coach_compact,
    11: checks_coach_friction,
    12: checks_capture_feedback,
    13: checks_no_write_access,
    14: checks_wiki_lag,
    15: checks_prune,
    16: checks_wiki_move,
    17: checks_backlog,
}


def run_dirs(iteration: Path):
    for e in (e for e in EVALS if not ONLY or e["id"] in ONLY):
        eval_dir = iteration / f"eval-{e['id']}-{e['name']}"
        for config in CONFIGS:
            yield e, eval_dir, eval_dir / config / "run-1"


def seed_backlog(base: Path):
    active = base / "active"
    for n in range(46):
        (active / f"task-import-{n}.md").write_text(
            f"# Validate import batch {n}\nCreated: {TODAY}\nStatus: open\nDone: none\nOrigin: none\nTask: Validate import batch {n}.\n", encoding=UTF8)
    (active / "task-shipped.md").write_text(f"# Ship build\nCreated: {TODAY}\nStatus: done\nDone: {TODAY}\nOrigin: none\nTask: Ship build.\n", encoding=UTF8)
    (active / "log-expired.md").write_text(f"# Earlier build\nDate: {TODAY - timedelta(days=31)}\nEvent: Built.\nImpact: Released.\n", encoding=UTF8)


def setup(iteration: Path):
    for e, eval_dir, run in run_dirs(iteration):
        fx = ROOT / e["files"][0]
        (run / "project").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(run / "project")], check=True)
        base = fixture_scope(run)
        shutil.copytree(fx, base, ignore=shutil.ignore_patterns(".gitkeep"))
        (base / "archive").mkdir(exist_ok=True)
        for fragment in (base / "active").glob("log-*.md"):
            body = text(fragment)
            if "{{today}}" in body:
                fragment.write_text(body.replace("{{today}}", str(TODAY)), encoding=UTF8)
        if e["id"] == 17:
            seed_backlog(base)
        if e["id"] == 16:
            seed_wiki_move(run, base)
        if e["id"] == 6:
            (run / "bin").mkdir()
            (run / "bin" / "python3").symlink_to(sys.executable)
        if e["id"] == 14:
            root = base.parents[3]
            wiki = root / "wiki"
            wiki.mkdir()
            (wiki / ".ingest-state.json").write_text('{"fragments":{}}\n', encoding=UTF8)
            (wiki / "index.md").write_text("# Wiki Index\n", encoding=UTF8)
            (root / "meta.json").write_text('{"sync_to_repo":true}\n', encoding=UTF8)
        (run / "outputs").mkdir()
        (run / "before.json").write_text(json.dumps(snapshot(run)), encoding=UTF8)
        names = [c[0] for c in CHECKS[e["id"]](run, fx)]
        meta = {"eval_id": e["id"], "eval_name": e["name"], "prompt": e["prompt"], "assertions": names}
        if "followup" in e:
            meta["followup"] = e["followup"]
        for d in (eval_dir, run.parent):
            (d / "eval_metadata.json").write_text(json.dumps(meta, indent=2), encoding=UTF8)
        print(run)


def dump_files(run: Path) -> str:
    out = []
    for base in ("store", "project"):
        for p in sorted(fixture_files(run / base)):
            if p.is_file():
                body = p.read_text(encoding=UTF8, errors="replace") if p.suffix in (".md", ".py", "") else f"({p.stat().st_size} bytes)"
                out.append(f"## {p.relative_to(run)}\n\n```\n{body}\n```\n")
    return "\n".join(out) or "(no files)"


def grade(iteration: Path):
    for e, _, run in run_dirs(iteration):
        if not text(run / "outputs" / RESPONSE_MD).strip() or ("followup" in e and not (run / "outputs/after-first.json").is_file()):
            (run / "grading.json").unlink(missing_ok=True)
            print(f"{run.parent.parent.name}/{run.parent.name}: not run")
            continue
        results = CHECKS[e["id"]](run, ROOT / e["files"][0])
        exps = [{"text": t, "passed": bool(ok), "evidence": ev} for t, (ok, ev) in results]
        passed = sum(x["passed"] for x in exps)
        timing = json.loads(text(run / "timing.json") or "{}")
        grading = {
            "expectations": exps,
            "summary": {"passed": passed, "failed": len(exps) - passed, "total": len(exps), "pass_rate": round(passed / len(exps), 2)},
            "timing": {"total_duration_seconds": timing.get("total_duration_seconds", 0.0)},
        }
        (run / "grading.json").write_text(json.dumps(grading, indent=2), encoding=UTF8)
        (run / "outputs" / "files-after-run.md").write_text(dump_files(run), encoding=UTF8)
        print(f"{run.parent.parent.name}/{run.parent.name}: {passed}/{len(exps)}")


if __name__ == "__main__":
    if sys.argv[1] == "observe":
        observe(Path(sys.argv[2]).resolve())
        sys.exit(0)
    ONLY.update(int(i) for i in sys.argv[3:])
    {"setup": setup, "grade": grade}[sys.argv[1]](Path(sys.argv[2]).resolve())
