#!/usr/bin/env python3
"""Fail-closed verification for one Wuzhen G2 setup/readback probe."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from fluent_case_layer.driver.util import atomic_write_json, file_sha256, stable_hash
from fluent_case_layer.schema import load_case

EXPECTED_ALLOWED_VALUES = {
    "species_model": "partially-premixed-combustion",
    "state_relation": "fgm",
    "energy_treatment": "non-adia",
    "flamelet_options": "create-flamelet",
    "flamelet_type": "diffusion-flamelet",
    "composition_basis": "mass-fraction",
    "turbulence_chemistry_interaction": "fr",
    "variance_method": "solve",
    "probability_density_function": "beta",
    "density_eos": "real-gas-soave-redlich-kwong",
}
PROBE_ASSET_IDS = {
    "g2-medium-mesh",
    "jl9-kinetics",
    "jl9-thermodynamics",
    "jl9-transport",
}
PDF_SETTINGS_PATH = (
    "setup/models/species/partially-premixed-combustion-parameters/probability-density-function"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--execution-provenance", type=Path, required=True)
    parser.add_argument("--staging-contract", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-snapshot-sha256", required=True)
    parser.add_argument("--expected-job-id", required=True)
    return parser.parse_args()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TypeError(f"expected one JSON object in {path}")
    return value


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _require_capture(value: Any, label: str) -> Mapping[str, Any]:
    capture = _require_mapping(value, label)
    status = capture.get("status")
    if status == "ok":
        if "value" not in capture:
            raise ValueError(f"{label} has no captured value")
    elif status == "error":
        error = _require_mapping(capture.get("error"), f"{label} error")
        if not isinstance(error.get("type"), str) or not isinstance(error.get("message"), str):
            raise ValueError(f"{label} error is incomplete")
    else:
        raise ValueError(f"{label} has invalid capture status")
    return capture


def _capture_value(capture: Mapping[str, Any]) -> Any:
    return capture.get("value") if capture.get("status") == "ok" else None


def _parent_pdf_value(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return None
    for key in ("probability_density_function", "probability-density-function"):
        if key in value:
            return value[key]
    return None


def verify(
    *,
    case_path: Path,
    evidence_path: Path,
    provenance_path: Path,
    staging_contract_path: Path,
    expected_commit: str,
    expected_snapshot_sha256: str,
    expected_job_id: str,
) -> dict[str, Any]:
    case = load_case(case_path)
    evidence = _load_object(evidence_path)
    provenance = _load_object(provenance_path)
    contract = _load_object(staging_contract_path)

    if evidence.get("status") != "setup_readback_complete":
        raise ValueError(f"probe did not complete: {evidence.get('status')!r}")
    if evidence.get("case_id") != case.physics.case.id:
        raise ValueError("evidence case_id differs from the typed case")
    if evidence.get("case_digest") != stable_hash(case):
        raise ValueError("evidence case_digest differs from the loaded typed case")
    generation = case.chemistry.model.generation
    if generation is None:
        raise ValueError("typed case has no FGM setup/readback generation contract")
    if evidence.get("classification") != generation.classification:
        raise ValueError("evidence classification differs from the typed case")
    if evidence.get("execution_scope") != "setup_readback_only":
        raise ValueError("evidence is outside setup_readback_only scope")
    if evidence.get("table_generation_permission") != "prohibited":
        raise ValueError("evidence does not preserve table_generation_permission=prohibited")
    if evidence.get("requested_generation") != generation.model_dump(mode="json"):
        raise ValueError("requested generation differs from the typed case")
    if not re.search(
        r"(?:26\.1|2026\s*R1)",
        str(evidence.get("fluent_version")),
        re.IGNORECASE,
    ):
        raise ValueError("evidence does not report Fluent 2026 R1")

    for name in (
        "flamelet_calculation_performed",
        "pdf_calculation_performed",
        "table_generation_eligible",
    ):
        if evidence.get(name) is not False:
            raise ValueError(f"{name} must be exactly false")
    if not isinstance(evidence.get("next_required_action"), str):
        raise TypeError("next_required_action is absent")

    expected_groups = set(generation.runtime_defaults.groups)
    readback = _require_mapping(evidence.get("readback"), "readback")
    if set(readback) != expected_groups:
        raise ValueError("readback does not contain exactly the requested Fluent groups")
    for name, value in readback.items():
        if not isinstance(value, Mapping) or not value:
            raise ValueError(f"readback group is empty or not an object: {name}")

    allowed_values = _require_mapping(evidence.get("allowed_values"), "allowed_values")
    if set(allowed_values) != set(EXPECTED_ALLOWED_VALUES):
        raise ValueError("allowed-value evidence is incomplete")
    for name, selected in EXPECTED_ALLOWED_VALUES.items():
        values = allowed_values[name]
        if not isinstance(values, list):
            raise TypeError(f"allowed values for {name} are not a list")
        if name == "probability_density_function":
            if values and selected not in values:
                raise ValueError("live PDF allowed values explicitly exclude beta")
            continue
        if not values or selected not in values:
            raise ValueError(f"selected {name} value is absent from Fluent allowed values")

    pdf = _require_mapping(
        evidence.get("probability_density_function_evidence"),
        "probability_density_function_evidence",
    )
    if pdf.get("requested") != "beta":
        raise ValueError("PDF evidence does not request beta")
    runtime_version = pdf.get("runtime_version")
    if runtime_version != evidence.get("fluent_version") or not re.search(
        r"(?:26\.1|2026\s*R1|v261)", str(runtime_version), re.IGNORECASE
    ):
        raise ValueError("PDF evidence is not locked to the reported Fluent 2026 R1 runtime")
    captures = {
        name: _require_capture(pdf.get(name), f"PDF {name}")
        for name in (
            "allowed_values_helper",
            "raw_attrs",
            "current_state_before",
            "parent_state_before",
            "generated_v261_schema",
            "runtime_static_info",
            "current_state_after",
            "parent_state_after",
        )
    }
    generated = _capture_value(captures["generated_v261_schema"])
    if not isinstance(generated, Mapping):
        raise TypeError("generated v261 PDF schema was not captured")
    generated_path = generated.get("path")
    if isinstance(generated_path, str):
        generated_path = generated_path.removeprefix("fluent/")
    if not (
        generated.get("module") == "ansys.fluent.core.generated.solver.settings_261"
        and generated.get("class") == "probability_density_function"
        and generated.get("version") == "261"
        and generated.get("exposure_level") == "stable"
        and generated.get("fluent_name") == "probability-density-function"
        and generated.get("python_name") == "probability_density_function"
        and generated_path == PDF_SETTINGS_PATH
        and generated.get("beta_constant") == "beta"
        and generated.get("allowed_values") == ["double-delta", "beta"]
    ):
        raise ValueError("generated v261 PDF schema evidence is not exact")

    helper_values = _capture_value(captures["allowed_values_helper"])
    raw = _capture_value(captures["raw_attrs"])
    raw_attrs = raw.get("attrs", {}) if isinstance(raw, Mapping) else {}
    raw_values = raw_attrs.get("allowed-values")
    for values in (helper_values, raw_values):
        if isinstance(values, list) and values and "beta" not in values:
            raise ValueError("captured live PDF metadata explicitly excludes beta")

    current_before = _capture_value(captures["current_state_before"])
    parent_before = _capture_value(captures["parent_state_before"])
    current_after = _capture_value(captures["current_state_after"])
    parent_after = _capture_value(captures["parent_state_after"])
    if current_after != "beta" or _parent_pdf_value(parent_after) != "beta":
        raise ValueError("PDF beta leaf and parent readback are not exact")

    decision = _require_mapping(pdf.get("decision"), "PDF decision")
    preconditions = _require_mapping(pdf.get("preconditions"), "PDF preconditions")
    mode = decision.get("mode")
    if decision.get("status") != "selected":
        raise ValueError("PDF decision is not selected")
    if mode == "existing_state_noop":
        if decision.get("setter_calls") != 0:
            raise ValueError("existing PDF beta no-op must not call the setter")
        if current_before != "beta" or _parent_pdf_value(parent_before) != "beta":
            raise ValueError("existing PDF beta no-op lacks exact initial readback")
    elif mode == "single_set_readback":
        if decision.get("setter_calls") != 1:
            raise ValueError("PDF setter path must contain exactly one call")
        required_preconditions = {
            "current_state_captured",
            "parent_state_captured",
            "raw_attrs_captured",
            "raw_allowed_values_valid",
            "runtime_2026_r1",
            "active",
            "writable",
            "generated_v261_schema",
            "runtime_static_info",
            "no_live_enum_conflict",
            "setter_authorized",
        }
        if set(preconditions) != required_preconditions or not all(preconditions.values()):
            raise ValueError("PDF setter was used without every fail-closed precondition")
        runtime_static = _capture_value(captures["runtime_static_info"])
        runtime_node = runtime_static.get("node") if isinstance(runtime_static, Mapping) else None
        runtime_path = runtime_static.get("path") if isinstance(runtime_static, Mapping) else None
        if isinstance(runtime_path, str):
            runtime_path = runtime_path.removeprefix("fluent/")
        runtime_enum = (
            runtime_node.get("allowed-values", runtime_node.get("allowed_values"))
            if isinstance(runtime_node, Mapping)
            else None
        )
        if not (
            runtime_path == PDF_SETTINGS_PATH
            and isinstance(runtime_node, Mapping)
            and runtime_node.get("type") == "string"
            and runtime_node.get("has-allowed-values") is True
            and runtime_enum == ["double-delta", "beta"]
        ):
            raise ValueError("runtime static-info does not authorize the PDF beta setter")
    else:
        raise ValueError(f"unsupported PDF selection mode: {mode!r}")

    stream = _require_mapping(evidence.get("stream_configuration"), "stream_configuration")
    if set(stream) != {"basis", "fuel", "oxidizer", "exposed_species"}:
        raise ValueError("stream_configuration is incomplete")
    if stream["basis"] != "mass-fraction":
        raise ValueError("unexpected FGM stream composition basis")
    if not all(stream[key] for key in ("fuel", "oxidizer", "exposed_species")):
        raise ValueError("FGM stream configuration contains an empty component")

    case_assets = case.assets.by_id()
    contract_assets = {entry["id"]: entry for entry in contract.get("simulation_assets", [])}
    required_staged_ids = PROBE_ASSET_IDS | {"singla-ohstar-relative"}
    if set(contract_assets) != required_staged_ids:
        raise ValueError("staging contract must contain exactly five approved simulation assets")
    for identifier, entry in contract_assets.items():
        locked = case_assets[identifier]
        if entry["sha256"] != locked.sha256 or entry["size_bytes"] != locked.size_bytes:
            raise ValueError(f"staging contract differs from assets.lock.yaml: {identifier}")

    probe_assets = _require_mapping(evidence.get("assets"), "probe assets")
    if set(probe_assets) != PROBE_ASSET_IDS:
        raise ValueError("probe evidence must contain exactly the mesh and three JL9 files")
    for identifier, observed in probe_assets.items():
        item = _require_mapping(observed, f"probe asset {identifier}")
        locked = case_assets[identifier]
        if (
            item.get("sha256") != locked.sha256
            or item.get("size_bytes") != locked.size_bytes
            or item.get("verified") is not True
        ):
            raise ValueError(f"probe asset verification is incomplete: {identifier}")

    if evidence.get("execution") != provenance:
        raise ValueError("embedded execution provenance differs from its source artifact")
    source = _require_mapping(provenance.get("source"), "provenance source")
    scheduler = _require_mapping(provenance.get("scheduler"), "provenance scheduler")
    runtime = _require_mapping(provenance.get("runtime"), "provenance runtime")
    staged_assets = _require_mapping(provenance.get("staged_assets"), "provenance staged_assets")
    safety = _require_mapping(provenance.get("safety_contract"), "safety contract")
    if source.get("git_commit") != expected_commit:
        raise ValueError("provenance Git commit differs from submitted commit")
    if source.get("snapshot_sha256") != expected_snapshot_sha256:
        raise ValueError("provenance snapshot differs from submitted snapshot")
    if scheduler.get("job_id") != expected_job_id:
        raise ValueError("provenance Slurm job id differs from active job")
    if scheduler.get("account") != "ac8azwcnf1":
        raise ValueError("probe did not run under the required Slurm account")
    if scheduler.get("partition") != "wzacnormal03":
        raise ValueError("probe did not run on the approved Wuzhen CPU partition")
    if scheduler.get("ranks") != 1 or scheduler.get("cpus_per_task") != 4:
        raise ValueError("probe resource readback differs from the one-rank profile")
    required_runtime = {
        "python_version",
        "python_executable",
        "pyfluent_version",
        "pydantic_version",
        "pyyaml_version",
        "fluent_product_version",
        "fluent_install",
        "pyfluent_environment",
        "container_image",
    }
    if set(runtime) != required_runtime or any(not runtime[key] for key in required_runtime):
        raise ValueError("runtime provenance is incomplete")
    if set(staged_assets) != required_staged_ids:
        raise ValueError("provenance does not contain exactly five staged simulation assets")
    for identifier, observed in staged_assets.items():
        if observed.get("verified") is not True:
            raise ValueError(f"staged asset is not verified: {identifier}")
    if safety != {
        "flamelet_calculation_permitted": False,
        "pdf_calculation_permitted": False,
        "initialization_permitted": False,
        "iterations_permitted": False,
    }:
        raise ValueError("execution safety contract is incomplete or permissive")

    runtime_dependencies = _require_mapping(
        provenance.get("runtime_dependencies"), "runtime dependencies"
    )
    if not runtime_dependencies or not all(
        isinstance(item, Mapping) and item.get("verified") is True
        for item in runtime_dependencies.values()
    ):
        raise ValueError("runtime dependency evidence is incomplete")

    return {
        "schema_version": "1",
        "status": "verified_setup_readback_complete",
        "case_id": case.physics.case.id,
        "git_commit": expected_commit,
        "snapshot_sha256": expected_snapshot_sha256,
        "slurm_job_id": expected_job_id,
        "evidence_sha256": file_sha256(evidence_path),
        "execution_provenance_sha256": file_sha256(provenance_path),
        "validated_readback_groups": sorted(expected_groups),
        "validated_simulation_assets": sorted(required_staged_ids),
        "pdf_selection_mode": mode,
        "calculation_or_iteration_performed": False,
        "success_marker_eligible": True,
    }


def main() -> int:
    args = parse_args()
    verification = verify(
        case_path=args.case.resolve(),
        evidence_path=args.evidence.resolve(),
        provenance_path=args.execution_provenance.resolve(),
        staging_contract_path=args.staging_contract.resolve(),
        expected_commit=args.expected_commit,
        expected_snapshot_sha256=args.expected_snapshot_sha256,
        expected_job_id=args.expected_job_id,
    )
    atomic_write_json(args.verification.resolve(), verification)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
