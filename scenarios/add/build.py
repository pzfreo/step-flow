"""Add: a new Ø10 hole at (50, 30); nothing else changes."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plate import BASE_HOLES, plate, write  # noqa: E402

V1 = plate(BASE_HOLES)
V2 = plate(BASE_HOLES + [(50, 30, 10)])

if __name__ == "__main__":
    write(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent, V1, V2)
