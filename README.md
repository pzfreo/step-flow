# step-flow

A geometry change, carried through as a build: STEP → PMI → drawing.

When a part's STEP file changes, step-flow:

1. compares it with the previous revision and carries the part's requirements (GD&T, fits, threads, finish,
   datums) to the new geometry with [Specify](https://github.com/pzfreo/specify-core), naming anything it can't
   place;
2. writes them into the new STEP as AP242 PMI, never taking defaults;
3. redraws the part with [Draftwright](https://github.com/pzfreo/draftwright), keeping the drawing's Spec;
4. checks every stage, and gives one verdict: **ok**, **decide** or **problems**.

Nothing is carried silently wrong: that is what the scenarios here test. Status: milestone 1 (pipeline,
six scenarios, local harness). No GitHub workflow yet. What the scenarios found about the tools is in
[FINDINGS.md](FINDINGS.md).

## Install

The tools are pinned to released versions in [tools.lock](tools.lock) (and `pyproject.toml`); step-flow
refuses to run other versions unless given `--allow-unpinned`. It uses the `specify-core` and `draftwright`
installed beside its own Python first, then PATH.

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e '.[scenarios]'   # build123d only for regenerating scenarios
```

## The pipeline

```sh
.venv/bin/step-flow OLD.step NEW.step --answers OLD.answers.json [--spec PART.spec.json] -o OUT/
```

`OLD.answers.json` is the old revision's Specify answers (its committed sidecar); `--spec` is the drawing's
Spec (`draftwright.spec/3`). Stages, each with a result `{stage, verdict, items, notes}`:

| Stage | What runs | ok | decide | problems |
|---|---|---|---|---|
| diff | `specify-core diff OLD NEW --answers` | every requirement carried, nothing new | an unresolved requirement (orphaned, ambiguous, unmatched, stale, unresolved), a new requirement to specify, a carry block | Specify's review found new problems; the diff failed (e.g. the answers belong to another revision) |
| validate | `specify-core analyse NEW`; `questions --answers <carried> --open` | no question open | each open question | the new part refuses the carried answers |
| write | `specify-core write` for OLD (its answers) and NEW (carried), **without `--accept-defaults`** | both written | the new write stopped on open items (each named) | a write failed otherwise, or the old answers do not write |
| draw | `draftwright plan/review/render` of the old and new PMI'd STEP; `draftwright diff` carries the Spec | drawn, every Spec entry carried | a Spec entry orphaned or ambiguous, or a new stale-edit problem (`dimension_edit_unapplied`, `annotation_edit_unapplied`, `id_not_migrated`) | a draftwright command failed |
| lint | compares the new drawing's review findings with the old one's | no new finding | a new finding of impact `decision` | a new finding of any other impact (`incomplete`, `readability`) |

Rules, decided for M1:

- **Overall** = the worst verdict of the stages that ran (ok < decide < problems). A stage that cannot run
  because an earlier one stopped (no PMI'd STEP to draw) is `skipped` and does not count.
- A stage's verdict is the worse of the tool's own verdict and what its items imply; when they differ the
  stage has a `verdict_disagrees` note.
- **Requirements to check** (carried to a feature that changed size or place) are notes, not decisions:
  Specify's verdict stays `ok` for them, and the summary lists them under "To check".
- **Lint** ignores `info` and `advisory` findings, and compares by (code, message) with Draftwright feature
  IDs' face numbers blanked (`f:hole:f7` → `f:hole:f#`), since faces renumber on any change; a finding that
  occurs more often than before is new. `draftwright diff`'s own verdict is recorded as a note, not used
  (it pairs items by face-numbered IDs: FINDINGS.md F3, draftwright #539; and a shared dimension that plan says serves two holes while lint says one is not located: F4, draftwright #540). Specify's `frame_tie` is a note and appears in `summary.md`.
- A `not_written` line from the write is a `decide` item (a requirement was not written), except the planner's
  "retained answered intent" lines (a shared planner dimension given up for an answered requirement), which are
  notes.
- Specify reads its own written PMI back: `specify-core analyse` on the written STEP (`resume.answers`) must
  equal the carried answers, and a difference or a `resume.conflicts` entry is `problems`. This is Specify
  checking Specify, not an independent reader; the independent reader is Draftwright, whose drawing checks
  (what the plan prints, the Spec carry, lint) read the PMI from the file. The harness checks carried
  requirements on the read-back and PMI values on Specify's intent and the drawing's plan.

Outputs in `OUT/`: `verdict.json` (`overall`, `stages`, `decisions`: every item needing a decision or naming
a problem, with `where` to look, `outputs`, `tools`), `summary.md` (for a PR comment), `commands.json` (every
command, exit code and stderr), `diff/` (Specify's report and carried `answers.json`), `validate/`,
`write/` (PMI'd STEPs, intents, write reports), `draw/` (`old.svg/pdf`, `new.svg/pdf`, plans, reviews,
`diff/` with the carried `spec.json` and `changes.svg`).

**Exit code:** 0 for `ok` and for `decide` (told apart by `overall` in `verdict.json` and the printed
line), 1 for `problems`, 2 for a tool failure (missing or unpinned tool, a failed tool command, or an
unexpected crash: the crash is also written to `verdict.json` as a `tool_failure` item). The harness exits 2 for
a crash or unpinned tool too.

## The harness

```sh
.venv/bin/step-flow-harness run [--scenario NAME] -o out/harness   # scorecard.md, scorecard.json
.venv/bin/step-flow-harness build [--check] [--scenario NAME]      # regenerate / verify the STEP files
.venv/bin/step-flow-harness answers [--scenario NAME]              # regenerate v1.answers.json
.venv/bin/python -m unittest discover -s tests -t .                # unit tests
```

Chain verdict scoring (ok < decide < problems): equal is correct; a worse verdict than the truth is an
unnecessary-ask; a better one is silent-wrong (including `problems` reported as only `decide`). A drawing check
that fails is correct-ask only when a draw or lint item names that very value, never for unrelated asks.

`run` runs the pipeline on each scenario and scores every expectation as **correct-automatic**,
**correct-ask**, **unnecessary-ask**, **silent-wrong** or **error** (the check could not be made). It exits 1
if anything is silent-wrong, 2 on an error. Checks are structural: which requirement is on which feature
(features found by geometry in Specify's analysis, never by face number), which values the new drawing's
own plan prints, which items the chain names. Nothing compares bytes or hashes.

## Scenarios

`scenarios/<name>/`:

| File | What it is |
|---|---|
| `build.py` | builds v1 and v2 with build123d from parameters (`scenarios/plate.py`); `python build.py DIR` |
| `v1.step`, `v2.step` | the generated parts, committed (about 30 KB each). STEP headers carry a timestamp, so `build --check` regenerates them and compares Specify's analysis of every face, not bytes |
| `v1.chosen.json` | the v1 requirements, answered by hand for every question Specify asks of v1 (face numbers are v1's) |
| `v1.answers.json` | generated by `answers`: refuses unless `questions --open` is empty for the chosen answers, then exports them with `questions --resolve-defaults --step` only to stamp Specify's evidence, and refuses if the export added or changed any answer. No default is ever taken |
| `part.spec.json` | the drawing's Spec: title block, and one judgement (a hole callout placed above the plan view) |
| `expect.toml` | the truth (below) |

`expect.toml`:

```toml
changed = "what changed, in words"
verdict = "ok"                      # the chain's expected verdict

[[carried]]                         # must be in the carried answers, on this feature of the new part
question = "hole.function"          # the answer ID's question (before the first ':')
value = "fit:H7"                    # optional
on.hole = { at = [20, 15], d = 6 }  # or on.holes = [...], or on.plane = { normal, through }; none = part-wide

[[not_carried]]                     # must not be carried anywhere
question = "hole.position"
value = "0.5"

[[ask]]                             # must be named for a decision
question = "hole.function"
revision = "old"                    # whose numbering the item uses: old (orphaned, ambiguous) or new
on.hole = { at = [80, 15], d = 8 }

[[noted]]                           # must be listed to check
question = "hole.function"
on.hole = { at = [20, 15], d = 7 }

[[pmi]]                             # must be in the PMI written to the new STEP (Specify's intent)
kind = "size"                       # any other keys must equal the intent row's (fit, nominal, tolerance...)
fit = "H7"
on.hole = { at = [20, 15], d = 7 }

[drawing]                           # read from `draftwright plan` of the new PMI'd STEP
prints = ["⌀7 H7 THRU"]             # dimension labels, GD&T frames ("⌖ | ⌀0.05 | A | B | C"), requirements, notes
absent = ["⌀6 H7 THRU"]
spec_edits = ["2× ⌀5 H11 THRU"]     # the Spec's dimension edit is on the item printing this
same_as_old = true                  # prints exactly what the old drawing printed
```

The six M1 scenarios: `reexport` (same geometry, faces reordered: ok), `move` (the Ø8 hole moves: ok),
`resize` (the Ø6 H7 hole becomes Ø7: ok, H7 carried with Ø7's limits and listed to check, per Specify's
rule), `add` (a new Ø10 hole: decide), `remove` (the Ø8 hole removed: decide, orphaned requirements named),
`symmetric` (one of a symmetric pair moves: ok, and the report must state that the file frame broke the tie; FINDINGS.md F1).

## Licence

Apache-2.0.
