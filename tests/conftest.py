"""Tests need the project root on sys.path to import lib/ and collectors/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
