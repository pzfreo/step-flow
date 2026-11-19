"""The step-flow pipeline: diff -> validate -> write -> draw -> lint, each with a verdict.

Every stage calls the released CLIs (``specify-core``, ``draftwright``) and reads their JSON. Nothing is
guessed: the PMI write never takes defaults (P4), and anything a tool leaves open is named as an item.
"""

import json
import re
import shutil
from collections import Counter
from pathlib import Path

from . import verdict as V
from .tools import Runner, ToolError, check_versions, dump_json, load_json

# Draftwright problem codes that mean a Spec edit no longer applies to the drawing (a stale Spec edit).
STALE_SPEC_CODES = {"dimension_edit_unapplied", "annotation_edit_unapplied", "id_not_migrated"}
# Draftwright diff's classes for a Spec entry that carried to the new revision.
SPEC_CARRIED = {"renamed", "carried", "unchanged", "adapted"}


def _tool_failure(runner, what):
    failed = [e for e in runner.log if e["rc"] != 0]
    last = (failed or runner.log)[-1]
    return {"kind": "tool_failure", "id": " ".join(last["cmd"][:2]), "needs": V.PROBLEMS,
            "what": f"{what}: `{' '.join(last['cmd'])}` exit {last['rc']}: {last['stderr'] or '(no message)'}",
            "where": "commands.json"}


# --- 1. diff -------------------------------------------------------------------------------------

def stage_diff(r, old, new, answers, out):
    d = out / "diff"
    proc = r.run("specify-core", "diff", old, new, "--answers", answers, "--title", Path(new).name, "-o", d)
    if proc.returncode != 0 or not (d / "report.json").exists():
        return V.stage("diff", V.PROBLEMS, [_tool_failure(r, "specify-core diff failed")]), None
    report = load_json(d / "report.json")
    carried = load_json(d / "answers.json")
    items, notes = [], []
    for u in report.get("unresolved", []):
        items.append({"kind": f"requirement_{u.get('class', 'unresolved')}", "id": u["id"], "needs": V.DECIDE,
                      "revision": "old", "answer": u.get("answer"),
                      "what": f"{u['id']} = {u.get('answer')!r} not carried ({u.get('class')}): {u.get('reason')}",
                      "where": "diff/report.json#/unresolved"})
    for q in report.get("questions", []):
        items.append({"kind": "requirement_to_specify", "id": q["id"], "needs": V.DECIDE, "revision": "new",
                      "what": f"{q['id']}: {q.get('title')}", "where": "diff/report.json#/questions"})
    named = {i["id"] for i in items}
    for qid, reason in sorted(carried.get("_specify", {}).get("unresolved", {}).items()):
        if qid not in named:
            items.append({"kind": "carry_blocked", "id": qid, "needs": V.DECIDE,
                          "what": f"{qid}: {reason}", "where": "diff/answers.json#/_specify/unresolved"})
    for p in report.get("problems", {}).get("added", []):
        items.append({"kind": "specify_problem", "id": p.get("code") or p.get("id") or str(p), "needs": V.PROBLEMS,
                      "what": p.get("message") or str(p), "where": "diff/report.json#/problems/added"})
    for c in report.get("check", []):
        notes.append({"kind": "check", "id": c["id"], "feature": c.get("feature"), "answer": c.get("answer"),
                      "changes": c.get("changes"), "where": "diff/report.json#/check",
                      "what": f"{c['id']} = {c.get('answer')!r} carried to a changed feature; check it still fits"})
    tie = report.get("frame_tie")
    if tie:
        notes.append({"kind": "frame_tie", "alternative": tie.get("alternative"), "where": "diff/report.json#/frame_tie",
                      "what": "tie broken by the file frame: " + (tie.get("note") or "another placement fits equally")})
    tool_verdict = report.get("verdict")
    verdict = V.worst([tool_verdict, V.item_verdict(items)])
    if verdict != tool_verdict:
        notes.append({"kind": "verdict_disagrees", "what": f"specify-core said {tool_verdict}, its items say {verdict}"})
    return V.stage("diff", verdict, items, notes, tool_verdict=tool_verdict, summary=report.get("summary"),
                   features=report.get("features", []), migrated=report.get("migrated", [])), report


# --- answering a decision -----------------------------------------------------------------------

