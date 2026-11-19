"""Render step-flow results for a pull request: the one comment, the check, and the job summary.

``python -m step_flow.github OUTROOT --repo R --base-sha S --head-sha S --run-url U [--committed]`` reads
``OUTROOT/<part>/verdict.json`` for every part, and writes ``OUTROOT/comment.md`` and ``OUTROOT/check.json``
(``conclusion``, ``title``, ``summary``). The workflow posts them; nothing here talks to GitHub.
"""

import argparse
import json
import sys
from pathlib import Path

from . import verdict as V

MARKER = "<!-- step-flow -->"
ICON = {V.OK: "✅", V.DECIDE: "⚠️", V.PROBLEMS: "❌"}
# A check run's conclusion for each overall verdict: decide is neutral ("needs input").
CONCLUSION = {V.OK: "success", V.DECIDE: "neutral", V.PROBLEMS: "failure"}
TITLE = {V.OK: "step-flow: ok", V.DECIDE: "step-flow: needs input", V.PROBLEMS: "step-flow: problems"}
LIST_SHOWN = 10  # decisions listed before the rest fold away
FILES = {"after": "part.pdf", "changes": "part.changes.svg"}


def conclusion(overall):
    return CONCLUSION[overall]


def combine(verdicts):
    """The worst of the parts' overall verdicts; ``problems`` if there are none to judge."""
    return V.worst(verdicts) or V.PROBLEMS


def actions(same_repo, overall):
    """What the workflow may do after a run. A fork's PR gets a read-only token and cannot be pushed to, so
    it is checked only: no commit-back, no comment, no check run; the job itself fails on ``problems``."""
    return {"commit_back": same_repo, "comment": same_repo, "check": same_repo,
            "fail_job": (not same_repo) and overall == V.PROBLEMS}


def drawing_links(part, repo, base_sha, head_sha, committed, run_url, has_after=True, has_before=True,
                  has_changes=True):
    """Before (main's committed drawing), after and changes. After is the committed file on the PR branch;
    for a fork, which cannot be committed to, the run's artifacts."""
    blob = f"https://github.com/{repo}/blob"
    links = {"before": f"{blob}/{base_sha}/demo/{part}/part.pdf"} if has_before else {}
    if not has_after:
        return {"before": links["before"]}
    if committed:
        links["after"] = f"{blob}/{head_sha}/demo/{part}/{FILES['after']}"
        links["changes"] = f"{blob}/{head_sha}/demo/{part}/{FILES['changes']}"
    else:
        links["after"] = links["changes"] = run_url  # a fork's PR is not committed to: see the run's artifacts
    if not has_changes:
        del links["changes"]
    return links


def _notes(result, kind):
    return [n for s in result["stages"] for n in s.get("notes", []) if n.get("kind") == kind]


CLASS = {"orphaned": "removed", "adapted": "changed", "matched": "unchanged", "added": "added", "new": "added"}


def _value(v):
    return "(" + ", ".join(f"{x:g}" if isinstance(x, (int, float)) else str(x) for x in v) + ")" \
        if isinstance(v, list) else str(v)


def what_changed(result):
    """Lines saying what changed, built from the diff stage's features (structured, from Specify's report), so
    the text follows step-flow's state. Specify's own summary sentence is kept verbatim in the comment's
    details, never edited."""
    diff = next((s for s in result["stages"] if s["stage"] == "diff"), {})
    lines = []
    for f in diff.get("features", []):
        cls = CLASS.get(f.get("class"), f.get("class") or "changed")
        if cls == "unchanged":
            continue
        line = f"{cls}: {f.get('what')} at {_value(f.get('at'))}"
        moves = [f"{k} {_value(c.get('old'))} → {_value(c.get('new'))}" for k, c in (f.get("changes") or {}).items()]
        lines.append(line + (" (" + "; ".join(moves) + ")" if moves else ""))
    return lines


