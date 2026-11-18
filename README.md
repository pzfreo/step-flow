# step-flow

A geometry change, carried through as a build: STEP → PMI → drawing.

When a part's STEP file changes in a pull request, step-flow:

1. compares it with the previous revision and carries the part's requirements (GD&T, fits, threads, finish,
   datums) to the new geometry with [Specify](https://github.com/pzfreo/specify-core), naming anything it can't
   place;
2. writes them into the new STEP as AP242 PMI;
3. redraws the part with [Draftwright](https://github.com/pzfreo/draftwright), keeping the drawing's Spec;
4. checks every stage, and gives one verdict: **ok** (carried and redrawn, nothing new to decide), **decide**
   (named items need a person or an AI), or **problems**.

Nothing is carried silently wrong: that is what the scenarios here test.

Status: under construction. The design is in
[draftwright-project's change-flow proposal](https://github.com/pzfreo/draftwright-project) (private) and
decision P8.

## Licence

Apache-2.0.
