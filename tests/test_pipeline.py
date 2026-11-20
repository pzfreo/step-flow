"""Pipeline behaviour that needs no tool, plus one real run without a Spec (skipped unless the pinned tools are here)."""
import json
import tempfile
import unittest
from pathlib import Path

from step_flow import pipeline as P
from step_flow import verdict as V
from step_flow.tools import ToolError, check_versions

ROOT = Path(__file__).resolve().parent.parent
LOG = [{"cmd": ["specify-core", "analyse", "a.step"], "rc": 0, "stderr": ""},
       {"cmd": ["draftwright", "render", "b.step"], "rc": 3, "stderr": "boom"},
       {"cmd": ["draftwright", "diff", "b.step"], "rc": 0, "stderr": ""}]


class Runner:
    log = LOG


class ToolFailure(unittest.TestCase):
    def test_reports_the_command_that_failed(self):
        item = P._tool_failure(Runner(), "drawing failed")
        self.assertIn("draftwright render b.step", item["what"])
        self.assertIn("exit 3", item["what"])


class NotWritten(unittest.TestCase):
    def stage(self, lines):
        orig_w, orig_r = P.write_one, P.readback
        P.write_one = lambda r, step, answers, d, stem: ({"rc": 0, "stderr": ""}, {"not_written": lines})
        P.readback = lambda r, out, d: []
        try:
            with tempfile.TemporaryDirectory() as tmp:
                return P.stage_write(None, "o", "a", "n", Path(tmp))
        finally:
            P.write_one, P.readback = orig_w, orig_r

    def test_a_requirement_not_written_needs_a_decision(self):
        st = self.stage(["position 0.5 on holes:7: could not be written"])
        self.assertEqual(st["verdict"], V.DECIDE)
        self.assertEqual(st["items"][0]["kind"], "not_written")

    def test_retained_answer_is_only_a_note(self):
        st = self.stage(["shared planner dim: General contract conflicts; retained answered intent instead"])
        self.assertEqual(st["verdict"], V.OK)
        self.assertEqual(st["notes"][0]["kind"], "not_written")


class Crash(unittest.TestCase):
    def test_crash_writes_verdict_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            orig = P.stage_diff
            P.stage_diff = lambda *a, **k: (_ for _ in ()).throw(ValueError("bad json"))
            try:
                try:
                    check_versions()
                except ToolError:
                    self.skipTest("pinned tools not installed")
                result = P.run(ROOT / "scenarios/move/v1.step", ROOT / "scenarios/move/v2.step",
                               ROOT / "scenarios/move/v1.answers.json", tmp)
            finally:
                P.stage_diff = orig
            self.assertEqual(V.exit_code(result), 2)
            saved = json.loads((Path(tmp) / "verdict.json").read_text())
            self.assertIn("ValueError: bad json", saved["decisions"][0]["what"])


class NoSpec(unittest.TestCase):
    def test_runs_without_a_spec(self):
        try:
            check_versions()
        except ToolError:
            self.skipTest("pinned tools not installed")
        with tempfile.TemporaryDirectory() as tmp:
            s = ROOT / "scenarios/move"
            result = P.run(s / "v1.step", s / "v2.step", s / "v1.answers.json", tmp)
            self.assertEqual(result["overall"], "ok")
            self.assertIsNone(result["inputs"]["spec"])
            self.assertTrue((Path(tmp) / "draw/new.svg").exists())


class FirstBuild(unittest.TestCase):
    def setUp(self):
        try:
            check_versions()
        except ToolError:
            self.skipTest("pinned tools not installed")

    def test_no_answers_asks_for_every_requirement_and_still_draws(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = P.first_build(ROOT / "scenarios/move/v1.step", tmp)
            stages = {s["stage"]: s for s in result["stages"]}
            self.assertEqual(result["overall"], "decide")
            self.assertTrue(stages["diff"]["skipped"])
            self.assertTrue(any(i["kind"] == "open_question" for i in stages["validate"]["items"]))
            self.assertIn("new_drawing_pdf", result["outputs"])
            self.assertNotIn("new_pmi_step", result["outputs"])  # nothing answered, nothing written

    def test_complete_answers_write_the_pmi(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = ROOT / "scenarios/move"
            result = P.first_build(s / "v1.step", tmp, answers=s / "v1.answers.json", spec=s / "part.spec.json")
            self.assertEqual(result["overall"], "ok")
            self.assertIn("new_pmi_step", result["outputs"])


class PersonSpec(unittest.TestCase):
    def test_spec_edited_on_the_branch_is_the_one_drawn(self):
        try:
            check_versions()
        except ToolError:
            self.skipTest("pinned tools not installed")
        with tempfile.TemporaryDirectory() as tmp:
            s = ROOT / "scenarios/move"
            mine = Path(tmp) / "mine.json"
            spec = json.loads((s / "part.spec.json").read_text())
            spec["sheet"]["title"]["title"] = "EDITED TITLE"
            mine.write_text(json.dumps(spec))
            result = P.run(s / "v1.step", s / "v2.step", s / "v1.answers.json", Path(tmp) / "o",
                           spec=s / "part.spec.json", new_spec=mine)
            self.assertEqual(result["overall"], "ok")
            self.assertIn("EDITED TITLE", (Path(tmp) / "o/draw/new.svg").read_text())
            self.assertEqual(json.loads((Path(tmp) / "o/draw/new.spec.json").read_text()), spec)
            self.assertNotIn("EDITED TITLE", (Path(tmp) / "o/draw/old.svg").read_text())


if __name__ == "__main__":
    unittest.main()