def resolve(stage, out, person_answers=None, accepted=()):
    """Apply what a person decided to the diff stage, so the next run re-checks it.

    - ``person_answers``: an answers file edited in the PR. It counts only when it is stamped for the new
      revision (its ``_specify.evidence`` equals the carried answers'), i.e. it is the file step-flow committed
      back, not main's. Its answers replace the carried ones; an item about a question it now answers is closed.
    - ``accepted``: requirement ids the person has accepted as dropped (an orphaned requirement); closed.

    The carried file is kept as ``diff/carried.answers.json``. Nothing is closed by being absent: a person must
    answer or list the id, so committing step-flow's own output back never turns a ``decide`` into ``ok``.
    """
    closed, stale = {}, []
    carried_path = out / "diff" / "answers.json"
    if person_answers:
        carried, mine = load_json(carried_path), load_json(person_answers)
        if carried.get("_specify", {}).get("evidence") == mine.get("_specify", {}).get("evidence"):
            dump_json(carried, out / "diff" / "carried.answers.json")
            for k, v in mine.items():
                if not k.startswith("_") and carried.get(k) != v:
                    carried[k] = v
                    closed[k] = "answered in answers.json"
            unresolved = carried.get("_specify", {}).get("unresolved", {})
            for k in [k for k in unresolved if k in closed]:
                del unresolved[k]
            dump_json(carried, carried_path)
        else:
            # Stamped for an earlier STEP (the geometry changed again): not applied, and said so.
            stale = sorted(k for k, v in mine.items() if not k.startswith("_") and carried.get(k) != v)
    for a in accepted:
        closed.setdefault(a, "accepted in accepted.json")
    notes = list(stage["notes"])
    if stale:
        notes.append({"kind": "answers_stale", "ids": stale, "where": "part.answers.json",
                      "what": f"{len(stale)} answers given for the previous STEP weren't applied; "
                              "re-answer against this one"})
        stage = dict(stage, notes=notes)
    if not closed:
        return stage
    kept = []
    for i in stage["items"]:
        if i.get("kind", "").startswith(("requirement_", "carry_blocked")) and i.get("id") in closed:
            notes.append({"kind": "decided", "id": i["id"], "what": f"{i['what']} -- {closed[i['id']]}",
                          "where": i["where"]})
        else:
            kept.append(i)
    stage = dict(stage, items=kept, notes=notes, verdict=V.item_verdict(kept))
    return stage


# --- 2. validate ---------------------------------------------------------------------------------

def stage_validate(r, new, out):
    """The new revision with the carried answers: Specify's own question list must have nothing open."""
    d = out / "validate"
    d.mkdir(parents=True, exist_ok=True)
    analysis = d / "new.analysis.json"
    if r.run("specify-core", "analyse", new, "-o", analysis).returncode != 0:
        return V.stage("validate", V.PROBLEMS, [_tool_failure(r, "specify-core analyse (new) failed")])
    proc = r.run("specify-core", "questions", analysis, "--answers", out / "diff" / "answers.json", "--open",
                 stdout_to=d / "open.json")
    if proc.returncode != 0:
        item = _tool_failure(r, "the carried answers are refused by the new revision")
        item["kind"] = "answers_refused"
        return V.stage("validate", V.PROBLEMS, [item])
    items = [{"kind": "open_question", "id": q["id"], "needs": V.DECIDE, "revision": "new",
              "attention": q.get("attention"), "faces": q.get("faces"),
              "what": f"{q['id']} is open ({q.get('attention')}): {q.get('prompt') or q.get('reason') or ''}".strip(),
              "where": "validate/open.json"}
             for q in load_json(d / "open.json")]
    return V.stage("validate", V.item_verdict(items), items)


# --- 3. write ------------------------------------------------------------------------------------

_INCOMPLETE_LIST = re.compile(r"unanswered:\s*(.+)$")
_BLOCKED = re.compile(r"([A-Za-z_]+\.[\w.:\-]+) \(carried answer could not be applied: ([^)]*)\)")


def parse_incomplete(message):
    """The question IDs a refused write names, from 'incomplete: ...' (both of Specify's forms)."""
    ids = [(m.group(1), m.group(2)) for m in _BLOCKED.finditer(message)]
    if ids:
        return ids
    m = _INCOMPLETE_LIST.search(message)
    if m:
        return [(x.strip(), "unanswered") for x in m.group(1).split(",") if x.strip()]
    return []


