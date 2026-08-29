#!/usr/bin/env python3
"""Repository-checkout wrapper for ``fluent-case campaign --mode apply``."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fluent_case_layer.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["campaign", *sys.argv[1:], "--mode", "apply"]))
