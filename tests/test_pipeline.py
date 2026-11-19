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


if __name__ == "__main__":
    unittest.main()
