"""The PR comment, check and the resolution of decisions: structure, not text (no tool needed)."""
import json
import tempfile
import unittest
from pathlib import Path

from step_flow import github as G
from step_flow import pipeline as P
from step_flow import verdict as V

LINKS = {"before": "https://x/before.pdf", "after": "https://x/after.pdf", "changes": "https://x/c.svg"}


def result(overall, items=(), notes=()):
    diff = V.stage("diff", overall, items, notes, summary="1 hole moved.", migrated=["a", "b"])
    stages = [diff, V.stage("draw", V.OK)]
    return {"overall": overall, "stages": stages, "decisions": V.decisions(stages)}


ITEM = {"kind": "requirement_orphaned", "id": "hole.function:holes:7", "needs": "decide",
        "what": "hole.function:holes:7 not carried (orphaned)", "where": "diff/report.json"}


class Conclusion(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual([G.conclusion(v) for v in ("ok", "decide", "problems")], ["success", "neutral", "failure"])

    def test_parts_combine_to_the_worst(self):
        self.assertEqual(G.combine(["ok", "decide"]), "decide")
        self.assertEqual(G.combine(["decide", "problems"]), "problems")
        self.assertEqual(G.combine([]), "problems")


class Render(unittest.TestCase):
    def sections(self, md):
        return [l for l in md.splitlines() if l.startswith(("##", "**"))]

    def test_ok_has_no_decision_list_and_links_the_drawings(self):
        md, overall = G.render([("plate", result("ok"), LINKS, "")])
        self.assertEqual(overall, "ok")
        self.assertIn("**Needs a decision:** nothing.", md)
        for url in LINKS.values():
            self.assertIn(url, md)
        self.assertNotIn("To answer", md)
        self.assertTrue(md.startswith("## step-flow: ✅ `ok`"))

    def test_decide_lists_each_item_and_says_how_to_answer(self):
        md, overall = G.render([("plate", result("decide", [ITEM]), LINKS, "")])
        self.assertEqual(overall, "decide")
        self.assertEqual(sum(1 for l in md.splitlines() if l.startswith("- ") and ITEM["id"] in l), 1)
        self.assertIn("**Needs a decision:**", md)
        self.assertIn("To answer", md)

    def test_problems_overall_is_the_worst_part(self):
        bad = dict(ITEM, needs="problems", kind="tool_failure")
        md, overall = G.render([("a", result("ok"), LINKS, ""), ("b", result("problems", [bad]), LINKS, "")])
        self.assertEqual(overall, "problems")
        self.assertEqual(sum(1 for l in md.splitlines() if l.startswith("### ")), 2)

    def test_part_without_result_is_named_not_counted(self):
        md, overall = G.render([("a", result("ok"), LINKS, ""), ("new", None, None, "no baseline on main")])
        self.assertEqual(overall, "ok")
        self.assertIn("demo/new/part.step", md)
        self.assertIn("no baseline on main", md)

    def test_notes_are_listed_to_check(self):
        note = {"kind": "check", "what": "hole.position:holes:7 carried to a changed feature"}
        md, _ = G.render([("plate", result("ok", notes=[note]), LINKS, "")])
        self.assertIn("**To check**", md)
        self.assertIn(note["what"], md)

    def test_links_point_at_the_branch_commit_or_the_run(self):
        done = G.drawing_links("plate", "o/r", "B", "H", True, "https://run")
        self.assertIn("/blob/B/demo/plate/part.pdf", done["before"])
        self.assertIn("/blob/H/demo/plate/part.pdf", done["after"])
        fork = G.drawing_links("plate", "o/r", "B", "H", False, "https://run")
        self.assertEqual(fork["after"], "https://run")
        self.assertEqual(list(G.drawing_links("plate", "o/r", "B", "H", True, "https://run", has_after=False)),
                         ["before"])


class Main(unittest.TestCase):
    def test_writes_comment_and_check(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "plate").mkdir()
            (root / "plate" / "verdict.json").write_text(json.dumps(result("decide", [ITEM])))
            args = [t, "--repo", "o/r", "--base-sha", "B", "--head-sha", "H", "--run-url", "https://run",
                    "--committed"]
            self.assertEqual(G.main(args), 0)
            check = json.loads((root / "check.json").read_text())
            self.assertEqual(check["conclusion"], "neutral")
            self.assertIn("needs input", check["title"])
            self.assertIn(ITEM["id"], check["summary"])
            self.assertTrue((root / "comment.md").read_text().startswith(G.MARKER))


class Resolve(unittest.TestCase):
    def setup(self, root, carried, mine):
        (root / "diff").mkdir(parents=True)
        (root / "diff" / "answers.json").write_text(json.dumps(carried))
        p = root / "mine.json"
        p.write_text(json.dumps(mine))
        return p

    def stage(self, *items):
        return V.stage("diff", V.DECIDE, items, [], tool_verdict="decide")

    def test_person_answer_closes_the_item_and_replaces_the_carried_answer(self):
        ev = {"evidence": {"faces": "new"}, "unresolved": {"hole.function:holes:9": "ambiguous"}}
        item = {"kind": "carry_blocked", "id": "hole.function:holes:9", "needs": "decide", "what": "w", "where": "x"}
        other = {"kind": "requirement_orphaned", "id": "hole.position:holes:7", "needs": "decide", "what": "w",
                 "where": "x"}
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            mine = self.setup(root, {"a": 1, "_specify": ev},
                              {"a": 1, "hole.function:holes:9": "clearance", "_specify": {"evidence": {"faces": "new"}}})
            st = P.resolve(self.stage(item, other), root, mine)
            self.assertEqual([i["id"] for i in st["items"]], ["hole.position:holes:7"])
            self.assertEqual(st["verdict"], "decide")
            merged = json.loads((root / "diff" / "answers.json").read_text())
            self.assertEqual(merged["hole.function:holes:9"], "clearance")
            self.assertNotIn("hole.function:holes:9", merged["_specify"]["unresolved"])
            self.assertEqual([n["kind"] for n in st["notes"]], ["decided"])

    def test_answers_stamped_for_another_revision_are_ignored(self):
        item = {"kind": "carry_blocked", "id": "q", "needs": "decide", "what": "w", "where": "x"}
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            mine = self.setup(root, {"_specify": {"evidence": {"faces": "new"}}},
                              {"q": "v", "_specify": {"evidence": {"faces": "main"}}})
            st = P.resolve(self.stage(item), root, mine)
            self.assertEqual(len(st["items"]), 1)
            self.assertNotIn("q", json.loads((root / "diff" / "answers.json").read_text()))

    def test_accepting_an_orphan_closes_it_and_only_it(self):
        a = {"kind": "requirement_orphaned", "id": "a", "needs": "decide", "what": "w", "where": "x"}
        b = dict(a, id="b")
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            self.setup(root, {}, {})
            st = P.resolve(self.stage(a, b), root, None, ["a"])
            self.assertEqual([i["id"] for i in st["items"]], ["b"])
            st = P.resolve(self.stage(a), root, None, ["a"])
            self.assertEqual(st["verdict"], "ok")

    def test_absence_closes_nothing(self):
        a = {"kind": "requirement_orphaned", "id": "a", "needs": "decide", "what": "w", "where": "x"}
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            mine = self.setup(root, {"_specify": {"evidence": {"f": 1}}}, {"_specify": {"evidence": {"f": 1}}})
            st = P.resolve(self.stage(a), root, mine)
            self.assertEqual(st["verdict"], "decide")


if __name__ == "__main__":
    unittest.main()
