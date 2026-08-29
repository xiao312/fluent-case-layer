"""Build or check the generated dictionary reference."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .render import check_outputs, write_outputs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fluent_case_layer.reference")
    parser.add_argument("mode", choices=("build", "check"))
    parser.add_argument("--root", default=".", help="repository root (default: current directory)")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.mode == "build":
        for path in write_outputs(root):
            print(path.relative_to(root.resolve()))
        return 0
    issues = check_outputs(root)
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1
    print("dictionary reference is current")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
