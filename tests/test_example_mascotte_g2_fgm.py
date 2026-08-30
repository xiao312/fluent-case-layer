from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from fluent_case_layer.driver import assess_flamelet_table_readiness, compile_plan
from fluent_case_layer.schema import CaseSpec, DiffusionFgmSetupProbe, load_case

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "mascotte-g2-jl-fgm"


def test_g2_fgm_example_is_valid_but_table_generation_is_blocked() -> None:
    case = load_case(EXAMPLE / "case")
    plan = compile_plan(case)
    generation = case.chemistry.model.generation
    readiness = assess_flamelet_table_readiness(case)

    assert case.physics.case.readiness == "blocked"
    assert generation.classification == "engineer_selected_exploratory"
    assert generation.execution_scope == "setup_readback_only"
    assert generation.table_generation_permission == "prohibited"
    assert generation.progress_variable_definition == "fluent_default"
    assert readiness.ready is False
    assert readiness.mode == "setup_readback_only"
    assert [action.kind.value for action in plan.actions] == [
        "launch_solver",
        "load_asset",
        "reconcile_settings",
    ]
    assert all(action.kind.value != "iterate" for action in plan.actions)


def test_g2_assets_retain_exact_mesh_and_chemistry_hashes() -> None:
    assets = load_case(EXAMPLE / "case").assets.by_id()

    assert all(asset.kind != "table" for asset in assets.values())
    assert assets["g2-medium-mesh"].sha256 == (
        "3e25883157ac1459f6b21a722faec672134f23b4325c516a7e506771f7bb6f97"
    )
    assert assets["jl9-kinetics"].sha256 == (
        "84cfcea7f44efe64f28dfe9504df4b288ac8b91cc9cb2276d9471d95a6201630"
    )
    assert assets["jl9-thermodynamics"].sha256 == (
        "0ce753ecb5aa37ba61c36a37087fbf47ab91dfc2600613dd983800fa90cc68d7"
    )
    assert assets["jl9-transport"].sha256 == (
        "1fe96c9d2549a403f23274f579c924088f007b95ec9a393035b38d96de0a061f"
    )


def test_runtime_default_probe_requires_every_active_group_once() -> None:
    generation = load_case(EXAMPLE / "case").chemistry.model.generation
    data = generation.model_dump(mode="json")
    data["runtime_defaults"]["groups"].remove("table")

    with pytest.raises(ValidationError, match="missing table"):
        DiffusionFgmSetupProbe.model_validate(data)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: data["chemistry"]["model"]["generation"].update(
                {"equilibrium_operating_pressure": {"value": 5_500_000, "unit": "Pa"}}
            ),
            "must equal the case operating pressure",
        ),
        (
            lambda data: data["materials"]["materials"][0]["properties"][
                "density"
            ].update({"fallback_model": "peng_robinson"}),
            "exact SRK with no fallback",
        ),
        (
            lambda data: next(
                asset
                for asset in data["assets"]["assets"]
                if asset["id"] == "jl9-kinetics"
            ).update({"kind": "other"}),
            "must have kind=chemistry",
        ),
    ],
)
def test_g2_setup_probe_rejects_physical_identity_drift(
    mutate: object,
    message: str,
) -> None:
    data = load_case(EXAMPLE / "case").model_dump(mode="json")
    mutate(data)

    with pytest.raises(ValidationError, match=message):
        CaseSpec.model_validate(data)


def test_comparison_contract_keeps_replication_and_probe_claims_separate() -> None:
    contract = json.loads(
        (EXAMPLE / "reference" / "comparison-contract.json").read_text(encoding="utf-8")
    )

    historical = contract["historical_replication"]
    exploratory = contract["exploratory_setup_probe"]
    assert historical["status"] == "blocked"
    assert historical["exact_fluent_flamelet_or_pdf_tables_found"] == []
    assert len(historical["missing_reproduction_inputs"]) >= 6
    assert exploratory["status"] == "eligible_for_setup_readback_only"
    assert exploratory["table_generation_eligible"] is False
    assert exploratory["prohibited_operations"] == [
        "calculate_flamelets",
        "calculate_pdf_table",
        "flow_iterations",
    ]
