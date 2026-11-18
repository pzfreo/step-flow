# Findings about Specify and Draftwright

What the M1 scenarios showed the released tools do (specify-core 0.1.18, draftwright 0.6.0). None is worked
around in step-flow, and no expectation was changed to match. Each reproduction runs from the repository
root with the pinned venv (`S=.venv/bin/specify-core D=.venv/bin/draftwright`); `out/` is ignored.

## F1. Symmetric part: Specify breaks the tie by the file frame and says `ok` (harness: silent-wrong)

**Scenario** `scenarios/symmetric`: a 100 × 60 × 10 plate, symmetric about its centre, with Ø6 holes at
(30, 30) and (70, 30). Datum B and Ø6 H7 are on the hole at (30, 30); the other is a clearance hole. In v2
the hole at (70, 30) moves to (75, 30).

```sh
$S diff scenarios/symmetric/v1.step scenarios/symmetric/v2.step \
   --answers scenarios/symmetric/v1.answers.json -o out/f1
```

**Observed:** verdict `ok`, nothing unresolved or ambiguous; `answers.json` keeps `datum.B: [6]` and
`hole.function:holes:6: fit:H7` on the hole at (30, 30); the hole at (75, 30) is "moved X +5" and its
requirements are listed to check.

**Expected (the brief, and docs/diff.md "ambiguous: ... such as a symmetric repeat"):** `decide`, naming
datum B and the H7 hole. Turned 180° about the plate's centre, v1 fits v2 exactly as well (every plate face,
and one of the two holes, coincide either way), and in that reading the datum hole is the one that moved.
Specify takes the identity motion without saying a choice was made.

**Caveat, for Paul:** this expectation may rest on an assumption. The file frame is real evidence (CAD
exports rarely turn a part), so taking the identity when it fits is defensible; but then it is a rule, and
the report should say the tie was broken by the file frame. Either the rule is stated (and the
scenario's truth changes to `ok` with a note) or Specify reports the tie as ambiguous. The harness keeps the
brief's truth until that is decided, so it fails on this scenario.

## F2. Specify's PMI change list mis-pairs items after a removal and reuses characteristic numbers

**Scenario** `scenarios/remove` (the Ø8 hole at (80, 15) removed; the Ø5 pair's faces 8, 9 become 7, 8).

```sh
$S diff scenarios/remove/v1.step scenarios/remove/v2.step \
   --answers scenarios/remove/v1.answers.json -o out/f2
grep '^- #' out/f2/report.md
```

**Observed** (`report.md` PMI section, `report.json` `pmi.items`):

```text
- #6 80 → 30 (Ø5 × 10 through hole)
- #6 30: characteristic number #16 → #6 (Ø5 × 10 through hole)
- #6 retired: 30 (Ø5 × 10 through hole)
- #15 60: characteristic number #18 → #15 (face 3)
- #15 retired: ⌀8 H11 (Ø8 × 10 through hole)
```

The removed hole's basic location 80 (id `planner:answered:dim:plane:0/to/hole:7/0`) is paired by id with
the Ø5 hole's 30, which took face 7: the report says a Ø5 hole's location changed 80 → 30. One number
appears as changed, renumbered and retired; #15 and #17 are both retired and given to another item.

**Expected:** "#… retired: 80 (Ø8 hole)" and no change on the Ø5 holes; docs/diff.md says a same-id match
"must not contradict known face correspondence" and "numbers are never reused". **Impact:** report only;
the carried `answers.json` and the written PMI are right (the harness checks both).

## F3. `draftwright diff` pairs drawing items by face-numbered IDs: false changes and a false `problems`

**Scenario** `scenarios/reexport` (identical geometry, faces in a different order).

```sh
mkdir -p out/f3
for v in v1 v2; do $S analyse scenarios/reexport/$v.step -o out/f3/$v.analysis.json; done
$S write scenarios/reexport/v1.step out/f3/v1.analysis.json scenarios/reexport/v1.answers.json -o out/f3/v1.pmi.step
$S diff scenarios/reexport/v1.step scenarios/reexport/v2.step --answers scenarios/reexport/v1.answers.json -o out/f3/sdiff
$S write scenarios/reexport/v2.step out/f3/v2.analysis.json out/f3/sdiff/answers.json -o out/f3/v2.pmi.step
$D diff out/f3/v1.pmi.step out/f3/v2.pmi.step --spec scenarios/reexport/part.spec.json -o out/f3/dw
```

**Observed** (`out/f3/dw/report.json`): verdict `problems`, "The new drawing has 1 problem the old one did
not." The added problem (`gdt_position_changed` for ⌖ ⌀0.2Ⓜ) is also listed as resolved, word for word.
`annotations` lists 12 changes for identical geometry, including `20 → 30` and `80 → 70` on
`d:pmi:dimension.linear.basic:f0,6` / `f0,7`. In `scenarios/remove` it likewise reports `80 → 30` and
`30 → 70`. Both drawings print exactly the same values (the harness's `same_as_old` check passes).

**Expected:** verdict `ok`, no annotation changes. Its feature comparison (`features: []`) and Spec carry
(`renamed` f8 → f6, to the right callout) are right; the annotation and problem comparison should go through
the same correspondence. step-flow records draftwright's verdict as a note and uses its own lint (below).

## F4. Holes sharing a coordinate: Draftwright's plan says one dimension serves both, its lint says not located

**Any base-plate scenario's old drawing** (holes at (20, 15) and (80, 15); (30, 45) and (70, 45)):

```sh
$S analyse scenarios/move/v1.step -o out/f4.analysis.json
$S write scenarios/move/v1.step out/f4.analysis.json scenarios/move/v1.answers.json -o out/f4.pmi.step
$D plan out/f4.pmi.step | python3 -c "import json,sys; p=json.load(sys.stdin); \
  [print(x['code'], x['message']) for x in p['problems'] if x['code']=='feature_not_located']"
```

**Observed:** Specify writes one basic y location per shared y (15 to the Ø6 hole, 45 to one Ø5 hole);
Draftwright's plan draws them with the basis "one dimension serves every feature at this distance", and the
same plan reports `feature_not_located` (fix_before_printing) for the ⌀8 and the other ⌀5 hole on y.
**Expected:** one or the other: either the shared dimension locates both (no problem) or it does not (and
the plan should not say it serves both). Present before any change, so it never reaches step-flow's
verdict; it makes every base-plate drawing `needs_attention`.
