"""Resize: the fitted Ø6 H7 hole at (20, 15) becomes Ø7."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plate import BASE_HOLES, plate, write  # noqa: E402

V1 = plate(BASE_HOLES)
V2 = plate([(20, 15, 7), (80, 15, 8), (30, 45, 5), (70, 45, 5)])

if __name__ == "__main__":
    write(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent, V1, V2)
