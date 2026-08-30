from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from fluent_case_layer.driver.util import stable_hash
from fluent_case_layer.schema import load_case

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "mascotte-g2-jl-fgm"
AUTOMATION = EXAMPLE / "automation"
CASE_PATH = EXAMPLE / "case"


def load_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def load_verifier() -> ModuleType:
    path = AUTOMATION / "verify_wuzhen_setup_readback.py"
    spec = importlib.util.spec_from_file_location("wuzhen_setup_readback_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wuzhen_profile_is_the_bounded_one_rank_cpu_allocation() -> None:
    case = load_case(CASE_PATH)
    platform = case.platforms["scnet-wuzhen-setup-readback"]

    assert platform.scheduler.partition == "wzacnormal03"
    assert platform.scheduler.account_variable == "SCNET_SLURM_ACCOUNT"
    assert platform.hardware == "cpu"
    assert platform.resources.nodes == 1
    assert platform.resources.ranks == 1
    assert platform.resources.tasks_per_node == 4
    assert platform.resources.memory_per_node.model_dump(mode="json") == {
        "value": 7.0,
        "unit": "GiB",
    }
    assert platform.resources.walltime.model_dump(mode="json") == {
        "value": 20.0,
        "unit": "min",
    }


def test_staging_contract_contains_exactly_the_five_locked_simulation_assets() -> None:
    case = load_case(CASE_PATH)
    locked = case.assets.by_id()
    contract = load_json(AUTOMATION / "wuzhen-setup-readback-assets.json")
    entries = {entry["id"]: entry for entry in contract["simulation_assets"]}

    assert contract["source_revision"] == "4d40647ebccb2674cadf19f0bf19a02efd26550b"
    assert set(entries) == {
        "g2-medium-mesh",
        "jl9-kinetics",
        "jl9-thermodynamics",
        "jl9-transport",
        "singla-ohstar-relative",
    }
    for identifier, entry in entries.items():
        assert entry["sha256"] == locked[identifier].sha256
        assert entry["size_bytes"] == locked[identifier].size_bytes
    assert {entry["staged_path"] for entry in entries.values()} == {
        "runtime-assets/mesh/g2-medium.msh",
        "runtime-assets/jl9/jl9.inp",
        "runtime-assets/jl9/jl9-thermo.dat",
        "runtime-assets/jl9/jl9-transport.dat",
        "runtime-assets/reference/singla-g2-ohstar-relative.npz",
    }


def test_wuzhen_runtime_wheels_are_exactly_locked() -> None:
    lines = [
        line.split(maxsplit=1)
        for line in (AUTOMATION / "wuzhen-runtime-wheels.sha256")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    assert {filename.strip() for _, filename in lines} == {
        "annotated_types-0.8.0-py3-none-any.whl",
        "pydantic-2.13.5-py3-none-any.whl",
        "pydantic_core-2.46.5-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
        "typing_extensions-4.16.0-py3-none-any.whl",
        "typing_inspection-0.4.4-py3-none-any.whl",
    }
    assert all(len(digest) == 64 for digest, _ in lines)


def synthetic_artifacts(tmp_path: Path) -> tuple[Path, Path, str, str, str]:
    case = load_case(CASE_PATH)
    contract = load_json(AUTOMATION / "wuzhen-setup-readback-assets.json")
    commit = "a" * 40
    snapshot = "b" * 64
    job_id = "12345678"
    staged_assets = {
        entry["id"]: {
            "staged_path": entry["staged_path"],
            "sha256": entry["sha256"],
            "size_bytes": entry["size_bytes"],
            "verified": True,
        }
        for entry in contract["simulation_assets"]
    }
    provenance = {
        "schema_version": "1",
        "case_id": case.physics.case.id,
        "mode": "setup_readback_only",
        "created_at_utc": "2026-08-31T00:00:00+00:00",
        "source": {
            "git_commit": commit,
            "git_branch": "feat/test",
            "snapshot_sha256": snapshot,
            "repository_root": "/remote/repository",
            "revision_root": "/remote/revision",
            "asset_source_revision": contract["source_revision"],
            "generated_asset_source_root": "/remote/source/generated",
            "reference_asset_source_root": "/remote/source/reference",
        },
        "scheduler": {
            "system": "slurm",
            "job_id": job_id,
            "account": "ac8azwcnf1",
            "partition": "wzacnormal03",
            "node_list": "node01",
            "ranks": 1,
            "cpus_per_task": 4,
            "run_dir": "/remote/run",
            "hostfile": ["node01:1"],
        },
        "runtime": {
            "python_version": "3.11.15",
            "python_executable": "/remote/python",
            "pyfluent_version": "0.40.2",
            "pydantic_version": "2.13.5",
            "pyyaml_version": "6.0.3",
            "fluent_product_version": "2026R1 (26.1.0)",
            "fluent_install": "/remote/fluent",
            "pyfluent_environment": "/remote/pyfluent",
            "container_image": "scnet-compute-runtime:wuzhen-default",
        },
        "staged_assets": staged_assets,
        "runtime_dependencies": {
            "pydantic-2.13.5-py3-none-any.whl": {
                "sha256": "c" * 64,
                "size_bytes": 1,
                "verified": True,
            }
        },
        "safety_contract": {
            "flamelet_calculation_permitted": False,
            "pdf_calculation_permitted": False,
            "initialization_permitted": False,
            "iterations_permitted": False,
        },
    }
    probe_assets = {}
    for identifier in (
        "g2-medium-mesh",
        "jl9-kinetics",
        "jl9-thermodynamics",
        "jl9-transport",
    ):
        asset = case.assets.by_id()[identifier]
        probe_assets[identifier] = {
            "kind": asset.kind,
            "sha256": asset.sha256,
            "size_bytes": asset.size_bytes,
            "verified": True,
        }
    generation = case.chemistry.model.generation
    evidence = {
        "schema_version": "1",
        "case_id": case.physics.case.id,
        "case_digest": stable_hash(case),
        "fluent_version": "2026 R1 (26.1.0)",
        "classification": generation.classification,
        "execution_scope": generation.execution_scope,
        "status": "setup_readback_complete",
        "assets": probe_assets,
        "requested_generation": generation.model_dump(mode="json"),
        "stream_configuration": {
            "basis": "mass-fraction",
            "fuel": {"ch4": 1.0},
            "oxidizer": {"o2": 1.0},
            "exposed_species": ["ch4", "o2"],
        },
        "readback": {
            name: {"captured": True}
            for name in generation.runtime_defaults.groups
        },
        "allowed_values": {
            "species_model": ["partially-premixed-combustion"],
            "state_relation": ["fgm"],
            "energy_treatment": ["non-adia"],
            "flamelet_options": ["create-flamelet"],
            "flamelet_type": ["diffusion-flamelet"],
            "composition_basis": ["mass-fraction"],
            "turbulence_chemistry_interaction": ["fr"],
            "variance_method": ["solve"],
            "probability_density_function": ["beta"],
            "density_eos": ["real-gas-soave-redlich-kwong"],
        },
        "flamelet_calculation_performed": False,
        "pdf_calculation_performed": False,
        "table_generation_eligible": False,
        "next_required_action": "Review and freeze captured settings.",
        "execution": provenance,
    }
    evidence_path = tmp_path / "setup-readback.json"
    provenance_path = tmp_path / "execution-provenance.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    return evidence_path, provenance_path, commit, snapshot, job_id


def test_independent_verifier_accepts_complete_synthetic_evidence(tmp_path: Path) -> None:
    evidence, provenance, commit, snapshot, job_id = synthetic_artifacts(tmp_path)
    verifier = load_verifier()

    result = verifier.verify(
        case_path=CASE_PATH,
        evidence_path=evidence,
        provenance_path=provenance,
        staging_contract_path=AUTOMATION / "wuzhen-setup-readback-assets.json",
        expected_commit=commit,
        expected_snapshot_sha256=snapshot,
        expected_job_id=job_id,
    )

    assert result["status"] == "verified_setup_readback_complete"
    assert result["success_marker_eligible"] is True
    assert result["calculation_or_iteration_performed"] is False


def test_independent_verifier_rejects_incomplete_settings_readback(tmp_path: Path) -> None:
    evidence, provenance, commit, snapshot, job_id = synthetic_artifacts(tmp_path)
    payload = load_json(evidence)
    del payload["readback"]["table"]
    evidence.write_text(json.dumps(payload), encoding="utf-8")
    verifier = load_verifier()

    with pytest.raises(ValueError, match="readback does not contain exactly"):
        verifier.verify(
            case_path=CASE_PATH,
            evidence_path=evidence,
            provenance_path=provenance,
            staging_contract_path=AUTOMATION / "wuzhen-setup-readback-assets.json",
            expected_commit=commit,
            expected_snapshot_sha256=snapshot,
            expected_job_id=job_id,
        )


def test_wuzhen_shell_entrypoints_are_syntactically_valid_and_fail_closed() -> None:
    submit = AUTOMATION / "submit_wuzhen_setup_readback.sh"
    runner = AUTOMATION / "run_wuzhen_setup_readback.slurm"
    subprocess.run(["bash", "-n", str(submit)], check=True)
    subprocess.run(["bash", "-n", str(runner)], check=True)

    submit_text = submit.read_text(encoding="utf-8")
    runner_text = runner.read_text(encoding="utf-8")
    assert submit_text.count("/opt/gridview/slurm/bin/sbatch") == 1
    assert "--account='${ACCOUNT}'" in submit_text
    assert "--partition='${PARTITION}'" in submit_text
    assert runner_text.index("verify_wuzhen_setup_readback.py") < runner_text.index(
        'touch "${RUN_DIR}/SUCCESS"'
    )
