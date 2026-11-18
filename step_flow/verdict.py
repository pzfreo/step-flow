"""Stage results and how they combine into the chain's verdict.

A stage result is ``{"stage", "verdict", "items", "notes", ...}``:

- ``ok``: the stage did its job and found nothing that needs a person or an AI;
- ``decide``: named items need a decision (each item says what and where to look);
- ``problems``: the stage failed, a tool failed, or it found new problems.

A stage that could not run because an earlier one stopped (a write that stopped on open items leaves
nothing to draw) is ``skipped``: its verdict is ``None`` and it does not count towards the overall verdict,
which is the worst of the stages that ran. A chain in which nothing ran is ``problems``.
"""

OK, DECIDE, PROBLEMS = "ok", "decide", "problems"
RANK = {OK: 0, DECIDE: 1, PROBLEMS: 2}


def worst(verdicts):
    """The worst of the given verdicts, ignoring ``None`` (skipped); ``None`` if none are given."""
    present = [v for v in verdicts if v is not None]
    for v in present:
        if v not in RANK:
            raise ValueError(f"unknown verdict {v!r}")
    if not present:
        return None
    return max(present, key=RANK.__getitem__)


def item_verdict(items):
    """The verdict a list of items implies on its own: the worst of their ``needs``."""
    return worst([i.get("needs") for i in items]) or OK


def stage(name, verdict, items=(), notes=(), **extra):
    """A stage result. ``verdict`` may be ``None`` only when the stage was skipped."""
    if verdict is not None and verdict not in RANK:
        raise ValueError(f"unknown verdict {verdict!r}")
    result = {"stage": name, "verdict": verdict, "items": list(items), "notes": list(notes)}
    result.update(extra)
    return result


def skipped(name, reason):
    return stage(name, None, skipped=True, reason=reason)


def overall(stages):
    """The chain's verdict: the worst verdict of the stages that ran (``problems`` if none ran)."""
    return worst([s["verdict"] for s in stages]) or PROBLEMS


def decisions(stages):
    """Every item that needs a decision or names a problem, in stage order, one per (stage, id)."""
    seen, out = set(), []
    for s in stages:
        for i in s["items"]:
            key = (s["stage"], i.get("id"), i.get("kind"))
            if key in seen:
                continue
            seen.add(key)
            out.append(dict(i, stage=s["stage"]))
    return out


def exit_code(result):
    """0 for ok and decide (told apart in verdict.json), 1 for problems, 2 for a tool failure."""
    if any(i.get("kind") == "tool_failure" for s in result["stages"] for i in s["items"]):
        return 2
    return 1 if result["overall"] == PROBLEMS else 0
