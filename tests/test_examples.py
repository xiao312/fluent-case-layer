from __future__ import annotations

from pathlib import Path

import pytest

from fluent_case_layer.driver import compile_campaign, compile_plan
from fluent_case_layer.driver.campaign import validate_campaign
from fluent_case_layer.schema import load_case

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {
    "transient-1d-h2-air": 8,
    "m2-torch-igniter": 14,
    "effusion-drm19-fgm": 13,
}


@pytest.mark.parametrize(("case_id", "authored_stages"), EXAMPLES.items())
def test_example_is_strictly_valid_and_compiles(case_id: str, authored_stages: int) -> None:
    case = load_case(ROOT / "examples" / case_id / "case")
    plan = compile_plan(case)

    assert case.physics.case.id == case_id
    assert len(case.control.stages) == authored_stages
    assert len(plan.actions) == authored_stages + 1  # compiler-injected launch boundary
    assert plan.case_id == case_id
    assert len(plan.plan_hash) == 64


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