def write_one(r, step, answers, d, stem):
    """Analyse and write one revision without --accept-defaults; returns (proc, report or None)."""
    analysis = d / f"{stem}.analysis.json"
    if r.run("specify-core", "analyse", step, "-o", analysis).returncode != 0:
        return r.log[-1], None
    proc = r.run("specify-core", "write", step, analysis, answers, "-o", d / f"{stem}.pmi.step",
                 "--intent", d / f"{stem}.intent.json", stdout_to=d / f"{stem}.write.json")
    report = load_json(d / f"{stem}.write.json") if proc.returncode == 0 else None
    return r.log[-1], report


# specify-core's not_written line for a planner dimension given up for an answered requirement.
RETAINED = re.compile(r"retained answered intent")


def readback(r, out, d):
    """Read the written STEP's PMI back with ``specify-core analyse`` (``resume.answers``) and compare it with
    the answers carried to the new revision. Independent of the intent Specify reported when writing."""
    back = d / "new.readback.json"
    if r.run("specify-core", "analyse", d / "new.pmi.step", "-o", back).returncode != 0:
        return [_tool_failure(r, "reading the written STEP back failed")]
    resume = load_json(back).get("resume") or {}
    got = resume.get("answers") or {}
    want = {k: v for k, v in load_json(out / "diff" / "answers.json").items() if not k.startswith("_")}
    items = []
    for k in sorted(set(want) | set(got)):
        if want.get(k) != got.get(k):
            items.append({"kind": "pmi_readback_mismatch", "id": k, "needs": V.PROBLEMS, "revision": "new",
                          "what": f"{k}: carried {want.get(k)!r}, the written STEP reads back {got.get(k)!r}",
                          "where": "write/new.readback.json#/resume"})
    for c in resume.get("conflicts") or []:
        items.append({"kind": "pmi_readback_conflict", "id": c.get("id"), "needs": V.PROBLEMS, "revision": "new",
                      "what": f"{c.get('id')}: the written STEP conflicts with the answer ({c})",
                      "where": "write/new.readback.json#/resume/conflicts"})
    return items


def stage_write(r, old, old_answers, new, out):
    d = out / "write"
    d.mkdir(parents=True, exist_ok=True)
    items, notes = [], []
    # The old revision is written from its own answers for the "before" drawing. Its answers are source,
    # so a refusal here is a problem with the source, not a decision about the change.
    if old is None:  # a first build has no old revision
        old_report = True
    else:
        log, old_report = write_one(r, old, old_answers, d, "old")
    if old_report is None:
        items.append({"kind": "old_write_failed", "id": "old", "needs": V.PROBLEMS, "where": "commands.json",
                      "what": f"the old revision's answers do not write: {log['stderr']}"})
    log, new_report = write_one(r, new, out / "diff" / "answers.json", d, "new")
    if new_report is None:
        msg = log["stderr"]
        if log["rc"] == 2 and "incomplete" in msg:
            parsed = parse_incomplete(msg)
            for qid, reason in parsed or [("write", msg)]:
                items.append({"kind": "write_stopped", "id": qid, "needs": V.DECIDE, "revision": "new",
                              "what": f"{qid}: {reason}", "where": "commands.json (specify-core write)"})
        else:
            items.append({"kind": "tool_failure", "id": "specify-core write", "needs": V.PROBLEMS,
                          "what": f"specify-core write (new) failed: exit {log['rc']}: {msg}",
                          "where": "commands.json"})
    else:
        for line in new_report.get("not_written", []):
            if RETAINED.search(line):
                # A shared planner dimension dropped because an answered requirement states the same thing:
                # the answer is written, so this is a note.
                notes.append({"kind": "not_written", "what": line, "where": "write/new.write.json#/not_written"})
            else:
                items.append({"kind": "not_written", "id": line, "needs": V.DECIDE, "revision": "new",
                              "what": f"a requirement was not written: {line}",
                              "where": "write/new.write.json#/not_written"})
        items += readback(r, out, d)
    return V.stage("write", V.item_verdict(items), items, notes,
                   written=new_report is not None, old_written=old_report is not None)


# --- 4. draw -------------------------------------------------------------------------------------

def _draw_one(r, step, spec, d, stem):
    """Plan, review and render one PMI'd STEP. Returns True when all three worked."""
    spec_args = ["--spec", spec] if spec else []
    ok = r.run("draftwright", "plan", step, *spec_args, stdout_to=d / f"{stem}.plan.json").returncode == 0
    proc = r.run("draftwright", "review", step, *spec_args)
    if proc.returncode == 0:
        review = json.loads(proc.stdout)
        review.pop("svg", None)  # the drawing itself is rendered below
        dump_json(review, d / f"{stem}.review.json")
    ok = ok and proc.returncode == 0
    ok = ok and r.run("draftwright", "render", step, *spec_args, "-o", d / stem,
                      "--formats", "svg,pdf").returncode == 0
    return ok


