"""Scoring against a synthetic run: a plate with two holes, so each category can be produced on purpose."""
import unittest

from step_flow import expect as E

ANALYSIS = {
    "faces": [
        {"id": 0, "kind": "plane", "centroid": [0, 30, 5], "direction": [-1, 0, 0], "area": 600},
        {"id": 1, "kind": "plane", "centroid": [50, 30, 0], "direction": [0, 0, -1], "area": 6000},
        {"id": 2, "kind": "cylinder", "centroid": [20, 15, 5], "direction": [0, 0, 1], "origin": [20, 15, 0],
         "radius": 3, "area": 1},
        {"id": 3, "kind": "cylinder", "centroid": [80, 15, 5], "direction": [0, 0, 1], "origin": [80, 15, 0],
         "radius": 4, "area": 1},
    ],
    "features": [{"id": "holes:2", "faces": [2]}, {"id": "holes:3", "faces": [3]}],
}
H6 = {"hole": {"at": [20, 15], "d": 6}}
H8 = {"hole": {"at": [80, 15], "d": 8}}


class FakeRun(E.Run):
    def __init__(self, answers, overall="ok", decisions=(), notes=(), intent=None, plans=None, stages=None):
        self.result = {"overall": overall, "decisions": list(decisions),
                       "stages": stages or [{"stage": "diff", "verdict": overall, "items": [], "notes": list(notes)}]}
        self._answers, self._intent, self._plans = answers, intent, plans or {}

    answers = property(lambda self: self._answers)
    new_analysis = property(lambda self: ANALYSIS)
    old_analysis = property(lambda self: ANALYSIS)
    intent = property(lambda self: self._intent)
    readback = property(lambda self: None)

    def plan(self, which):
        return self._plans.get(which)


def cats(rows, check):
    return [r["category"] for r in rows if r["check"] == check]


