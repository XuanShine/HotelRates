"""Shim: same entry as `python -m hotelrates.scheduler`."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from hotelrates.scheduler import main

if __name__ == "__main__":
    main()
