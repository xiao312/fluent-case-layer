#!/usr/bin/env python3
"""Run the G2 diffusion-FGM setup/readback probe in an existing allocation.

This program neither submits a scheduler job nor calculates a flamelet/PDF table.
It exits after serializing the active Fluent settings groups.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import traceback
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fluent_case_layer.driver.flamelet import (
    assess_flamelet_table_readiness,
    run_diffusion_fgm_setup_probe,
)
from fluent_case_layer.driver.util import atomic_write_json
from fluent_case_layer.schema import load_case


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "case",
        help="Canonical split case directory.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination for the complete setup/readback JSON evidence.",
    )
    parser.add_argument(
        "--execution-provenance",
        type=Path,
        required=True,
        help="Preflighted scheduler, revision, runtime, and staged-asset provenance JSON.",
    )
    parser.add_argument("--processors", type=int, default=1)
    parser.add_argument(
        "--confirm-setup-readback-only",
        action="store_true",
        help="Acknowledge that this run must stop before all calculations and iterations.",
    )
    return parser.parse_args()


def _load_execution_provenance(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read execution provenance {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise SystemExit("execution provenance must contain one JSON object")
    return value


def main() -> int:
    args = parse_args()
    if not args.confirm_setup_readback_only:
        raise SystemExit("refusing launch without --confirm-setup-readback-only")
    if args.processors < 1:
        raise SystemExit("--processors must be positive")

    case = load_case(args.case)
    execution = _load_execution_provenance(args.execution_provenance.resolve())
    readiness = assess_flamelet_table_readiness(case)
    if readiness.ready or readiness.mode != "setup_readback_only":
        raise SystemExit(
            f"refusing a case outside the blocked setup/readback contract: {readiness!r}"
        )
    generation = getattr(case.chemistry.model, "generation", None)
    if generation is None:
        raise SystemExit("setup/readback case has no typed generation contract")

    try:
        pyfluent = importlib.import_module("ansys.fluent.core")
    except ImportError as exc:
        raise SystemExit("install the project 'fluent' extra before this smoke") from exc

    session = None
    try:
        session = pyfluent.launch_fluent(
            product_version="26.1.0",
            mode="solver",
            dimension=2,
            precision="double",
            processor_count=args.processors,
            additional_arguments=os.environ.get(
                "FLUENT_ADDITIONAL_ARGUMENTS", f"-t{args.processors}"
            ),
            ui_mode="no_gui",
            start_transcript=True,
            cleanup_on_exit=True,
            start_timeout=600,
        )
        evidence = run_diffusion_fgm_setup_probe(
            session,
            case,
            repository_root=REPOSITORY_ROOT,
        )
        atomic_write_json(args.output.resolve(), {**evidence, "execution": execution})
    except BaseException as exc:
        failure = {
            "schema_version": "1",
            "case_id": case.physics.case.id,
            "status": "setup_readback_failed",
            "classification": generation.classification,
            "execution_scope": generation.execution_scope,
            "table_generation_permission": generation.table_generation_permission,
            "requested_generation": generation.model_dump(mode="json"),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
            "execution": execution,
        }
        diagnostics = getattr(exc, "probe_evidence", None)
        if isinstance(diagnostics, Mapping):
            failure["diagnostics"] = diagnostics
        atomic_write_json(args.output.resolve(), failure)
        raise
    finally:
        if session is not None:
            session.exit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
