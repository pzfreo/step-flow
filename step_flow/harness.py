"""``step-flow-harness``: run the pipeline on every scenario and score it against the scenario's truth.

    step-flow-harness run [--scenario NAME] -o OUT/      score the scenarios; exit 1 on any silent-wrong
    step-flow-harness build [--check] [--scenario NAME]  regenerate v1/v2 STEP files from build.py
    step-flow-harness answers [--scenario NAME]          regenerate v1.answers.json from v1.chosen.json

A scenario is a directory under scenarios/ with build.py, v1.step, v2.step, v1.chosen.json,
v1.answers.json, part.spec.json (optional) and expect.toml.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import expect as E
from . import pipeline
from .tools import Runner, check_versions, dump_json, load_json

ROOT = Path(__file__).resolve().parent.parent / "scenarios"


def scenarios(only=None, root=ROOT):
    dirs = sorted(p for p in root.iterdir() if (p / "build.py").exists())
    if only:
        dirs = [p for p in dirs if p.name in only]
        missing = set(only) - {p.name for p in dirs}
        if missing:
            raise SystemExit(f"no such scenario: {', '.join(sorted(missing))}")
    return dirs


# --- run -----------------------------------------------------------------------------------------

def run_one(sdir, out, allow_unpinned=False):
    exp = E.load(sdir / "expect.toml")
    spec = sdir / "part.spec.json"
    result = pipeline.run(sdir / "v1.step", sdir / "v2.step", sdir / "v1.answers.json", out,
                          spec=spec if spec.exists() else None, allow_unpinned=allow_unpinned)
    rows = E.score(exp, E.Run(out, result))
    return {"scenario": sdir.name, "changed": exp.get("changed", ""), "expected": exp["verdict"],
            "got": result["overall"], "stages": {s["stage"]: s["verdict"] for s in result["stages"]},
            "tally": E.tally(rows), "rows": rows, "out": str(out),
            "decisions": [f"[{i['stage']}] {i['what']}" for i in result["decisions"]],
            "findings": exp.get("findings", [])}


def scorecard_md(results, tools):
    lines = ["# step-flow scorecard", ""]
    lines.append("Tools: " + ", ".join(f"{k} {v['version']}" for k, v in (tools or {}).items()))
    lines.append("")
    total = {c: sum(r["tally"][c] for r in results) for c in E.CATEGORIES}
    lines.append("| scenario | expected | got | stages | " + " | ".join(E.CATEGORIES) + " |")
    lines.append("|---|---|---|---|" + "---|" * len(E.CATEGORIES))
    for r in results:
        st = " ".join(f"{k}:{v or 'skip'}" for k, v in r["stages"].items())
        lines.append(f"| {r['scenario']} | {r['expected']} | {r['got']} | {st} | "
                     + " | ".join(str(r["tally"][c]) for c in E.CATEGORIES) + " |")
    lines.append("| **total** | | | | " + " | ".join(f"**{total[c]}**" for c in E.CATEGORIES) + " |")
    lines.append("")
    for r in results:
        lines += [f"## {r['scenario']}", "", r["changed"].strip(), ""]
        for row in r["rows"]:
            mark = "" if row["category"] in ("correct-automatic", "correct-ask") else " **←**"
            detail = f" — {row['detail']}" if row["detail"] else ""
            lines.append(f"- `{row['category']}` {row['what']}{detail}{mark}")
        if r["decisions"]:
            lines += ["", "Named by the chain:"] + [f"- {d}" for d in r["decisions"]]
        for f in r["findings"]:
            lines += ["", f"Known finding: {f}"]
        lines.append("")
    return "\n".join(lines)


def cmd_run(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tools = check_versions(a.allow_unpinned)
    results = [run_one(s, out / s.name, a.allow_unpinned) for s in scenarios(a.scenario)]
    dump_json({"schema": "step-flow.scorecard/1", "tools": tools, "scenarios": results}, out / "scorecard.json")
    (out / "scorecard.md").write_text(scorecard_md(results, tools))
    for r in results:
        t = r["tally"]
        print(f"{r['scenario']:<10} expected {r['expected']:<8} got {r['got']:<8} "
              + " ".join(f"{c}={t[c]}" for c in E.CATEGORIES if t[c]))
    print(f"scorecard: {out / 'scorecard.md'}")
    if any(r["tally"]["error"] for r in results):
        return 2
    return 1 if any(r["tally"]["silent-wrong"] for r in results) else 0


# --- build ---------------------------------------------------------------------------------------

def faces_summary(analysis):
    return [(f["kind"], round(f["area"], 3), tuple(round(c, 3) for c in f["centroid"])) for f in analysis["faces"]]


def cmd_build(a):
    """Regenerate the STEP files. STEP headers carry a timestamp, so --check compares geometry (Specify's
    analysis of each face, in order), not bytes."""
    bad = 0
    for s in scenarios(a.scenario):
        if not a.check:
            subprocess.run([sys.executable, s / "build.py", s], check=True)
            print(f"built {s.name}")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, s / "build.py", tmp], check=True)
            for v in ("v1", "v2"):
                r = Runner()
                summ = []
                for step in (s / f"{v}.step", Path(tmp) / f"{v}.step"):
                    an = Path(tmp) / f"{v}.{len(summ)}.analysis.json"
                    r.run("specify-core", "analyse", step, "-o", an)
                    summ.append(faces_summary(load_json(an)))
                same = summ[0] == summ[1]
                bad += not same
                print(f"{s.name}/{v}.step: {'same geometry' if same else 'DIFFERS from build.py'}")
    return 1 if bad else 0


# --- answers -------------------------------------------------------------------------------------

def cmd_answers(a):
    """v1.answers.json from v1.chosen.json: every question answered explicitly, then exported.

    The export (``questions --resolve-defaults``) is used only to stamp Specify's evidence on the file;
    it must add no answer and change no value, or the chosen answers are incomplete and this refuses.
    """
    check_versions(a.allow_unpinned)
    bad = 0
    for s in scenarios(a.scenario):
        with tempfile.TemporaryDirectory() as tmp:
            r = Runner()
            an = Path(tmp) / "v1.analysis.json"
            r.run("specify-core", "analyse", s / "v1.step", "-o", an)
            chosen = s / "v1.chosen.json"
            proc = r.run("specify-core", "questions", an, "--answers", chosen, "--open")
            open_q = [q["id"] for q in json.loads(proc.stdout or "[]")]
            if proc.returncode or open_q:
                print(f"{s.name}: refused: chosen answers leave questions open: {open_q} {r.log[-1]['stderr']}")
                bad += 1
                continue
            proc = r.run("specify-core", "questions", an, "--answers", chosen, "--resolve-defaults",
                         "--step", s / "v1.step")
            if proc.returncode:
                print(f"{s.name}: export refused: {r.log[-1]['stderr']}")
                bad += 1
                continue
            exported, mine = json.loads(proc.stdout), load_json(chosen)
            added = sorted(set(exported) - set(mine) - {"_specify"})
            changed = sorted(k for k in mine if exported.get(k) != mine[k])
            if added or changed:
                print(f"{s.name}: refused: the export added {added} / changed {changed}")
                bad += 1
                continue
            (s / "v1.answers.json").write_text(proc.stdout)
            print(f"{s.name}: v1.answers.json written ({len(mine)} explicit answers)")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="step-flow-harness", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "build", "answers"):
        p = sub.add_parser(name)
        p.add_argument("--scenario", action="append", help="only this scenario (repeatable)")
        p.add_argument("--allow-unpinned", action="store_true")
        if name == "run":
            p.add_argument("-o", "--out", required=True)
        if name == "build":
            p.add_argument("--check", action="store_true", help="regenerate to a temporary directory and compare")
    a = ap.parse_args(argv)
    return {"run": cmd_run, "build": cmd_build, "answers": cmd_answers}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
