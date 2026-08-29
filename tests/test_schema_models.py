from __future__ import annotations

import pytest
from pydantic import ValidationError

from fluent_case_layer.schema.chemistry import Composition
from fluent_case_layer.schema.common import Cardinality, Quantity, ZonePatternSelector
from fluent_case_layer.schema.numerics import NumericsDocument


def test_quantity_requires_finite_value_and_unit() -> None:
    assert Quantity(value=1.0, unit="kg/s").unit == "kg/s"
    with pytest.raises(ValidationError):
        Quantity(value=float("nan"), unit="Pa")
    with pytest.raises(ValidationError):
        Quantity(value=1.0, unit="")


def test_zone_cardinality_bounds_are_consistent() -> None:
    assert Cardinality(exactly=2).exactly == 2
    with pytest.raises(ValidationError):
        Cardinality(at_least=3, at_most=2)
    with pytest.raises(ValidationError):
        Cardinality(exactly=1, at_least=1)
    with pytest.raises(ValidationError):
        ZonePatternSelector(type="pattern", pattern="[", cardinality={"at_least": 1})


def test_composition_is_normalized() -> None:
    composition = Composition(
        basis="mass_fraction",
        fractions={"o2": 0.233, "n2": 0.767},
    )
    assert sum(composition.fractions.values()) == pytest.approx(1.0)
    with pytest.raises(ValidationError, match="sum to one"):
        Composition(basis="mass_fraction", fractions={"o2": 0.2, "n2": 0.7})


def test_numerics_profile_inheritance_is_a_dag() -> None:
    with pytest.raises(ValidationError, match="cycle in numerics profile"):
        NumericsDocument(
            schema_version="1.0",
            default_profile="a",
            profiles={
                "a": {"extends": "b"},
                "b": {"extends": "a"},
            },
        )
