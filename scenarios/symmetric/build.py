"""Symmetric: a plate symmetric about its centre with two Ø6 holes at (30, 30) and (70, 30); the one at
(30, 30) is datum B. Specify takes the two equal holes as one pair, so both are Ø6 H7. In v2 the other hole moves to (75, 30), so v1 maps onto v2 either as it lies
(the datum hole stays at (30, 30)) or turned 180° about the plate's centre (the datum hole is the one that moved)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plate import BASE_HOLES, plate, write  # noqa: E402

V1 = plate([(30, 30, 6), (70, 30, 6)])
V2 = plate([(30, 30, 6), (75, 30, 6)])

if __name__ == "__main__":
    write(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent, V1, V2)
