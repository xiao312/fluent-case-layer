"""Material definitions and zone-to-material assignments."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    Identifier,
    Quantity,
    StrictModel,
    VersionedDocument,
    ZoneSelector,
    ensure_unique_ids,
)


class FluentDatabaseMaterialSource(StrictModel):
    type: Literal["fluent_database"]
    name: str


class ExplicitMaterialSource(StrictModel):
    type: Literal["explicit"]


class ChemistryMixtureMaterialSource(StrictModel):
    type: Literal["chemistry_mixture"]
    mixture: Identifier


MaterialSource = Annotated[
    FluentDatabaseMaterialSource | ExplicitMaterialSource | ChemistryMixtureMaterialSource,
    Field(discriminator="type"),
]


class ConstantProperty(StrictModel):
    type: Literal["constant"]
    value: Quantity


class IdealGasProperty(StrictModel):
    type: Literal["ideal_gas"]


class PolynomialProperty(StrictModel):
    type: Literal["polynomial"]
    coefficients: Annotated[list[float], Field(min_length=1)]
    independent_unit: str
    output_unit: str
    valid_range: tuple[Quantity, Quantity] | None = None

    @model_validator(mode="after")
    def ordered_range(self) -> PolynomialProperty:
        if self.valid_range is not None:
            lower, upper = self.valid_range
            if lower.unit != upper.unit or lower.value >= upper.value:
                raise ValueError(
                    "property valid_range must have matching units and increasing values"
                )
        return self


class SutherlandProperty(StrictModel):
    type: Literal["sutherland"]
    reference_value: Quantity
    reference_temperature: Quantity
    sutherland_temperature: Quantity


class FluentProperty(StrictModel):
    type: Literal["fluent_database"]
    name: str


class CubicEquationOfStateProperty(StrictModel):
    """Fluent cubic real-gas density intent for a fluid or mixture."""

    type: Literal["cubic_eos"]
    model: Literal["soave_redlich_kwong", "peng_robinson"] = Field(
        description="Primary cubic equation of state requested for the material density."
    )
    volume_translation: bool = Field(
        default=False,
        description="Request volume translation when the selected Fluent model exposes it.",
    )
    fallback_model: Literal["soave_redlich_kwong", "peng_robinson"] | None = Field(
        default=None,
        description=(
            "Distinct fallback accepted only when the primary model is unavailable in "
            "the live Fluent material state."
        ),
    )

    @model_validator(mode="after")
    def distinct_fallback(self) -> CubicEquationOfStateProperty:
        if self.fallback_model == self.model:
            raise ValueError("cubic EOS fallback_model must differ from model")
        return self


PropertyModel = Annotated[
    ConstantProperty
    | IdealGasProperty
    | PolynomialProperty
    | SutherlandProperty
    | FluentProperty
    | CubicEquationOfStateProperty,
    Field(discriminator="type"),
]


class MaterialSpec(StrictModel):
    id: Identifier
    kind: Literal["fluid", "solid", "mixture"]
    source: MaterialSource
    properties: dict[Identifier, PropertyModel] = Field(default_factory=dict)


class ZoneMaterialAssignment(StrictModel):
    id: Identifier
    zones: ZoneSelector
    material: Identifier


class MaterialsDocument(VersionedDocument):
    materials: Annotated[list[MaterialSpec], Field(min_length=1)]
    zone_assignments: list[ZoneMaterialAssignment] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_material_references(self) -> MaterialsDocument:
        ensure_unique_ids(self.materials, "material")
        ensure_unique_ids(self.zone_assignments, "zone assignment")
        names = {material.id for material in self.materials}
        missing = sorted({assignment.material for assignment in self.zone_assignments} - names)
        if missing:
            raise ValueError(f"zone assignments reference unknown materials: {', '.join(missing)}")
        return self