def render_part(part, result, links):
    """Markdown for one part: verdict, what changed, carried, decisions, to check, drawings."""
    overall = result["overall"]
    stages = {s["stage"]: s for s in result["stages"]}
    out = [f"### `demo/{part}/part.step`: {ICON[overall]} `{overall}`", ""]
    out.append(" → ".join(f"{s['stage']} {ICON.get(s['verdict'], '⏭️')}" for s in result["stages"]))
    out.append("")
    diff = stages.get("diff") or {}
    if result.get("mode") == "first_build":
        out += ["**What changed:** new part, first build. Nothing to carry from an earlier revision: every "
                "requirement is to be specified.", ""]
    elif diff.get("verdict") is not None:
        changes = what_changed(result)
        out += ["**What changed:**" + ("" if changes else " no feature changed.")]
        out += [f"- {c}" for c in changes]
        out.append("")
        if diff.get("summary"):
            out += ["<details><summary>Specify's report</summary>", "", diff["summary"], "", "</details>", ""]
    if diff.get("verdict") is not None:
        decided = _notes(result, "decided")
        line = (f"**Carried:** requirements were carried to the new geometry by Specify "
                f"({len(diff.get('migrated', []))} renamed to new face numbers)")
        if decided:
            line += f"; {len(decided)} decided by you"
        out += [line + ".", ""]
        for n in decided:
            out.append(f"- decided: {n['what']}")
        if decided:
            out.append("")
    specs = _notes(result, "spec_decided")
    if specs:
        out += ["**Spec:** the Spec edited on this branch is used for the new drawing.", ""]
    if result["decisions"]:
        label = "Problems and decisions" if overall == V.PROBLEMS else "Needs a decision"
        # One line per id: validate and write both name an unanswered question.
        seen, lines = set(), []
        for i in result["decisions"]:
            if i.get("id") in seen:
                continue
            seen.add(i.get("id"))
            lines.append(f"- {ICON[i['needs']]} [{i['stage']}] {i['what']}")
        out.append(f"**{label}** ({len(lines)}):")
        out += lines[:LIST_SHOWN]
        if len(lines) > LIST_SHOWN:
            out += ["", f"<details><summary>{len(lines) - LIST_SHOWN} more</summary>", ""]
            out += lines[LIST_SHOWN:]
            out += ["", "</details>"]
        out.append("")
    else:
        out += ["**Needs a decision:** nothing.", ""]
    checks = _notes(result, "check")
    if checks:
        out.append("**To check** (carried to a feature that changed):")
        out += [f"- {n['what']}" for n in checks]
        out.append("")
    ties = _notes(result, "frame_tie")
    if ties:
        out.append("**Stated tie:**")
        out += [f"- {n['what']}" for n in ties]
        out.append("")
    skipped = [s for s in result["stages"] if s.get("skipped")]
    out += [f"_{s['stage']} skipped: {s['reason']}._" for s in skipped]
    if skipped:
        out.append("")
    if links:
        out.append("**Drawings:** " + " · ".join(f"[{k}]({links[k]})" for k in ("before", "after", "changes")
                                                  if k in links))
        out.append("")
    return "\n".join(out)


def render(parts, how_to=True):
    """``parts``: list of ``(name, result_or_None, links_or_None, note)``. Returns ``(markdown, overall)``.
    A part with no result (no baseline on main, or step-flow did not finish) says so in its note."""
    verdicts, body = [], []
    for name, result, links, note in parts:
        if result is None:
            body += [f"### `demo/{name}/part.step`: ⏭️ not checked", "", note, ""]
            continue
        verdicts.append(result["overall"])
        body.append(render_part(name, result, links))
    overall = combine(verdicts) if verdicts else V.OK
    head = [f"## step-flow: {ICON[overall]} `{overall}`", ""]
    if overall == V.DECIDE and how_to:
        body.append("To answer: edit `part.answers.json` (answer the question), `part.accepted.json` (list a "
                    "requirement id to drop) or `part.spec.json` (a drawing Spec entry) on this branch and push. "
                    "The next run re-checks. "
                    "See the README, \"GitHub flow\".")
    return "\n".join(head + body).rstrip() + "\n", overall


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m step_flow.github", description=__doc__)
    ap.add_argument("root")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--run-url", required=True)
    ap.add_argument("--fork", action="store_true", help="the PR is from a fork: check only")
    ap.add_argument("--committed", action="store_true", help="the results were committed to the PR branch")
    a = ap.parse_args(argv)
    root = Path(a.root)
    parts = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        vf = d / "verdict.json"
        if vf.exists():
            result = json.loads(vf.read_text())
            links = drawing_links(d.name, a.repo, a.base_sha, a.head_sha, a.committed, a.run_url,
                                  has_after="new_drawing_pdf" in result.get("outputs", {}),
                                  has_before=result.get("mode") != "first_build",
                                  has_changes=result.get("mode") != "first_build")
            parts.append((d.name, result, links, ""))
        else:
            note = (d / "note.txt").read_text().strip() if (d / "note.txt").exists() else "step-flow did not finish."
            parts.append((d.name, None, None, note))
    if not parts:
        print("no parts", file=sys.stderr)
        return 2
    markdown, overall = render(parts)
    (root / "comment.md").write_text(MARKER + "\n" + markdown)
    (root / "check.json").write_text(json.dumps({
        "conclusion": conclusion(overall), "title": TITLE[overall], "summary": markdown,
        "actions": actions(not a.fork, overall)}, ensure_ascii=False))
    print(overall)
    return 0


if __name__ == "__main__":
    sys.exit(main())
