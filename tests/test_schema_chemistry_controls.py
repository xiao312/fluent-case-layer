from __future__ import annotations

import pytest
from pydantic import ValidationError

from fluent_case_layer.schema.chemistry import FiniteRateChemistry


def finite_rate(**updates: object) -> FiniteRateChemistry:
    data: dict[str, object] = {
        "type": "finite_rate",
        "mechanism": {"type": "builtin", "name": "hydrogen-air"},
        "turbulence_interaction": "edc",
        "stiff_chemistry_solver": True,
        "stiff_solver_controls": {
            "absolute_ode_tolerance": 1.0e-8,
            "relative_ode_tolerance": 1.0e-9,
        },
        "edc_controls": {
            "aggressiveness_factor": 0.0,
            "flow_iterations_per_chemistry_update": 5,
        },
    }
    data.update(updates)
    return FiniteRateChemistry.model_validate(data)


def test_finite_rate_accepts_typed_stiff_and_edc_controls() -> None:
    model = finite_rate()

    assert model.stiff_solver_controls is not None
    assert model.stiff_solver_controls.absolute_ode_tolerance == 1.0e-8
    assert model.edc_controls is not None
    assert model.edc_controls.flow_iterations_per_chemistry_update == 5


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"stiff_chemistry_solver": False},
            "stiff_solver_controls require stiff_chemistry_solver=true",
        ),
        (
            {"turbulence_interaction": "none"},
            "edc_controls require turbulence_interaction=edc",
        ),
    ],
)
def test_finite_rate_rejects_inactive_controls(
    updates: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        finite_rate(**updates)


@pytest.mark.parametrize(
    "edc_controls",
    [
        {"aggressiveness_factor": -0.1, "flow_iterations_per_chemistry_update": 1},
        {"aggressiveness_factor": 1.1, "flow_iterations_per_chemistry_update": 1},
        {"aggressiveness_factor": 0.5, "flow_iterations_per_chemistry_update": 0},
    ],
)
def test_finite_rate_rejects_out_of_range_edc_controls(
    edc_controls: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        finite_rate(edc_controls=edc_controls)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 0.0, -1.0])
def test_finite_rate_rejects_invalid_ode_tolerance(value: float) -> None:
    with pytest.raises(ValidationError):
        finite_rate(
            stiff_solver_controls={
                "absolute_ode_tolerance": value,
                "relative_ode_tolerance": 1.0e-9,
            }
        )
