import unittest

from step_flow import verdict as V
from step_flow.pipeline import finding_key, new_findings, parse_incomplete


class Combine(unittest.TestCase):
    def test_worst(self):
        self.assertEqual(V.worst(["ok", "decide", "ok"]), "decide")
        self.assertEqual(V.worst(["ok", "problems", "decide"]), "problems")
        self.assertEqual(V.worst(["ok"]), "ok")
        self.assertIsNone(V.worst([]))
        self.assertEqual(V.worst([None, "ok"]), "ok")

    def test_unknown_verdict_refused(self):
        with self.assertRaises(ValueError):
            V.worst(["ok", "fine"])
        with self.assertRaises(ValueError):
            V.stage("diff", "fine")

    def test_skipped_stages_do_not_count(self):
        stages = [V.stage("diff", "decide"), V.stage("write", "decide"), V.skipped("draw", "write stopped")]
        self.assertEqual(V.overall(stages), "decide")

    def test_nothing_ran_is_problems(self):
        self.assertEqual(V.overall([V.skipped("diff", "x")]), "problems")

    def test_item_verdict(self):
        self.assertEqual(V.item_verdict([]), "ok")
        self.assertEqual(V.item_verdict([{"needs": "decide"}, {"needs": "problems"}]), "problems")

    def test_exit_codes(self):
        ok = {"overall": "ok", "stages": [V.stage("diff", "ok")]}
        decide = {"overall": "decide", "stages": [V.stage("diff", "decide", [{"kind": "x", "needs": "decide"}])]}
        problems = {"overall": "problems", "stages": [V.stage("lint", "problems", [{"kind": "y", "needs": "problems"}])]}
        failed = {"overall": "problems",
                  "stages": [V.stage("diff", "problems", [{"kind": "tool_failure", "needs": "problems"}])]}
        self.assertEqual([V.exit_code(r) for r in (ok, decide, problems, failed)], [0, 0, 1, 2])

    def test_decisions_dedupe_within_a_stage_only(self):
        item = {"kind": "open_question", "id": "hole.function:holes:8", "needs": "decide"}
        stages = [V.stage("validate", "decide", [item, item]), V.stage("write", "decide", [dict(item, kind="w")])]
        self.assertEqual([d["stage"] for d in V.decisions(stages)], ["validate", "write"])


class WriteRefusals(unittest.TestCase):
    def test_unanswered_list(self):
        msg = "incomplete: 2 question(s) unanswered: hole.function:holes:8, hole.position:holes:8"
        self.assertEqual([i for i, _ in parse_incomplete(msg)], ["hole.function:holes:8", "hole.position:holes:8"])

    def test_blocked_carry(self):
        msg = "incomplete: datum.A (carried answer could not be applied: face 4 has no match in the new part)"
        self.assertEqual(parse_incomplete(msg), [("datum.A", "face 4 has no match in the new part")])

    def test_unknown_form(self):
        self.assertEqual(parse_incomplete("incomplete: something else"), [])


class Lint(unittest.TestCase):
    def f(self, code, msg, severity="warning", impact="incomplete"):
        return {"code": code, "message": msg, "severity": severity, "impact": impact}

    def test_renumbered_feature_is_not_new(self):
        old = {"lint": [self.f("feature_not_located", "f:hole:f7 on y: no chain")]}
        new = {"lint": [self.f("feature_not_located", "f:hole:f5 on y: no chain")]}
        self.assertEqual(new_findings(old, new), [])
        self.assertEqual(finding_key(new["lint"][0]), ("feature_not_located", "f:hole:f# on y: no chain"))

    def test_a_second_occurrence_is_new(self):
        old = {"problems": [self.f("x", "the ⌀8 hole")]}
        new = {"problems": [self.f("x", "the ⌀8 hole"), self.f("x", "the ⌀8 hole")]}
        self.assertEqual(len(new_findings(old, new)), 1)

    def test_info_and_advisory_ignored(self):
        new = {"problems": [self.f("a", "m", severity="info"), self.f("b", "m", impact="advisory")]}
        self.assertEqual(new_findings({}, new), [])


if __name__ == "__main__":
    unittest.main()
