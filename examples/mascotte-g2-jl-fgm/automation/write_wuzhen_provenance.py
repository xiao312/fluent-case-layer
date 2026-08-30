#!/usr/bin/env python3
"""Write pre-Fluent provenance after verifying the immutable Wuzhen snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fluent_case_layer.driver.util import atomic_write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision-root", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--staging-contract", type=Path, required=True)
    parser.add_argument("--wheel-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--git-branch", required=True)
    parser.add_argument("--snapshot-sha256", required=True)
    parser.add_argument("--source-generated-root", required=True)
    parser.add_argument("--source-reference-root", required=True)
    parser.add_argument("--fluent-install", required=True)
    parser.add_argument("--pyfluent-environment", required=True)
    parser.add_argument("--hostfile", type=Path, required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--partition", required=True)
    parser.add_argument("--ranks", type=int, required=True)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected one JSON object in {path}")
    return value


def _wheel_entries(path: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, filename = line.split(maxsplit=1)
        entries.append((digest, filename.strip()))
    return entries


def main() -> int:
    args = parse_args()
    if args.ranks != 1:
        raise SystemExit("the setup/readback profile is locked to one Fluent rank")

    revision_root = args.revision_root.resolve()
    repository_root = args.repository_root.resolve()
    run_dir = args.run_dir.resolve()
    contract = _load_json_object(args.staging_contract.resolve())

    staged_assets: dict[str, dict[str, Any]] = {}
    for entry in contract["simulation_assets"]:
        path = revision_root / entry["staged_path"]
        observed_size = path.stat().st_size
        observed_sha256 = _sha256(path)
        if observed_size != entry["size_bytes"] or observed_sha256 != entry["sha256"]:
            raise SystemExit(f"staged simulation asset differs from lock: {entry['id']}")
        staged_assets[entry["id"]] = {
            "staged_path": entry["staged_path"],
            "sha256": observed_sha256,
            "size_bytes": observed_size,
            "verified": True,
        }

    runtime_dependencies: dict[str, dict[str, Any]] = {}
    for expected_sha256, filename in _wheel_entries(args.wheel_manifest.resolve()):
        path = revision_root / "runtime-wheels" / filename
        observed_sha256 = _sha256(path)
        if observed_sha256 != expected_sha256:
            raise SystemExit(f"runtime wheel differs from lock: {filename}")
        runtime_dependencies[filename] = {
            "sha256": observed_sha256,
            "size_bytes": path.stat().st_size,
            "verified": True,
        }

    hostfile_lines = [
        line.strip()
        for line in args.hostfile.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not hostfile_lines:
        raise SystemExit("Fluent hostfile is empty")

    provenance = {
        "schema_version": "1",
        "case_id": contract["case_id"],
        "mode": "setup_readback_only",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "git_commit": args.git_commit,
            "git_branch": args.git_branch,
            "snapshot_sha256": args.snapshot_sha256,
            "repository_root": str(repository_root),
            "revision_root": str(revision_root),
            "asset_source_revision": contract["source_revision"],
            "generated_asset_source_root": args.source_generated_root,
            "reference_asset_source_root": args.source_reference_root,
        },
        "scheduler": {
            "system": "slurm",
            "job_id": os.environ.get("SLURM_JOB_ID", ""),
            "account": args.account,
            "partition": args.partition,
            "node_list": os.environ.get("SLURM_JOB_NODELIST", ""),
            "ranks": args.ranks,
            "cpus_per_task": int(os.environ.get("SLURM_CPUS_PER_TASK", "0")),
            "run_dir": str(run_dir),
            "hostfile": hostfile_lines,
        },
        "runtime": {
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "pyfluent_version": importlib.metadata.version("ansys-fluent-core"),
            "pydantic_version": importlib.metadata.version("pydantic"),
            "pyyaml_version": importlib.metadata.version("PyYAML"),
            "fluent_product_version": "2026R1 (26.1.0)",
            "fluent_install": args.fluent_install,
            "pyfluent_environment": args.pyfluent_environment,
            "container_image": os.environ.get(
                "CONTAINER_IMAGE", "scnet-compute-runtime:wuzhen-default"
            ),
        },
        "staged_assets": staged_assets,
        "runtime_dependencies": runtime_dependencies,
        "safety_contract": {
            "flamelet_calculation_permitted": False,
            "pdf_calculation_permitted": False,
            "initialization_permitted": False,
            "iterations_permitted": False,
        },
    }
    if not provenance["scheduler"]["job_id"]:
        raise SystemExit("SLURM_JOB_ID is absent")
    if provenance["scheduler"]["cpus_per_task"] != 4:
        raise SystemExit("the setup/readback profile requires exactly four allocated CPUs")
    atomic_write_json(args.output.resolve(), provenance)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