def stage_draw(r, spec, out, new_spec=None):
    d = out / "draw"
    d.mkdir(parents=True, exist_ok=True)
    w = out / "write"
    items, notes = [], []
    if not _draw_one(r, w / "old.pmi.step", spec, d, "old"):
        items.append(_tool_failure(r, "drawing the old revision failed"))
    spec_args = ["--spec", spec] if spec else []
    proc = r.run("draftwright", "diff", w / "old.pmi.step", w / "new.pmi.step", *spec_args, "-o", d / "diff")
    if proc.returncode != 0 or not (d / "diff" / "report.json").exists():
        items.append(_tool_failure(r, "draftwright diff failed"))
        return V.stage("draw", V.PROBLEMS, items, notes)
    report = load_json(d / "diff" / "report.json")
    if new_spec:
        # A person edited the Spec for the new revision: it replaces the carried one, and the planner checks
        # it against the new part (the stale-edit codes below), so Specify's carry items no longer apply.
        notes.append({"kind": "spec_decided", "what": "the Spec edited on the branch is used for the new drawing",
                      "where": "part.spec.json"})
    for e in [] if new_spec else report.get("spec", []):
        if e.get("class") not in SPEC_CARRIED:
            items.append({"kind": "stale_spec_edit", "id": e.get("path"), "needs": V.DECIDE,
                          "what": f"Spec entry {e.get('path')} is {e.get('class')}: {e.get('reason') or e.get('entry')}",
                          "where": "draw/diff/report.json#/spec"})
        else:
            notes.append({"kind": "spec_carried", "what": f"{e.get('path')} {e.get('class')}"
                          + (f" to {e['to']}" if e.get("to") else ""), "where": "draw/diff/report.json#/spec"})
    carried_spec = Path(new_spec) if new_spec else d / "diff" / "spec.json"
    shutil.copyfile(carried_spec, d / "new.spec.json")
    if not _draw_one(r, w / "new.pmi.step", carried_spec, d, "new"):
        items.append(_tool_failure(r, "drawing the new revision failed"))
    else:
        old_stale = _stale_codes(d / "old.plan.json")
        for p in _stale_codes(d / "new.plan.json") - old_stale:
            items.append({"kind": "stale_spec_edit", "id": p[1], "needs": V.DECIDE, "what": p[2],
                          "where": "draw/new.plan.json#/problems"})
    return V.stage("draw", V.item_verdict(items), items, notes, tool_verdict=report.get("verdict"),
                   tool_summary=report.get("summary"), annotations=report.get("annotations", []))


def _stale_codes(plan_path):
    plan = load_json(plan_path)
    return {(p["code"], p.get("id"), p.get("message")) for p in plan.get("problems", [])
            if p.get("code") in STALE_SPEC_CODES}


# --- 5. lint -------------------------------------------------------------------------------------

def findings(review):
    """The review's problems, lint and structural findings that matter: not info, not advisory."""
    out = []
    for key in ("problems", "lint", "structural"):
        for f in review.get(key, []):
            if f.get("severity") == "info" or f.get("impact") == "advisory":
                continue
            out.append(f)
    return out


_FEATURE_ID = re.compile(r"\b(f:[a-z_]+:)f\d+(?:_\d+)?")


def finding_key(f):
    """(code, message) with Draftwright feature IDs' face numbers blanked (``f:hole:f7`` -> ``f:hole:f#``).

    Feature IDs are numbered by face, and faces renumber whenever the geometry changes, so a finding about
    the same feature must not look new because its ID did. Messages that name features in words
    ("the ⌀8 hole on y") are compared as they are.
    """
    return f.get("code"), _FEATURE_ID.sub(r"\1f#", f.get("message") or "")


def new_findings(old_review, new_review):
    """Findings in the new drawing that the old one did not have, compared by ``finding_key``.
    A finding that occurs more often than before counts as new."""
    old = Counter(finding_key(f) for f in findings(old_review))
    out = []
    for f in findings(new_review):
        k = finding_key(f)
        if old[k] > 0:
            old[k] -= 1
        else:
            out.append(f)
    return out


