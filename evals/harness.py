"""Set up and grade memoir skill eval runs.

    python3 evals/harness.py setup <iteration-dir> [eval-id ...]   # seed run dirs from evals/fixtures
    python3 evals/harness.py grade <iteration-dir> [eval-id ...]   # write grading.json + outputs/files-after-run.md

Layout per run: <iteration>/eval-<id>-<name>/<config>/run-1/{store,project,outputs}.
"""
import json
import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = json.loads((ROOT / "evals" / "evals.json").read_text())["evals"]
PROMPTS = {e["id"]: e["prompt"] for e in EVALS}
CONFIGS = ("with_skill", "old_skill")
TODAY = date.today()
KEBAB = r"[a-z0-9]+(?:-[a-z0-9]+)*"


def text(p: Path) -> str:
    return p.read_text() if p.is_file() else ""


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
    idx = [next((i for i, l in enumerate(lines) if l.startswith(p)), -1) for p in prefixes]
    return -1 not in idx and idx == sorted(idx)


def refs_grounded(active: Path, prompt: str) -> tuple[bool, str]:
    """Every reference Target is a URL, an existing path, or stated verbatim in the prompt."""
    bad = [t for p in active.glob("reference-*.md") if (t := field(text(p), "Target"))
           and not (t.startswith(("http://", "https://")) or Path(t).exists() or t in prompt)]
    return (not bad, f"ungrounded: {bad}")


CAPTURED = r"^Captured: \d+ decisions?, \d+ logs?, \d+ references?, \d+ feedback, state updated\s*$"


def coach_shape(r: str, outcome: str) -> list:
    """Shared coach template: header, Why: with bullets, exactly one Captured: after Why:."""
    lines = r.splitlines()
    head = next((i for i, l in enumerate(lines) if l.strip() == f"[Memoir Coach] {outcome}"), -1)
    why = next((i for i, l in enumerate(lines) if l.strip() == "Why:"), -1)
    caps = [i for i, l in enumerate(lines) if re.match(CAPTURED, l.strip())]
    bullets = why >= 0 and why + 1 < len(lines) and lines[why + 1].lstrip().startswith("- ")
    return [
        (f"Header line is exactly '[Memoir Coach] {outcome}'", (head >= 0, next((l for l in lines if "Memoir Coach" in l), "(no header)"))),
        ("Why: line after the header, followed by a bullet", (head >= 0 and why > head and bullets, lines[why + 1] if 0 <= why < len(lines) - 1 else "(missing)")),
        ("Exactly one Captured: line, after Why:", (len(caps) == 1 and caps[0] > why >= 0, f"{len(caps)} Captured: lines")),
    ]


def files_line_lists_new(r: str, active: Path, fx: Path) -> tuple:
    new = sorted(p.name for p in active.glob("*.md")
                 if p.name != "state-current.md" and not (fx / "active" / p.name).exists())
    line = next((l for l in r.splitlines() if l.startswith("Files:")), "")
    return ("Files: line names every new fragment", (bool(line) and all(n in line for n in new), f"{line!r} vs {new}"))


def superseded_line_matches_disk(lines: list[str], active: Path) -> tuple:
    """Superseded: names exactly the active decisions some other decision supersedes (always incl. the REST one)."""
    want = {n for p in active.glob("decision-*.md")
            for n in re.findall(rf"decision-{KEBAB}\.md", field(text(p), "Supersedes")) if n != p.name}
    line = next((l for l in lines if l.startswith("Superseded:")), "")
    got = set(re.findall(rf"decision-{KEBAB}\.md", line))
    return ("Superseded line matches the Supersedes: chain on disk", (bool(line) and got == want and "decision-use-rest-api.md" in got, f"{line!r} vs {sorted(want)}"))


def count_said(reply: str, n: int, kind: str) -> bool:
    return bool(re.search(rf"\b{n}\b[^\n\d]{{0,20}}{kind}|{kind}s?\W{{0,5}}{n}\b", reply, re.I))


