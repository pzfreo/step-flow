"""The PR comment, check and the resolution of decisions: structure, not text (no tool needed)."""
import json
import sys
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
        self.assertIn("**Needs a decision** (1):", md)
        self.assertIn("To answer", md)

    def test_problems_overall_is_the_worst_part(self):
        bad = dict(ITEM, needs="problems", kind="tool_failure")
        md, overall = G.render([("a", result("ok"), LINKS, ""), ("b", result("problems", [bad]), LINKS, "")])
        self.assertEqual(overall, "problems")
        self.assertEqual(sum(1 for l in md.splitlines() if l.startswith("### ")), 2)

    def test_part_without_a_verdict_is_problems(self):
        # step-flow left no verdict.json (it crashed, was killed, or the part has no STEP): that must never be
        # a green check. The earlier expectation (ok) was wrong, and combine()'s docstring says so; changed
        # because the fix requires it.
        md, overall = G.render([("a", result("ok"), LINKS, ""), ("new", None, None, "step-flow did not finish")])
        self.assertEqual(overall, "problems")
        self.assertIn("demo/new/part.step", md)
        self.assertIn("step-flow did not finish", md)
        self.assertEqual(G.render([("only", None, None, "x")])[1], "problems")

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


FEATURE = {"class": "orphaned", "what": "Ø8 × 10 through hole", "at": [80.0, 15.0, 10.0]}
MOVED = {"class": "adapted", "what": "Ø8 hole", "at": [80, 15, 10],
         "changes": {"position": {"old": [80.0, 15.0], "new": [75.0, 15.0]}}}


class State(unittest.TestCase):
    def test_what_changed_is_built_from_features_not_from_specifys_sentence(self):
        r = result("decide", [ITEM])
        r["stages"][0]["features"] = [FEATURE, MOVED]
        r["stages"][0]["summary"] = "1 hole removed. A decision is needed: 2 requirements could not be applied."
        lines = G.what_changed(r)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("removed:"))
        self.assertIn("→", lines[1])
        md, _ = G.render([("plate", r, LINKS, "")])
        before, _, details = md.partition("<details>")
        self.assertNotIn("A decision is needed", before)       # only in the folded, verbatim report
        self.assertIn("A decision is needed", details)

    def test_decided_items_leave_the_decision_list(self):
        r = result("ok", notes=[{"kind": "decided", "what": "x -- accepted in accepted.json"}])
        md, overall = G.render([("plate", r, LINKS, "")])
        self.assertEqual(overall, "ok")
        self.assertIn("**Needs a decision:** nothing.", md)
        self.assertIn("1 decided by you", md)

    def test_spec_edited_on_the_branch_is_stated(self):
        r = result("ok", notes=[{"kind": "spec_decided", "what": "w"}])
        md, _ = G.render([("plate", r, LINKS, "")])
        self.assertIn("**Spec:**", md)

    def test_first_build_has_no_before_drawing_and_says_nothing_is_carried(self):
        r = result("decide", [ITEM, dict(ITEM, stage="write")])
        r["mode"] = "first_build"
        links = G.drawing_links("new", "o/r", "B", "H", True, "https://run", has_before=False, has_changes=False)
        self.assertEqual(sorted(links), ["after"])
        md, overall = G.render([("new", r, links, "")])
        self.assertEqual(overall, "decide")
        self.assertIn("first build", md)
        self.assertNotIn("[before]", md)
        self.assertEqual(sum(1 for l in md.splitlines() if ITEM["id"] in l), 1)  # one line per id

    def test_a_long_list_folds(self):
        items = [dict(ITEM, id=f"q{n}") for n in range(15)]
        md, _ = G.render([("new", result("decide", items), LINKS, "")])
        self.assertIn("**Needs a decision** (15):", md)
        self.assertIn("<summary>5 more</summary>", md)