def stage_lint(out):
    d = out / "draw"
    new = new_findings(load_json(d / "old.review.json"), load_json(d / "new.review.json"))
    items = []
    for f in new:
        needs = V.DECIDE if f.get("impact") == "decision" else V.PROBLEMS
        items.append({"kind": "new_drawing_finding", "id": f.get("id"), "code": f.get("code"), "needs": needs,
                      "impact": f.get("impact"), "severity": f.get("severity"), "tier": f.get("tier"),
                      "what": f"{f.get('code')}: {f.get('message')}", "where": "draw/new.review.json"})
    return V.stage("lint", V.item_verdict(items), items)


# --- the chain -----------------------------------------------------------------------------------

def run(old, new, answers, out, spec=None, allow_unpinned=False, person_answers=None, accepted=None,
        new_spec=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    old, new, answers = Path(old).resolve(), Path(new).resolve(), Path(answers).resolve()
    spec = Path(spec).resolve() if spec else None
    r = Runner()
    stages = []
    try:
        tools = check_versions(allow_unpinned)
        st, report = stage_diff(r, old, new, answers, out)
        if report is not None:
            st = resolve(st, out, person_answers, load_json(accepted) if accepted else ())
        stages.append(st)
        if report is None:
            stages += [V.skipped(s, "the diff failed") for s in ("validate", "write", "draw", "lint")]
        else:
            stages.append(stage_validate(r, new, out))
            st = stage_write(r, old, answers, new, out)
            stages.append(st)
            if not st["written"] or not st["old_written"]:
                why = "the PMI write stopped" if not st["written"] else "the old revision did not write"
                stages += [V.skipped("draw", why), V.skipped("lint", why)]
            else:
                st = stage_draw(r, spec, out, Path(new_spec).resolve() if new_spec else None)
                stages.append(st)
                if (out / "draw" / "new.review.json").exists() and (out / "draw" / "old.review.json").exists():
                    lint = stage_lint(out)
                    dw = st.get("tool_verdict")
                    if dw and dw != lint["verdict"]:
                        # Recorded, not used: draftwright diff pairs drawing items by face-numbered IDs, so
                        # renumbering alone can make it report changed values and new problems (FINDINGS.md).
                        lint["notes"].append({"kind": "verdict_disagrees", "where": "draw/diff/report.json",
                                              "what": f"draftwright diff said {dw} ({st.get('tool_summary')}); "
                                                      f"step-flow's lint says {lint['verdict']}"})
                    stages.append(lint)
                else:
                    stages.append(V.skipped("lint", "a drawing is missing"))
    except ToolError as e:
        tools = None
        stages.append(V.stage("setup", V.PROBLEMS, [{"kind": "tool_failure", "id": "tools", "needs": V.PROBLEMS,
                                                     "what": str(e), "where": "tools.lock"}]))
    except Exception as e:  # noqa: BLE001 - any crash is an error verdict with its evidence, never a traceback
        tools = None
        stages.append(V.stage("crash", V.PROBLEMS, [{
            "kind": "tool_failure", "id": "step-flow", "needs": V.PROBLEMS, "where": "commands.json",
            "what": f"step-flow crashed: {type(e).__name__}: {e}"}]))
    result = {
        "schema": "step-flow.verdict/1",
        "overall": V.overall(stages),
        "inputs": {"old": str(old), "new": str(new), "answers": str(answers), "spec": str(spec) if spec else None},
        "tools": tools,
        "stages": stages,
        "decisions": V.decisions(stages),
        "outputs": _outputs(out),
    }
    dump_json(result, out / "verdict.json")
    dump_json(r.log, out / "commands.json")
    (out / "summary.md").write_text(summary(result))
    return result


def first_build(new, out, answers=None, spec=None, allow_unpinned=False):
    """A part with no revision to carry from: nothing is carried, every requirement is to be specified.

    Validates ``answers`` (none = empty) against the part, writes the PMI without taking defaults, and draws
    the part: with its PMI when it was written, plain when it could not be. Verdict ``decide`` while any
    question is open."""
    out = Path(out)
    (out / "diff").mkdir(parents=True, exist_ok=True)
    new = Path(new).resolve()
    answers = Path(answers).resolve() if answers else None
    spec = Path(spec).resolve() if spec else None
    r = Runner()
    stages = [V.skipped("diff", "first build: no earlier revision to carry requirements from")]
    try:
        tools = check_versions(allow_unpinned)
        carried = out / "diff" / "answers.json"
        if answers:
            shutil.copyfile(answers, carried)
        else:
            carried.write_text("{}\n")
        stages.append(stage_validate(r, new, out))
        st = stage_write(r, None, None, new, out)
        stages.append(st)
        d = out / "draw"
        d.mkdir(parents=True, exist_ok=True)
        drawn = out / "write" / "new.pmi.step" if st["written"] else new
        items = []
        if not _draw_one(r, drawn, spec, d, "new"):
            items.append(_tool_failure(r, "drawing the part failed"))
        stages.append(V.stage("draw", V.item_verdict(items), items,
                              [] if st["written"] else [{"kind": "plain_drawing",
                                                         "what": "drawn without PMI: the requirements are not answered yet"}]))
        stages.append(V.skipped("lint", "first build: no earlier drawing to compare with"))
    except ToolError as e:
        tools = None
        stages.append(V.stage("setup", V.PROBLEMS, [{"kind": "tool_failure", "id": "tools", "needs": V.PROBLEMS,
                                                     "what": str(e), "where": "tools.lock"}]))
    except Exception as e:  # noqa: BLE001
        tools = None
        stages.append(V.stage("crash", V.PROBLEMS, [{
            "kind": "tool_failure", "id": "step-flow", "needs": V.PROBLEMS, "where": "commands.json",
            "what": f"step-flow crashed: {type(e).__name__}: {e}"}]))
    result = {"schema": "step-flow.verdict/1", "mode": "first_build", "overall": V.overall(stages),
              "inputs": {"new": str(new), "answers": str(answers) if answers else None,
                         "spec": str(spec) if spec else None},
              "tools": tools, "stages": stages, "decisions": V.decisions(stages), "outputs": _outputs(out)}
    dump_json(result, out / "verdict.json")
    dump_json(r.log, out / "commands.json")
    (out / "summary.md").write_text(summary(result))
    return result


def _outputs(out):
    names = {
        "diff_report": "diff/report.json", "diff_markdown": "diff/report.md", "carried_answers": "diff/answers.json",
        "new_pmi_step": "write/new.pmi.step", "new_intent": "write/new.intent.json",
        "old_drawing": "draw/old.svg", "new_drawing": "draw/new.svg",
        "old_drawing_pdf": "draw/old.pdf", "new_drawing_pdf": "draw/new.pdf",
        "carried_spec": "draw/new.spec.json", "drawing_changes": "draw/diff/changes.svg",
    }
    return {k: v for k, v in names.items() if (out / v).exists()}


ICON = {V.OK: "✅", V.DECIDE: "⚠️", V.PROBLEMS: "❌", None: "⏭️"}


def summary(result):
    """A short Markdown summary for a pull request comment."""
    stages = {s["stage"]: s for s in result["stages"]}
    lines = [f"## step-flow: {ICON[result['overall']]} `{result['overall']}`", ""]
    lines.append(" → ".join(f"{s['stage']} {ICON[s['verdict']]}" for s in result["stages"]))
    lines.append("")
    diff = stages.get("diff")
    if diff and diff.get("summary"):
        lines += ["**What changed:** " + diff["summary"], ""]
    if diff and diff["verdict"] is not None:
        carried = [m for m in diff.get("migrated", [])]
        lines.append(f"**Carried:** the requirements were carried by `specify-core diff` "
                     f"({len(carried)} renamed to new face numbers); see `diff/answers.json`.")
        lines.append("")
    if result["decisions"]:
        lines.append("**Needs a decision:**")
        for i in result["decisions"]:
            lines.append(f"- [{i['stage']}] {ICON[i['needs']]} {i['what']} (`{i['where']}`)")
        lines.append("")
    else:
        lines += ["**Needs a decision:** nothing.", ""]
    checks = [n for s in result["stages"] for n in s.get("notes", []) if n.get("kind") == "check"]
    if checks:
        lines.append("**To check** (carried to a changed feature):")
        lines += [f"- {n['what']}" for n in checks]
        lines.append("")
    ties = [n for s in result["stages"] for n in s.get("notes", []) if n.get("kind") == "frame_tie"]
    if ties:
        lines.append("**Stated tie:**")
        lines += [f"- {n['what']}" for n in ties]
        lines.append("")
    skipped = [s for s in result["stages"] if s.get("skipped")]
    for s in skipped:
        lines.append(f"_{s['stage']} skipped: {s['reason']}._")
    if skipped:
        lines.append("")
    outs = result["outputs"]
    if "old_drawing" in outs or "new_drawing" in outs:
        lines.append(f"**Drawings:** before `{outs.get('old_drawing', '—')}`, after `{outs.get('new_drawing', '—')}`"
                     + (f", changes `{outs['drawing_changes']}`" if "drawing_changes" in outs else ""))
    return "\n".join(lines).rstrip() + "\n"