# Each check: (assertion text, fn(run_dir, fixture_dir) -> (passed, evidence)).
def checks_auto_decision(run, fx):
    active = run / "store" / "active"
    new = sorted(p for p in active.glob("decision-*.md") if p.name != "decision-use-sqlite.md")
    d = text(new[0]) if new else ""
    name = new[0].name if new else "(none)"
    return [
        ("Exactly one new decision fragment written", (len(new) == 1, f"new: {[p.name for p in new]}")),
        ("Filename is lowercase kebab-case decision-*.md", (bool(re.fullmatch(rf"decision-{KEBAB}\.md", name)), name)),
        ("Has all 7 template fields in order", (in_order(d, ["# ", "Date:", "Supersedes:", "Decision:", "Why:", "Alternatives:", "Deferred:"]), d[:300])),
        ("Date is today", (field(d, "Date") == str(TODAY), field(d, "Date"))),
        ("Supersedes names decision-use-sqlite.md", (field(d, "Supersedes") == "decision-use-sqlite.md", field(d, "Supersedes"))),
        ("Alternatives names both WAL and Redis", (all(k in field(d, "Alternatives").lower() for k in ("wal", "redis")), field(d, "Alternatives"))),
        ("Deferred mentions read replicas", ("replica" in field(d, "Deferred").lower(), field(d, "Deferred"))),
        ("Old decision left in active (archiving happens on reload)", ((active / "decision-use-sqlite.md").is_file(), "")),
    ]


def checks_state(run, fx):
    s = text(run / "store" / "active" / "state-current.md")
    sec = sections(s)
    want = ["Goal", "Completed", "Blocked/Pending", "Next Action"]
    return [
        ("Updated: is today", (field(s, "Updated") == str(TODAY), field(s, "Updated"))),
        ("Stale CI state replaced", ("ci pipeline" not in s.lower() and "lint job" not in s.lower(), s[:200])),
        ("Has Goal, Completed, Blocked/Pending, Next Action in order", (list(sec) == want, str(list(sec)))),
        ("Every section has 1 to 3 bullets", (bool(sec) and all(1 <= len(v) <= 3 for v in sec.values()), str({k: len(v) for k, v in sec.items()}))),
        ("Blocked/Pending mentions the missing Redis credentials", ("redis" in " ".join(sec.get("Blocked/Pending", [])).lower(), str(sec.get("Blocked/Pending")))),
        ("Next Action mentions app.py", ("app.py" in " ".join(sec.get("Next Action", [])), str(sec.get("Next Action")))),
    ]


def checks_coach(run, fx):
    active = run / "store" / "active"
    r = text(run / "outputs" / "response.md")
    lines = [l.strip() for l in r.splitlines() if l.strip()]
    i = lines.index("/clear") if "/clear" in lines else -1
    s = text(active / "state-current.md")
    goal = " ".join(sections(s).get("Goal", [])).lower()
    return [
        *coach_shape(r, "CLEAR"),
        files_line_lists_new(r, active, fx),
        ("State saved line has the absolute active path", (f"State saved -> {active}/state-current.md" in r, next((l for l in lines if l.startswith("State saved")), "(missing)"))),
        superseded_line_matches_disk(lines, active),
        ("/clear then /memoir reload as bare consecutive lines", (i >= 0 and i + 1 < len(lines) and lines[i + 1] == "/memoir reload", str(lines[i:i + 2]) if i >= 0 else "no bare /clear line")),
        ("No hand-written resume prompt", ("Load the following files" not in r and "Based on the state file" not in r, "")),
        ("State updated to the CI migration goal", (field(s, "Updated") == str(TODAY) and ("github actions" in goal or "travis" in goal), f"Updated {field(s, 'Updated')}; goal {goal!r}")),
        ("Coach does not archive (REST decision still active)", ((active / "decision-use-rest-api.md").is_file(), "")),
        ("Every reference Target is a URL, existing path or user-stated path", refs_grounded(active, PROMPTS[3])),
    ]


