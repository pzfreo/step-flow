"""Remove: the Ø8 clearance hole at (80, 15) is removed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from plate import BASE_HOLES, plate, write  # noqa: E402

V1 = plate(BASE_HOLES)
V2 = plate([(20, 15, 6), (30, 45, 5), (70, 45, 5)])

if __name__ == "__main__":
    write(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent, V1, V2)
