"""A scenario's expectations (expect.toml) and how a pipeline run is scored against them.

Every check is structural: which requirement is on which feature (features are found by geometry in
Specify's analysis of the revision, never by face number), which values the drawing's own plan prints,
which items the chain names for a decision. Nothing compares output bytes or hashes.

Each expectation scores as one of:

- ``correct-automatic``: the chain did the right thing without asking;
- ``correct-ask``: the chain named what the expectation says must be decided;
- ``unnecessary-ask``: the chain stopped or asked where it should have carried on its own;
- ``silent-wrong``: the chain passed something wrong or lost without naming it: the failure that matters;
- ``error``: the expectation could not be checked (a tool failed, or the expectation names nothing).
"""

import math
import re
import tomllib
from pathlib import Path

from .tools import load_json

CATEGORIES = ("correct-automatic", "correct-ask", "unnecessary-ask", "silent-wrong", "error")
TOL = 0.01


def load(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


# --- finding features by geometry ----------------------------------------------------------------

def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(a):
    return math.sqrt(_dot(a, a))


def hole_faces(analysis, at, d):
    """Cylinder faces of diameter d whose axis passes through ``at`` ([x, y] means along z)."""
    out = set()
    for f in analysis["faces"]:
        if f.get("kind") != "cylinder" or abs(2 * f["radius"] - d) > TOL:
            continue
        axis, origin = f["direction"], f["origin"]
        p = list(at) + [origin[2]] if len(at) == 2 else list(at)
        v = _sub(p, origin)
        off = _sub(v, [c * _dot(v, axis) for c in axis])
        if _norm(off) <= TOL:
            out.add(f["id"])
    return out


def plane_faces(analysis, normal, through):
    out = set()
    for f in analysis["faces"]:
        if f.get("kind") != "plane":
            continue
        if _norm(_sub(f["direction"], normal)) > 1e-6:
            continue
        if abs(_dot(_sub(f["centroid"], through), normal)) <= TOL:
            out.add(f["id"])
    return out


def locate(analysis, on):
    """The face set an ``on`` table names: {hole={at,d}}, {holes=[{at,d},...]} or {plane={normal,through}}."""
    if on is None:
        return None
    faces = set()
    if "hole" in on:
        faces |= hole_faces(analysis, on["hole"]["at"], on["hole"]["d"])
    for h in on.get("holes", []):
        faces |= hole_faces(analysis, h["at"], h["d"])
    if "plane" in on:
        faces |= plane_faces(analysis, on["plane"]["normal"], on["plane"]["through"])
    return faces


def describe_on(on):
    if on is None:
        return "the part"
    if "hole" in on:
        h = on["hole"]
        return f"the Ø{h['d']} hole at {tuple(h['at'])}"
    if "holes" in on:
        return "the holes " + ", ".join(f"Ø{h['d']} at {tuple(h['at'])}" for h in on["holes"])
    if "plane" in on:
        return f"the face normal {tuple(on['plane']['normal'])} through {tuple(on['plane']['through'])}"
    return str(on)


# --- what an answer ID refers to -----------------------------------------------------------------

def base(qid):
    return qid.split(":", 1)[0]


def answer_faces(qid, answers, analysis):
    """The faces an answer applies to on this revision: a feature ID's faces, a datum's chosen faces."""
    if ":" in qid:
        fid = qid.split(":", 1)[1]
        for f in analysis["features"]:
            if f["id"] == fid:
                return set(f["faces"])
        return None
    if qid.startswith("datum."):
        letter = qid.split(".")[1]
        v = answers.get(f"datum.{letter}")
        return set(v) if isinstance(v, list) else None
    return set()


# --- the run's evidence --------------------------------------------------------------------------

class Run:
    """What a pipeline run left in OUT/, read lazily."""

    def __init__(self, out, result):
        self.out, self.result = Path(out), result
        self._cache = {}

    def _json(self, rel):
        if rel not in self._cache:
            p = self.out / rel
            self._cache[rel] = load_json(p) if p.exists() else None
        return self._cache[rel]

    @property
    def answers(self):
        return self._json("diff/answers.json")

    @property
    def new_analysis(self):
        return self._json("validate/new.analysis.json")

    @property
    def old_analysis(self):
        return self._json("write/old.analysis.json")

    @property
    def readback(self):
        """``resume.answers`` of ``specify-core analyse`` on the written STEP, or None."""
        back = self._json("write/new.readback.json")
        return None if back is None else (back.get("resume") or {}).get("answers") or {}

    @property
    def intent(self):
        return self._json("write/new.intent.json")

    def plan(self, which):
        return self._json(f"draw/{which}.plan.json")

    def stage(self, name):
        return next((s for s in self.result["stages"] if s["stage"] == name), None)

    @property
    def decisions(self):
        return [i for i in self.result["decisions"] if i.get("needs") == "decide"]

    def notes(self, kind):
        return [n for s in self.result["stages"] for n in s.get("notes", []) if n.get("kind") == kind]


def printed(plan):
    """Every value the drawing prints, as text: dimension labels, GD&T frames, requirements, notes."""
    out = []
    for d in plan.get("dimensions", []):
        if (d.get("state") or {}).get("kind") == "shown" and d.get("label"):
            out.append(d["label"])
    for g in plan.get("gdt", []):
        if g.get("label"):
            out.append(g["label"])
    for r in plan.get("requirements", []):
        if (r.get("state") or {}).get("kind") == "shown" and r.get("text"):
            out.append(r["text"])
    for n in plan.get("notes", []):
        out += n.get("rows", [])
    return out


# --- scoring -------------------------------------------------------------------------------------

def score(expect, run):
    rows = []

    def row(kind, what, category, detail=""):
        rows.append({"check": kind, "what": what, "category": category, "detail": detail})

    # The chain's verdict.
    want, got = expect["verdict"], run.result["overall"]
    # ok < decide < problems. Same: right. Anything reported as ok that is not: silent-wrong. A problem reported
    # as only a decision understates it: silent-wrong. Reported worse than the truth: unnecessary-ask.
    rank = {"ok": 0, "decide": 1, "problems": 2}
    if got == want:
        cat = "correct-automatic" if want == "ok" else "correct-ask"
    elif rank.get(got, 2) < rank[want]:
        cat = "silent-wrong"
    else:
        cat = "unnecessary-ask"
    if any(i.get("kind") == "tool_failure" for i in run.result["decisions"]):
        cat = "error"
    row("verdict", f"chain verdict {want}", cat, f"got {got}")

    answers, new_a, old_a = run.answers, run.new_analysis, run.old_analysis
    # Carried requirements are checked on what the written STEP reads back as (independent of Specify's own
    # intent), when a STEP was written; the read-back must also equal the carried answers.
    if run.readback is not None:
        carried_only = {k: v for k, v in (answers or {}).items() if not k.startswith("_")}
        bad = [i["id"] for i in run.result["decisions"] if i.get("kind", "").startswith("pmi_readback")]
        row("readback", "the written STEP reads back as the carried answers",
            "silent-wrong" if bad or run.readback != carried_only else "correct-automatic",
            ", ".join(bad) or "")
        answers = dict(run.readback)

    # Requirements that must be carried to a feature of the new revision.
    for e in expect.get("carried", []):
        what = f"{e['question']}" + (f" = {e['value']!r}" if "value" in e else "") + f" on {describe_on(e.get('on'))}"
        if answers is None or new_a is None:
            row("carried", what, "error", "no carried answers or new analysis")
            continue
        want_faces = locate(new_a, e.get("on"))
        if e.get("on") is not None and not want_faces:
            row("carried", what, "error", "the expectation's feature is not in the new revision")
            continue
        hits, elsewhere = [], []
        for k, v in answers.items():
            if k.startswith("_") or base(k) != e["question"]:
                continue
            if "value" in e and v != e["value"]:
                continue
            faces = answer_faces(k, answers, new_a)
            (hits if e.get("on") is None or faces == want_faces else elsewhere).append(k)
        asked = [i for i in run.decisions if base(i["id"]) == e["question"]]
        if hits:
            row("carried", what, "correct-automatic", ", ".join(hits))
        elif elsewhere:
            row("carried", what, "silent-wrong", "carried to another feature: " + ", ".join(elsewhere))
        elif asked:
            row("carried", what, "unnecessary-ask", "not carried; asked: " + ", ".join(i["id"] for i in asked))
        else:
            row("carried", what, "silent-wrong", "not carried and not named for a decision")

    # Requirements that must not be carried anywhere (the feature is gone or ambiguous).
    for e in expect.get("not_carried", []):
        what = f"{e['question']}" + (f" = {e['value']!r}" if "value" in e else "") + " is not carried anywhere"
        if answers is None:
            row("not_carried", what, "error", "no carried answers")
            continue
        found = [k for k, v in answers.items() if not k.startswith("_") and base(k) == e["question"]
                 and ("value" not in e or v == e["value"])]
        if e.get("not_on") is not None and new_a is not None:
            bad = locate(new_a, e["not_on"])
            found = [k for k in found if answer_faces(k, answers, new_a) == bad]
        row("not_carried", what, "silent-wrong" if found else "correct-automatic", ", ".join(found))

    # Items that must be named for a decision.
    for e in expect.get("ask", []):
        what = f"{e['question']} on {describe_on(e.get('on'))} is named for a decision"
        analysis = old_a if e.get("revision", "new") == "old" else new_a
        want_faces = locate(analysis, e.get("on")) if analysis else None
        if e.get("on") is not None and not want_faces:
            row("ask", what, "error", f"the expectation's feature is not in the {e.get('revision', 'new')} revision")
            continue
        named = []
        for i in run.decisions:
            if base(i["id"]) != e["question"]:
                continue
            if e.get("on") is None:
                named.append(i)
                continue
            faces = answer_faces(i["id"], {}, analysis)
            if faces == want_faces:
                named.append(i)
        if named:
            row("ask", what, "correct-ask", "; ".join(f"[{i['stage']}] {i['id']}" for i in named))
        else:
            carried = [k for k in (answers or {}) if not k.startswith("_") and base(k) == e["question"]]
            row("ask", what, "silent-wrong",
                "not named" + (f"; carried as {', '.join(carried)}" if carried else ""))

    # Requirements that must be listed to check (carried to a changed feature).
    for e in expect.get("noted", []):
        what = f"{e['question']} on {describe_on(e.get('on'))} is listed to check"
        want_faces = locate(new_a, e.get("on")) if new_a else None
        hits = [n for n in run.notes("check") if base(n["id"]) == e["question"]
                and (e.get("on") is None or answer_faces(n["id"], answers or {}, new_a) == want_faces)]
        row("noted", what, "correct-automatic" if hits else "silent-wrong",
            ", ".join(n["id"] for n in hits) or "not listed")

    # A tie the tools broke must be stated, not silent.
    for kind in expect.get("stated", []):
        what = f"the report states {kind.replace('_', ' ')}"
        hits = run.notes(kind)
        row("stated", what, "correct-automatic" if hits else "silent-wrong",
            "; ".join(n["what"] for n in hits) or "not stated")

    # PMI written into the new STEP (the intent Specify wrote).
    for e in expect.get("pmi", []):
        fields = {k: v for k, v in e.items() if k not in ("on", "kind")}
        what = f"PMI {e['kind']} {fields} on {describe_on(e.get('on'))}"
        if run.intent is None:
            row("pmi", what, "unnecessary-ask" if expect["verdict"] == "ok" else "error", "no PMI was written")
            continue
        want_faces = locate(new_a, e.get("on"))
        rows_ = run.intent.get("requirements", []) + [dict(r, kind="datum") for r in run.intent.get("datums", [])]
        cands = [r for r in rows_ if r.get("kind") == e["kind"]
                 and all(_same(r.get(k), v) for k, v in fields.items())]
        exact = [r for r in cands if want_faces is None or set(r.get("faces", [])) == want_faces]
        if exact:
            row("pmi", what, "correct-automatic")
        elif cands:
            row("pmi", what, "silent-wrong", "on faces " + ", ".join(str(r.get("faces")) for r in cands))
        else:
            row("pmi", what, "silent-wrong", "not written")

    # What the new drawing prints, read from the drawing's own plan.
    drawing = expect.get("drawing", {})
    checks = [("prints", s) for s in drawing.get("prints", [])] + [("absent", s) for s in drawing.get("absent", [])]
    checks += [("spec_edit", s) for s in drawing.get("spec_edits", [])]
    if drawing.get("same_as_old"):
        checks.append(("same_as_old", None))
    if checks:
        new_plan, old_plan = run.plan("new"), run.plan("old")
        # Only a draw or lint item about the very value in question may excuse a wrong print.
        drawn_asks = [i for i in run.result["decisions"] if i["stage"] in ("draw", "lint")]

        def excused(*texts):
            def hit(t, i):
                # A bare number is a dimension value that also appears in coordinates and sizes in any message,
                # so it only counts when the item's own id carries it; a longer label counts in the message too.
                where = str(i.get("id", "")) if re.fullmatch(r"[\d.]+", t) else f"{i.get('what', '')} {i.get('id', '')}"
                return re.search(r"(?<![\w.])" + re.escape(t) + r"(?![\w]|\.\d)", where) is not None
            return any(hit(t, i) for i in drawn_asks for t in texts if t)
        for kind, text in checks:
            what = {"prints": f"drawing prints {text!r}", "absent": f"drawing does not print {text!r}",
                    "spec_edit": f"the Spec's edit still applies to {text!r}",
                    "same_as_old": "drawing prints the same values as before"}[kind]
            if new_plan is None:
                row("drawing", what, "unnecessary-ask" if expect["verdict"] == "ok" else "error", "no new drawing")
                continue
            labels = printed(new_plan)
            if kind == "prints":
                ok, detail = text in labels, ""
            elif kind == "absent":
                ok, detail = text not in labels, ""
            elif kind == "spec_edit":
                edited = set((new_plan.get("spec") or {}).get("dimensions", {}))
                on = [d.get("label") for d in new_plan.get("dimensions", []) if d["id"] in edited]
                ok, detail = text in on, f"the Spec's dimension edits are on {on}"
            else:
                a, b = sorted(printed(old_plan)), sorted(labels)
                ok = a == b
                detail = "" if ok else f"only before: {sorted(set(a) - set(b))}; only after: {sorted(set(b) - set(a))}"
            if ok:
                row("drawing", what, "correct-automatic")
            else:
                if kind == "same_as_old":
                    named = sorted(set(a) ^ set(b))
                else:
                    named = [text]
                row("drawing", what, "correct-ask" if excused(*named) else "silent-wrong",
                    detail or f"prints {labels}")
    return rows


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-6
    return a == b


def tally(rows):
    out = {c: 0 for c in CATEGORIES}
    for r in rows:
        out[r["category"]] += 1
    return out