def checks_reload(run, fx):
    active, archive = run / "store" / "active", run / "store" / "archive"
    r = text(run / "outputs" / "response.md")
    t = text(run / "outputs" / "transcript.md")
    archived = archive / f"{TODAY:%Y%m%d}-decision-use-session-cookies.md"
    others = [p for p in (fx / "active").glob("*.md") if p.name != "decision-use-session-cookies.md"]
    changed = [p.name for p in others if text(active / p.name) != p.read_text()]
    # The archive step names the superseded file; only reads of active fragments count.
    names = [n for n in re.findall(rf"(?:state-current|decision-{KEBAB}|reference-{KEBAB}|log-{KEBAB})\.md", t)
             if n != "decision-use-session-cookies.md"]
    project_files = [str(p.relative_to(run)) for p in (run / "project").rglob("*") if p.is_file()]
    return [
        ("Superseded decision moved to archive/YYYYMMDD-…", (archived.is_file() and not (active / archived.name[9:]).exists(), str(sorted(p.name for p in archive.glob("*"))))),
        ("Other fragments untouched", (not changed, f"changed: {changed}")),
        ("Read state-current.md before other fragments (self-reported transcript)", (bool(names) and names[0] == "state-current.md", str(names[:4]))),
        ("Reply states the PKCE goal", ("pkce" in r.lower(), "")),
        ("Reply states the token-refresh next action", ("refresh" in r.lower(), "")),
        ("Reply names the archived file", ("decision-use-session-cookies" in r, "")),
        ("Reply counts 2 decisions, 1 reference, 1 log", (all(count_said(r, n, k) for n, k in ((2, "decision"), (1, "reference"), (1, "log"))), r[:400])),
        ("Waited: no project files written", (not project_files, str(project_files))),
    ]


def checks_trivial(run, fx):
    decisions = [p.name for p in (run / "store" / "active").glob("decision-*.md")]
    u = text(run / "project" / "users.py")
    return [
        ("(proposed) No decision fragment for a parameter-naming choice", (not decisions, str(decisions))),
        ("users.py written with a user_id parameter", ("def " in u and "user_id" in u, u[:200])),
    ]


def checks_reload_no_uv(run, fx):
    t = text(run / "outputs" / "transcript.md")
    return checks_reload(run, fx) + [
        ("No `uv run` attempted (self-reported transcript)", ("uv run" not in t, "")),
        # Only uv errors count: the host's rtk hook also fails on the stripped PATH.
        ("No uv 'command not found' errors", (not re.search(r"not found: uv\b|\buv: (?:command not found|not found|No such file)", t), "")),
    ]


def checks_slug_collision(run, fx):
    active = run / "store" / "active"
    old = "decision-use-redis-cache.md"
    new = sorted(p for p in active.glob("decision-*.md") if p.name != old)
    d = text(new[0]) if new else ""
    return [
        ("Session-cache decision left unchanged", (text(active / old) == text(fx / "active" / old), "")),
        ("Exactly one new kebab-case decision file", (len(new) == 1 and bool(re.fullmatch(rf"decision-{KEBAB}\.md", new[0].name)), str([p.name for p in new]))),
        ("New decision is about the catalog with a 5-minute TTL", ("catalog" in d.lower() and "5" in field(d, "Decision"), field(d, "Decision"))),
        ("Supersedes: none (session cache still stands)", (field(d, "Supersedes") == "none", field(d, "Supersedes"))),
        ("Alternatives names the per-instance LRU", ("lru" in field(d, "Alternatives").lower(), field(d, "Alternatives"))),
    ]


def checks_coach_continue(run, fx):
    active = run / "store" / "active"
    r = text(run / "outputs" / "response.md")
    s = text(active / "state-current.md")
    return [
        *coach_shape(r, "CONTINUE"),
        ("Next: line follows Captured:", (bool(re.search(r"^Captured:.*\n\s*Next: \S", r, re.M)), next((l for l in r.splitlines() if l.startswith("Next:")), "(missing)"))),
        ("No /clear, /compact or /memoir reload", (not re.search(r"^\s*/(?:clear|compact|memoir reload)\b", r, re.M), "")),
        ("State updated with the Export button as next action", ("button" in " ".join(sections(s).get("Next Action", [])).lower(), str(sections(s).get("Next Action")))),
        ("Nothing archived", (not any((run / "store" / "archive").iterdir()), "")),
    ]


