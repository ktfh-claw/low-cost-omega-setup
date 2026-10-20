"""Test fixtures: make the wrapper module importable from the tests dir."""

from __future__ import annotations

import sys
from pathlib import Path

WRAPPER_DIR = Path(__file__).resolve().parent.parent
if str(WRAPPER_DIR) not in sys.path:
    sys.path.insert(0, str(WRAPPER_DIR))
