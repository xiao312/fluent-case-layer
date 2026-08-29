from __future__ import annotations

from pathlib import Path

from fluent_case_layer.driver import compile_plan, load_case

CASE_TEMPLATE = Path(__file__).resolve().parents[1] / "case"


def test_typed_case_compiles_to_dependency_ordered_driver_plan() -> None:
    loaded = load_case(CASE_TEMPLATE)
    plan = compile_plan(loaded.case, platform=loaded.platform)

    assert plan.case_id == "illustrative-reacting-flow"
    assert [action.id for action in plan.actions] == [
        "launch-solver",
        "load-mesh",
        "configure",
        "initialize",
        "smoke",
        "sample",
        "accept",
        "final-checkpoint",
    ]
    assert plan.actions[-1].depends_on == ("accept",)
    assert len(plan.plan_hash) == 64
    assert plan.metadata["objectives"]["enforcement"] == "none"
    assert plan.metadata["objectives"]["revision"]["id"] == "initial-objectives"
    assert len(plan.metadata["objectives"]["content_digest"]) == 64
    assert plan.metadata["state_ownership"]["policy"]["mode"] == "full_definition"
    assert len(plan.metadata["state_ownership"]["content_digest"]) == 64
