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
FILES = {"after": "part.pdf", "changes": "part.changes.svg"}


def conclusion(overall):
    return CONCLUSION[overall]


def combine(verdicts):
    """The worst of the parts' overall verdicts; ``problems`` if there are none to judge."""
    return V.worst(verdicts) or V.PROBLEMS


def drawing_links(part, repo, base_sha, head_sha, committed, run_url, has_after=True):
    """Before (main's committed drawing), after and changes. After is the committed file on the PR branch;
    for a fork, which cannot be committed to, the run's artifacts."""
    blob = f"https://github.com/{repo}/blob"
    links = {"before": f"{blob}/{base_sha}/demo/{part}/part.pdf"}
    if not has_after:
        return {"before": links["before"]}
    if committed:
        links["after"] = f"{blob}/{head_sha}/demo/{part}/{FILES['after']}"
        links["changes"] = f"{blob}/{head_sha}/demo/{part}/{FILES['changes']}"
    else:
        links["after"] = links["changes"] = run_url  # a fork's PR is not committed to: see the run's artifacts
    return links


def _notes(result, kind):
    return [n for s in result["stages"] for n in s.get("notes", []) if n.get("kind") == kind]


def render_part(part, result, links):
    """Markdown for one part: verdict, what changed, carried, decisions, to check, drawings."""
    overall = result["overall"]
    stages = {s["stage"]: s for s in result["stages"]}
    out = [f"### `demo/{part}/part.step`: {ICON[overall]} `{overall}`", ""]
    out.append(" → ".join(f"{s['stage']} {ICON.get(s['verdict'], '⏭️')}" for s in result["stages"]))
    out.append("")
    diff = stages.get("diff") or {}
    if diff.get("summary"):
        out += [f"**What changed:** {diff['summary']}", ""]
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
    if result["decisions"]:
        label = "Problems and decisions" if overall == V.PROBLEMS else "Needs a decision"
        out.append(f"**{label}:**")
        for i in result["decisions"]:
            out.append(f"- {ICON[i['needs']]} [{i['stage']}] {i['what']}")
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
        body.append("To answer: edit `part.answers.json` (answer the question) or `part.accepted.json` (list a "
                    "requirement id to drop) on this branch and push. The next run re-checks. "
                    "See the README, \"GitHub flow\".")
    return "\n".join(head + body).rstrip() + "\n", overall


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m step_flow.github", description=__doc__)
    ap.add_argument("root")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--base-sha", required=True)
    ap.add_argument("--head-sha", required=True)
    ap.add_argument("--run-url", required=True)
    ap.add_argument("--committed", action="store_true", help="the results were committed to the PR branch")
    a = ap.parse_args(argv)
    root = Path(a.root)
    parts = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        vf = d / "verdict.json"
        if vf.exists():
            result = json.loads(vf.read_text())
            links = drawing_links(d.name, a.repo, a.base_sha, a.head_sha, a.committed, a.run_url,
                                  has_after="new_drawing_pdf" in result.get("outputs", {}))
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
        "conclusion": conclusion(overall), "title": TITLE[overall], "summary": markdown}, ensure_ascii=False))
    print(overall)
    return 0


if __name__ == "__main__":
    sys.exit(main())
