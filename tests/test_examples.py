from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fluent_case_layer.driver import compile_campaign, compile_plan
from fluent_case_layer.driver.campaign import validate_campaign
from fluent_case_layer.schema import load_case

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {
    "transient-1d-h2-air": (8, "full_definition"),
    "m2-torch-igniter": (13, "checkpoint_overlay"),
    "effusion-drm19-fgm": (13, "full_definition"),
}


@pytest.mark.parametrize(("case_id", "expected"), EXAMPLES.items())
def test_example_is_strictly_valid_and_compiles(
    case_id: str, expected: tuple[int, str]
) -> None:
    authored_stages, state_mode = expected
    case = load_case(ROOT / "examples" / case_id / "case")
    plan = compile_plan(case)

    assert case.physics.case.id == case_id
    assert len(case.control.stages) == authored_stages
    assert case.state.mode == state_mode
    assert case.objectives.enforcement == "none"
    assert len(plan.actions) == authored_stages + 1  # compiler-injected launch boundary
    assert plan.case_id == case_id
    assert plan.metadata["objectives"]["enforcement"] == "none"
    assert plan.metadata["state_ownership"]["policy"]["mode"] == state_mode
    assert len(plan.plan_hash) == 64


def test_m2_overlay_only_owns_staged_register_and_patch_mutations() -> None:
    case = load_case(ROOT / "examples" / "m2-torch-igniter" / "case")

    assert case.state.baseline is not None
    assert case.state.baseline.case.asset == "m2-checkpoint-case"
    assert case.state.baseline.data is not None
    assert case.state.baseline.data.asset == "m2-checkpoint-data"
    assert {entry.path for entry in case.state.declared_paths} == {
        "solution.initialization.registers.ignition_full",
        "solution.initialization.registers.ignition_lower_clear",
        "solution.initialization.patches.full_progress",
        "solution.initialization.patches.lower_progress",
    }
    assert all(stage.type != "reconcile" for stage in case.control.stages)


def test_checked_in_reference_asset_digest_is_current() -> None:
    case = load_case(ROOT / "examples" / "effusion-drm19-fgm" / "case")
    asset = case.assets.by_id()["tutorial-field-reference"]
    reference_path = ROOT / asset.source.path

    assert reference_path.is_file()
    assert hashlib.sha256(reference_path.read_bytes()).hexdigest() == asset.sha256


def test_representative_campaign_compiles_all_examples_portably() -> None:
    campaign = compile_campaign(ROOT / "examples" / "campaign.yaml")

    assert [item.id for item in campaign.cases] == list(EXAMPLES)
    assert [item.source for item in campaign.cases] == [
        "transient-1d-h2-air/case",
        "m2-torch-igniter/case",
        "effusion-drm19-fgm/case",
    ]
    assert validate_campaign(campaign)["valid"] is True
    assert len(campaign.campaign_hash) == 64