class Scoring(unittest.TestCase):
    def test_verdict_scoring(self):
        for want, got, cat in [("ok", "ok", "correct-automatic"), ("decide", "decide", "correct-ask"),
                               ("problems", "problems", "correct-ask"), ("problems", "decide", "silent-wrong"),
                               ("problems", "ok", "silent-wrong"), ("decide", "ok", "silent-wrong"),
                               ("decide", "problems", "unnecessary-ask"), ("ok", "decide", "unnecessary-ask"),
                               ("ok", "problems", "unnecessary-ask")]:
            rows = E.score({"verdict": want}, FakeRun({}, overall=got))
            self.assertEqual(cats(rows, "verdict"), [cat], (want, got))

    def test_wrong_print_excused_only_by_an_ask_about_it(self):
        exp = {"verdict": "ok", "drawing": {"prints": ["⌀7 H7 THRU"]}}
        plans = {"new": {"dimensions": [{"id": "d1", "label": "⌀6 H7 THRU"}]}, "old": {"dimensions": []}}

        def drawn(item):
            return FakeRun({}, plans=plans, decisions=[dict(item, stage="lint", needs="decide")])
        unrelated = drawn({"id": "x", "what": "readability_x: label overlap on ⌀9 H11 THRU"})
        self.assertEqual(cats(E.score(exp, unrelated), "drawing"), ["silent-wrong"])
        related = drawn({"id": "y", "what": "stale: the edit on ⌀7 H7 THRU no longer applies"})
        self.assertEqual(cats(E.score(exp, related), "drawing"), ["correct-ask"])

    def test_stated_tie_required(self):
        exp = {"verdict": "ok", "stated": ["frame_tie"]}
        silent = E.score(exp, FakeRun({}))
        self.assertEqual(cats(silent, "stated"), ["silent-wrong"])
        said = E.score(exp, FakeRun({}, notes=[{"kind": "frame_tie", "what": "tie broken by the file frame"}]))
        self.assertEqual(cats(said, "stated"), ["correct-automatic"])

    def test_locate(self):
        self.assertEqual(E.locate(ANALYSIS, H6), {2})
        self.assertEqual(E.locate(ANALYSIS, {"plane": {"normal": [0, 0, -1], "through": [0, 0, 0]}}), {1})
        self.assertEqual(E.locate(ANALYSIS, {"hole": {"at": [20, 15], "d": 8}}), set())

    def test_verdict_categories(self):
        def v(want, got):
            return cats(E.score({"verdict": want}, FakeRun({}, overall=got)), "verdict")[0]
        self.assertEqual(v("ok", "ok"), "correct-automatic")
        self.assertEqual(v("decide", "decide"), "correct-ask")
        self.assertEqual(v("ok", "decide"), "unnecessary-ask")
        self.assertEqual(v("decide", "ok"), "silent-wrong")
        self.assertEqual(v("ok", "problems"), "unnecessary-ask")

    def test_carried_right_wrong_lost_asked(self):
        exp = {"verdict": "ok", "carried": [{"question": "hole.function", "value": "fit:H7", "on": H6}]}
        right = E.score(exp, FakeRun({"hole.function:holes:2": "fit:H7"}))
        wrong = E.score(exp, FakeRun({"hole.function:holes:3": "fit:H7"}))
        lost = E.score(exp, FakeRun({}))
        asked = E.score(exp, FakeRun({}, overall="decide",
                                     decisions=[{"id": "hole.function:holes:2", "stage": "diff", "needs": "decide"}]))
        self.assertEqual(cats(right, "carried"), ["correct-automatic"])
        self.assertEqual(cats(wrong, "carried"), ["silent-wrong"])
        self.assertEqual(cats(lost, "carried"), ["silent-wrong"])
        self.assertEqual(cats(asked, "carried"), ["unnecessary-ask"])

    def test_datum_by_faces(self):
        exp = {"verdict": "ok", "carried": [{"question": "datum.A",
                                              "on": {"plane": {"normal": [0, 0, -1], "through": [0, 0, 0]}}}]}
        self.assertEqual(cats(E.score(exp, FakeRun({"datum.A": [1]})), "carried"), ["correct-automatic"])
        self.assertEqual(cats(E.score(exp, FakeRun({"datum.A": [0]})), "carried"), ["silent-wrong"])

    def test_ask_named_or_silent(self):
        exp = {"verdict": "decide", "ask": [{"question": "hole.function", "revision": "old", "on": H8}]}
        named = FakeRun({}, overall="decide",
                        decisions=[{"id": "hole.function:holes:3", "stage": "diff", "needs": "decide"}])
        other = FakeRun({}, overall="decide",
                        decisions=[{"id": "hole.function:holes:2", "stage": "diff", "needs": "decide"}])
        self.assertEqual(cats(E.score(exp, named), "ask"), ["correct-ask"])
        self.assertEqual(cats(E.score(exp, other), "ask"), ["silent-wrong"])

    def test_not_carried(self):
        exp = {"verdict": "decide", "not_carried": [{"question": "hole.position", "value": "0.5"}]}
        self.assertEqual(cats(E.score(exp, FakeRun({"hole.position:holes:2": "0.5"})), "not_carried"),
                         ["silent-wrong"])
        self.assertEqual(cats(E.score(exp, FakeRun({})), "not_carried"), ["correct-automatic"])

    def test_pmi_on_feature(self):
        intent = {"requirements": [{"kind": "size", "fit": "H7", "nominal": 6.0, "faces": [3]}], "datums": []}
        exp = {"verdict": "ok", "pmi": [{"kind": "size", "fit": "H7", "nominal": 6, "on": H6}]}
        self.assertEqual(cats(E.score(exp, FakeRun({}, intent=intent)), "pmi"), ["silent-wrong"])
        intent["requirements"][0]["faces"] = [2]
        self.assertEqual(cats(E.score(exp, FakeRun({}, intent=intent)), "pmi"), ["correct-automatic"])

    def test_drawing_stale_value_is_silent_when_the_chain_passed_it(self):
        plan = {"dimensions": [{"id": "d1", "label": "80", "state": {"kind": "shown"}}]}
        exp = {"verdict": "ok", "drawing": {"prints": ["75"], "absent": ["80"]}}
        stages = [{"stage": s, "verdict": "ok", "items": [], "notes": []} for s in ("diff", "draw", "lint")]
        rows = E.score(exp, FakeRun({}, plans={"new": plan, "old": plan}, stages=stages))
        self.assertEqual(cats(rows, "drawing"), ["silent-wrong", "silent-wrong"])
        # A lint problem about something else does not excuse the wrong values (review round 1, item 3).
        stages[2]["verdict"] = "problems"
        other = [{"stage": "lint", "needs": "problems", "id": "z", "what": "readability: label overlap on ⌀9"}]
        rows = E.score(exp, FakeRun({}, overall="problems", decisions=other, plans={"new": plan, "old": plan}, stages=stages))
        self.assertEqual(cats(rows, "drawing"), ["silent-wrong", "silent-wrong"])
        named = [{"stage": "lint", "needs": "problems", "id": "z", "what": "stale: the dimension 80 became 75"}]
        rows = E.score(exp, FakeRun({}, overall="problems", decisions=named, plans={"new": plan, "old": plan}, stages=stages))
        self.assertEqual(cats(rows, "drawing"), ["correct-ask", "correct-ask"])

    def test_tally(self):
        self.assertEqual(E.tally([{"category": "silent-wrong"}])["silent-wrong"], 1)


if __name__ == "__main__":
    unittest.main()
