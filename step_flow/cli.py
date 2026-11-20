"""``step-flow OLD.step NEW.step --answers OLD.answers.json [--spec PART.spec.json] -o OUT/``"""

import argparse
import json
import sys

from . import pipeline
from .verdict import exit_code


def main(argv=None):
    ap = argparse.ArgumentParser(prog="step-flow", description=__doc__)
    ap.add_argument("old", help="the STEP file as it was")
    ap.add_argument("new", help="the STEP file as it is now")
    ap.add_argument("--answers", required=True, help="the old revision's Specify answers (its sidecar)")
    ap.add_argument("--spec", help="the drawing's Spec (draftwright.spec JSON) for the old revision")
    ap.add_argument("-o", "--out", required=True, help="output directory")
    ap.add_argument("--allow-unpinned", action="store_true", help="run tools that differ from tools.lock")
    a = ap.parse_args(argv)
    try:
        result = pipeline.run(a.old, a.new, a.answers, a.out, spec=a.spec, allow_unpinned=a.allow_unpinned)
    except Exception as e:  # noqa: BLE001 - e.g. an unreadable input before the pipeline starts
        print(f"step-flow: error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"overall": result["overall"],
                      "stages": {s["stage"]: s["verdict"] for s in result["stages"]},
                      "decisions": len(result["decisions"])}, ensure_ascii=False))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
