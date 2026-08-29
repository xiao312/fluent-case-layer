"""Chemistry mechanisms, combustion closures, and inlet stream intent."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import Identifier, Quantity, StrictModel, VersionedDocument, require_unit


class Composition(StrictModel):
    basis: Literal["mass_fraction", "mole_fraction"]
    fractions: dict[Identifier, float]

    @field_validator("fractions")
    @classmethod
    def normalized_fractions(cls, fractions: dict[str, float]) -> dict[str, float]:
        if not fractions:
            raise ValueError("composition must contain at least one species")
        if any(not math.isfinite(value) or value < 0 or value > 1 for value in fractions.values()):
            raise ValueError("composition fractions must be finite and between zero and one")
        total = sum(fractions.values())
        if not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError(f"composition fractions must sum to one, got {total:.9g}")
        return fractions


class BuiltinMechanism(StrictModel):
    type: Literal["builtin"]
    name: str


class AssetMechanism(StrictModel):
    type: Literal["asset"]
    format: Literal["chemkin", "cantera_yaml", "fluent_table"]
    mechanism_asset: Identifier
    thermodynamics_asset: Identifier | None = None
    transport_asset: Identifier | None = None


MechanismSource = Annotated[BuiltinMechanism | AssetMechanism, Field(discriminator="type")]


class NoChemistry(StrictModel):
    type: Literal["none"]


class FiniteRateChemistry(StrictModel):
    type: Literal["finite_rate"]
    mechanism: MechanismSource
    turbulence_interaction: Literal[
        "none",
        "eddy_dissipation",
        "finite_rate_eddy_dissipation",
        "edc",
    ] = "none"
    stiff_chemistry_solver: bool = True


class FlameletChemistry(StrictModel):
    type: Literal["flamelet"]
    mechanism: MechanismSource
    table_asset: Identifier | None = None
    table_mode: Literal["read", "calculate"] = "read"
    nonadiabatic: bool = True
    partially_premixed: bool = False
    progress_variable: bool = True

    @model_validator(mode="after")
    def table_required_when_reading(self) -> FlameletChemistry:
        if self.table_mode == "read" and self.table_asset is None:
            raise ValueError("flamelet table_mode=read requires table_asset")
        return self


ChemistryModel = Annotated[
    NoChemistry | FiniteRateChemistry | FlameletChemistry,
    Field(discriminator="type"),
]


class StreamSpec(StrictModel):
    temperature: Quantity
    composition: Composition

    @field_validator("temperature")
    @classmethod
    def temperature_unit(cls, value: Quantity) -> Quantity:
        if value.unit == "K" and value.value <= 0:
            raise ValueError("absolute temperature must be positive")
        return require_unit(value, {"K", "degC"}, "stream temperature")


class ChemistryDocument(VersionedDocument):
    model: ChemistryModel
    streams: dict[Identifier, StreamSpec] = Field(default_factory=dict)
    tracked_species: list[Identifier] = Field(default_factory=list)

    @field_validator("tracked_species")
    @classmethod
    def unique_species(cls, species: list[str]) -> list[str]:
        if len(species) != len(set(species)):
            raise ValueError("tracked_species must be unique")
        return species