class Parts(unittest.TestCase):
    def test_any_change_in_a_part_dir_selects_it_except_generated_files(self):
        paths = ["demo/plate/part.answers.json", "demo/plate/part.pdf", "demo/b c/part.spec.json",
                 "demo/d/part.pmi.step", "demo/d/part.changes.svg", "demo/e/part.step", "README.md",
                 "demo/stray.txt", "demo/e/nested/part.step"]
        self.assertEqual(G.changed_parts(paths), ["demo/b c", "demo/e", "demo/plate"])

    def test_names_survive_a_nul_separated_round_trip(self):
        import io
        import contextlib
        stdin = io.TextIOWrapper(io.BytesIO("demo/a b/part.step\0demo/a b/part.pdf\0".encode()))
        out = io.StringIO()
        old = sys.stdin
        sys.stdin = stdin
        try:
            with contextlib.redirect_stdout(out):
                G.main(["parts"])
        finally:
            sys.stdin = old
        self.assertEqual(out.getvalue(), "demo/a b\0")

    def test_the_check_has_its_own_name(self):
        self.assertNotEqual(G.CHECK_NAME, "step-flow")

    def test_nothing_to_check_is_ok(self):
        with tempfile.TemporaryDirectory() as t:
            G.main([t, "--repo", "o/r", "--base-sha", "B", "--head-sha", "H", "--run-url", "u"])
            self.assertEqual(json.loads((Path(t) / "check.json").read_text())["conclusion"], "success")


class Fork(unittest.TestCase):
    """A PR from a fork gets a read-only token: checked only, nothing is committed, posted or set."""

    def test_fork_is_check_only(self):
        for overall in ("ok", "decide"):
            self.assertEqual(G.actions(False, overall),
                             {"commit_back": False, "comment": False, "check": False, "fail_job": False})
        self.assertTrue(G.actions(False, "problems")["fail_job"])

    def test_same_repo_commits_comments_and_checks_and_never_fails_the_job(self):
        for overall in ("ok", "decide", "problems"):
            self.assertEqual(G.actions(True, overall),
                             {"commit_back": True, "comment": True, "check": True, "fail_job": False})

    def test_main_writes_the_actions_for_a_fork(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "plate").mkdir()
            (Path(t) / "plate" / "verdict.json").write_text(json.dumps(result("problems", [dict(ITEM, needs="problems")])))
            G.main([t, "--repo", "o/r", "--base-sha", "B", "--head-sha", "H", "--run-url", "https://run", "--fork"])
            check = json.loads((Path(t) / "check.json").read_text())
            self.assertEqual(check["actions"], G.actions(False, "problems"))
            self.assertNotIn("blob/H", check["summary"])   # nothing was committed: links go to the run


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

    def test_answers_stamped_for_an_earlier_step_are_listed_not_applied(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            mine = self.setup(root, {"a": 1, "_specify": {"evidence": {"faces": "new"}}},
                              {"a": 1, "q1": "x", "q2": "y", "_specify": {"evidence": {"faces": "old"}}})
            st = P.resolve(self.stage(), root, mine)
            note = [n for n in st["notes"] if n["kind"] == "answers_stale"][0]
            self.assertEqual(note["ids"], ["q1", "q2"])
            self.assertIn("2 answers", note["what"])
            self.assertNotIn("q1", json.loads((root / "diff" / "answers.json").read_text()))
            r = result("decide", [ITEM], [note])
            md, _ = G.render([("plate", r, LINKS, "")])
            self.assertIn("**Answers not applied:**", md)

    def test_absence_closes_nothing(self):
        a = {"kind": "requirement_orphaned", "id": "a", "needs": "decide", "what": "w", "where": "x"}
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            mine = self.setup(root, {"_specify": {"evidence": {"f": 1}}}, {"_specify": {"evidence": {"f": 1}}})
            st = P.resolve(self.stage(a), root, mine)
            self.assertEqual(st["verdict"], "decide")


if __name__ == "__main__":
    unittest.main()
