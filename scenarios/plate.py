"""The scenario parts: a plate with through holes, built with build123d from parameters.

Every scenario's build.py calls ``plate`` for v1 and v2, so the change between them is exactly the
parameters that differ. ``builder="sketch"`` builds the same solid from a sketch and an extrusion, which
gives the same geometry with its faces in a different order (the re-export scenario).
"""

from build123d import Align, Box, BuildPart, BuildSketch, Circle, Cylinder, Locations, Mode, Pos, Rectangle, \
    export_step, extrude

# The base plate: 100 x 60 x 10, corner at the origin, bottom face on z = 0.
BASE = dict(length=100, width=60, thickness=10)
# (x, y, diameter) of each through hole.
BASE_HOLES = [
    (20, 15, 6),   # the fitted hole: Ø6 H7, position 0.05
    (80, 15, 8),   # the clearance hole: Ø8 (H11), position 0.5 at MMC
    (30, 45, 5),   # the pair: 2× Ø5 clearance, position 0.2 at MMC
    (70, 45, 5),
]


def plate(holes, length=100, width=60, thickness=10, builder="box"):
    if builder == "box":
        part = Box(length, width, thickness, align=(Align.MIN, Align.MIN, Align.MIN))
        for x, y, d in holes:
            part -= Pos(x, y, thickness / 2) * Cylinder(d / 2, thickness)
        return part
    if builder == "sketch":
        with BuildPart() as bp:
            with BuildSketch():
                Rectangle(length, width, align=(Align.MIN, Align.MIN))
                for x, y, d in reversed(holes):
                    with Locations((x, y)):
                        Circle(d / 2, mode=Mode.SUBTRACT)
            extrude(amount=thickness)
        return bp.part
    raise ValueError(builder)


def write(out_dir, v1, v2):
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    export_step(v1, str(out / "v1.step"))
    export_step(v2, str(out / "v2.step"))