def checks_capture(run, fx):
    active = run / "store" / "active"
    r = text(run / "outputs" / "response.md")
    decisions = sorted(p for p in active.glob("decision-*.md") if p.name != "decision-use-pnpm.md")
    logs, refs = sorted(active.glob("log-*.md")), sorted(active.glob("reference-*.md"))
    d = text(decisions[0]) if decisions else ""
    s = text(active / "state-current.md")
    blocked = " ".join(sections(s).get("Blocked/Pending", [])).lower()
    return [
        ("Exactly one new decision, about Vitest", (len(decisions) == 1 and "vitest" in field(d, "Decision").lower(), str([p.name for p in decisions]))),
        ("No duplicate pnpm decision", (not any("pnpm" in text(p).lower().split("alternatives:")[0] for p in decisions), "")),
        ("pnpm decision unchanged", (text(active / "decision-use-pnpm.md") == text(fx / "active" / "decision-use-pnpm.md"), "")),
        ("Exactly one log, about the Node 18 ESM crash", (len(logs) == 1 and "node 18" in text(logs[0]).lower(), str([p.name for p in logs]))),
        ("Exactly one reference, targeting the runbook path", (len(refs) == 1 and field(text(refs[0]), "Target") == "/srv/docs/platform/node-upgrade.md", str([p.name for p in refs]))),
        ("Every reference Target is a URL, existing path or user-stated path", refs_grounded(active, PROMPTS[9])),
        ("State written today with Node 20 bump as blocked", (field(s, "Updated") == str(TODAY) and "node 20" in blocked, f"Updated {field(s, 'Updated')}; blocked {blocked!r}")),
        ("Reply has 'Captured: 1 decisions, 1 logs, 1 references, 0 feedback, state updated'", (bool(re.search(r"Captured: 1 decisions?, 1 logs?, 1 references?, 0 feedback, state updated", r)), next((l for l in r.splitlines() if "Captured" in l), "(missing)"))),
    ]


def checks_coach_compact(run, fx):
    active = run / "store" / "active"
    r = text(run / "outputs" / "response.md")
    compact = [l.strip() for l in r.splitlines() if l.strip().startswith("/compact")]
    focus = compact[0].lower() if compact else ""
    return [
        *coach_shape(r, "COMPACT"),
        ("Exactly one /compact line", (len(compact) == 1, str(compact))),
        ("/compact focus names the billing/tax refactor", ("billing" in focus or "tax" in focus, focus[:200])),
        ("/compact focus names the absolute active path", (str(active) in (compact[0] if compact else ""), focus[:200])),
        ("/compact focus is at most 300 chars excluding the path", (bool(compact) and len(compact[0].replace(str(active), "")) <= 300, f"{len(compact[0].replace(str(active), '')) if compact else 0} chars")),
        ("No /clear or /memoir reload", (not re.search(r"^\s*/(?:clear|memoir reload)\b", r, re.M), "")),
    ]


def checks_coach_friction(run, fx):
    active = run / "store" / "active"
    r = text(run / "outputs" / "response.md")
    lines = [l.strip() for l in r.splitlines() if l.strip()]
    i = lines.index("/clear") if "/clear" in lines else -1
    decisions = sorted(active.glob("decision-*.md"))
    inline = [p for p in decisions if "inline" in field(text(p), "Decision").lower()
              and "toast" in field(text(p), "Alternatives").lower()]
    why = r.split("Why:", 1)[1].split("Captured:", 1)[0].lower() if "Why:" in r and "Captured:" in r else ""
    return [
        *coach_shape(r, "CLEAR"),
        ("Decision records inline errors with toasts as the rejected alternative", (bool(inline), str([p.name for p in decisions]))),
        files_line_lists_new(r, active, fx),
        ("Why: cites the repeated toast/inline correction", (("toast" in why or "inline" in why) and bool(re.search(r"\b(3|three|twice|repeat|re-?correct)", why)), why[:200])),
        ("/clear then /memoir reload as bare consecutive lines", (i >= 0 and i + 1 < len(lines) and lines[i + 1] == "/memoir reload", str(lines[i:i + 2]) if i >= 0 else "no bare /clear line")),
    ]


def checks_capture_feedback(run, fx):
    active = run / "store" / "active"
    r = text(run / "outputs" / "response.md")
    old = "feedback-imperative-commits.md"
    feedback = sorted(p for p in active.glob("feedback-*.md") if p.name != old)
    decisions = sorted(active.glob("decision-*.md"))
    f = text(feedback[0]) if feedback else ""
    d = text(decisions[0]) if decisions else ""
    s = text(active / "state-current.md")
    recap = re.compile(r"recap|summar", re.I)
    return [
        ("Exactly one new kebab-case feedback, about recaps", (len(feedback) == 1 and bool(re.fullmatch(rf"feedback-{KEBAB}\.md", feedback[0].name)) and bool(recap.search(field(f, "Feedback"))), str([p.name for p in feedback]))),
        ("Feedback Why: names the rejected recaps", (bool(recap.search(field(f, "Why"))), field(f, "Why"))),
        ("Imperative-commit feedback unchanged, not duplicated", (text(active / old) == text(fx / "active" / old) and not any("imperative" in text(p).lower() for p in feedback), "")),
        ("Exactly one decision, about zod, not about recaps", (len(decisions) == 1 and "zod" in field(d, "Decision").lower() and not recap.search(d), str([p.name for p in decisions]))),
        ("One-off rename not recorded as feedback or decision", (not any("format.ts" in text(p) for p in [*feedback, *decisions]), "")),
        ("State written today", (field(s, "Updated") == str(TODAY), field(s, "Updated"))),
        ("Reply has 'Captured: 1 decisions, <n> logs, 0 references, 1 feedback, state updated'", (bool(re.search(r"Captured: 1 decisions?, \d+ logs?, 0 references?, 1 feedback, state updated", r)), next((l for l in r.splitlines() if "Captured" in l), "(missing)"))),
    ]


CHECKS = {1: checks_auto_decision, 2: checks_state, 3: checks_coach, 4: checks_reload, 5: checks_trivial,
          6: checks_reload_no_uv, 7: checks_slug_collision, 8: checks_coach_continue, 9: checks_capture,
          10: checks_coach_compact, 11: checks_coach_friction, 12: checks_capture_feedback}
ONLY = {int(i) for i in sys.argv[3:]}


def run_dirs(iteration: Path):
    for e in (e for e in EVALS if not ONLY or e["id"] in ONLY):
        eval_dir = iteration / f"eval-{e['id']}-{e['name']}"
        for config in CONFIGS:
            yield e, eval_dir, eval_dir / config / "run-1"


def setup(iteration: Path):
    for e, eval_dir, run in run_dirs(iteration):
        fx = ROOT / e["files"][0]
        shutil.copytree(fx, run / "store", ignore=shutil.ignore_patterns(".gitkeep"))
        (run / "store" / "archive").mkdir()
        (run / "project").mkdir()
        (run / "outputs").mkdir()
        names = [c[0] for c in CHECKS[e["id"]](run, fx)]
        meta = {"eval_id": e["id"], "eval_name": e["name"], "prompt": e["prompt"], "assertions": names}
        for d in (eval_dir, run.parent):
            (d / "eval_metadata.json").write_text(json.dumps(meta, indent=2))
        print(run)


def dump_files(run: Path) -> str:
    out = []
    for base in ("store", "project"):
        for p in sorted((run / base).rglob("*")):
            if p.is_file():
                body = p.read_text(errors="replace") if p.suffix in (".md", ".py", "") else f"({p.stat().st_size} bytes)"
                out.append(f"## {p.relative_to(run)}\n\n```\n{body}\n```\n")
    return "\n".join(out) or "(no files)"


def grade(iteration: Path):
    for e, _, run in run_dirs(iteration):
        if not run.is_dir():
            continue
        results =CHECKS[e["id"]](run, ROOT / e["files"][0])
        exps = [{"text": t, "passed": bool(ok), "evidence": ev} for t, (ok, ev) in results]
        passed = sum(x["passed"] for x in exps)
        timing = json.loads(text(run / "timing.json") or "{}")
        grading = {
            "expectations": exps,
            "summary": {"passed": passed, "failed": len(exps) - passed, "total": len(exps), "pass_rate": round(passed / len(exps), 2)},
            "timing": {"total_duration_seconds": timing.get("total_duration_seconds", 0.0)},
        }
        (run / "grading.json").write_text(json.dumps(grading, indent=2))
        (run / "outputs" / "files-after-run.md").write_text(dump_files(run))
        print(f"{run.parent.parent.name}/{run.parent.name}: {passed}/{len(exps)}")


if __name__ == "__main__":
    {"setup": setup, "grade": grade}[sys.argv[1]](Path(sys.argv[2]).resolve())
