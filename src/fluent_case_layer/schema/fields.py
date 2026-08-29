"""Initial field values and typed Fluent boundary conditions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .chemistry import Composition
from .common import (
    ExpressionValue,
    FieldValue,
    Identifier,
    ProfileValue,
    Quantity,
    StrictModel,
    VectorQuantity,
    VersionedDocument,
    ZoneSelector,
    ensure_unique_ids,
    require_unit,
)


class FieldSpec(StrictModel):
    id: Identifier
    fluent_name: str
    rank: Literal["scalar", "vector"]
    initial: FieldValue
    required: bool = True

    @model_validator(mode="after")
    def matching_value_rank(self) -> FieldSpec:
        vector_value = self.initial.type == "uniform_vector"
        if self.rank == "vector" and self.initial.type == "uniform_scalar":
            raise ValueError("vector fields cannot use uniform_scalar initial values")
        if self.rank == "scalar" and vector_value:
            raise ValueError("scalar fields cannot use uniform_vector initial values")
        return self


class FieldsDocument(VersionedDocument):
    fields: Annotated[list[FieldSpec], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_fields(self) -> FieldsDocument:
        ensure_unique_ids(self.fields, "field")
        return self


class NoTurbulenceInput(StrictModel):
    type: Literal["none"]


class IntensityHydraulicDiameter(StrictModel):
    type: Literal["intensity_hydraulic_diameter"]
    intensity: float = Field(ge=0, le=1)
    hydraulic_diameter: Quantity

    @field_validator("hydraulic_diameter")
    @classmethod
    def length_unit(cls, value: Quantity) -> Quantity:
        if value.value <= 0:
            raise ValueError("hydraulic diameter must be positive")
        return require_unit(value, {"m", "cm", "mm"}, "hydraulic diameter")


class IntensityLengthScale(StrictModel):
    type: Literal["intensity_length_scale"]
    intensity: float = Field(ge=0, le=1)
    length_scale: Quantity

    @field_validator("length_scale")
    @classmethod
    def length_unit(cls, value: Quantity) -> Quantity:
        if value.value <= 0:
            raise ValueError("turbulence length scale must be positive")
        return require_unit(value, {"m", "cm", "mm"}, "turbulence length scale")


class KEpsilonInput(StrictModel):
    type: Literal["k_epsilon"]
    turbulent_kinetic_energy: Quantity
    dissipation_rate: Quantity


TurbulenceInput = Annotated[
    NoTurbulenceInput | IntensityHydraulicDiameter | IntensityLengthScale | KEpsilonInput,
    Field(discriminator="type"),
]


class MassFlowInlet(StrictModel):
    type: Literal["mass_flow_inlet"]
    mass_flow: Quantity
    temperature: Quantity
    species: Composition | None = None
    turbulence: TurbulenceInput = Field(default_factory=lambda: NoTurbulenceInput(type="none"))

    @field_validator("mass_flow")
    @classmethod
    def flow_unit(cls, value: Quantity) -> Quantity:
        if value.value < 0:
            raise ValueError("mass flow cannot be negative")
        return require_unit(value, {"kg/s", "g/s"}, "mass flow")

    @field_validator("temperature")
    @classmethod
    def temperature_unit(cls, value: Quantity) -> Quantity:
        return require_unit(value, {"K", "degC"}, "inlet temperature")


class VelocityInlet(StrictModel):
    type: Literal["velocity_inlet"]
    velocity: VectorQuantity
    temperature: Quantity | None = None
    species: Composition | None = None
    turbulence: TurbulenceInput = Field(default_factory=lambda: NoTurbulenceInput(type="none"))

    @field_validator("velocity")
    @classmethod
    def velocity_unit(cls, value: VectorQuantity) -> VectorQuantity:
        if value.unit not in {"m/s", "cm/s"}:
            raise ValueError("velocity must use m/s or cm/s")
        return value


class PressureOutlet(StrictModel):
    type: Literal["pressure_outlet"]
    gauge_pressure: Quantity
    backflow_temperature: Quantity | None = None
    backflow_species: Composition | None = None
    turbulence: TurbulenceInput = Field(default_factory=lambda: NoTurbulenceInput(type="none"))

    @field_validator("gauge_pressure")
    @classmethod
    def pressure_unit(cls, value: Quantity) -> Quantity:
        return require_unit(value, {"Pa", "kPa", "MPa", "bar", "atm"}, "gauge pressure")


class AdiabaticWall(StrictModel):
    type: Literal["adiabatic"]


class FixedTemperatureWall(StrictModel):
    type: Literal["temperature"]
    temperature: Quantity | ProfileValue | ExpressionValue


class FixedHeatFluxWall(StrictModel):
    type: Literal["heat_flux"]
    heat_flux: Quantity | ProfileValue | ExpressionValue


class ConvectionWall(StrictModel):
    type: Literal["convection"]
    heat_transfer_coefficient: Quantity
    external_temperature: Quantity


WallThermalCondition = Annotated[
    AdiabaticWall | FixedTemperatureWall | FixedHeatFluxWall | ConvectionWall,
    Field(discriminator="type"),
]


class WallBoundary(StrictModel):
    type: Literal["wall"]
    shear: Literal["no_slip", "slip"] = "no_slip"
    thermal: WallThermalCondition = Field(default_factory=lambda: AdiabaticWall(type="adiabatic"))


class SymmetryBoundary(StrictModel):
    type: Literal["symmetry"]


class AxisBoundary(StrictModel):
    type: Literal["axis"]


BoundaryCondition = Annotated[
    MassFlowInlet | VelocityInlet | PressureOutlet | WallBoundary | SymmetryBoundary | AxisBoundary,
    Field(discriminator="type"),
]


class BoundarySpec(StrictModel):
    id: Identifier
    zones: ZoneSelector
    condition: BoundaryCondition


class BoundaryConditionsDocument(VersionedDocument):
    boundaries: Annotated[list[BoundarySpec], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_boundaries(self) -> BoundaryConditionsDocument:
        ensure_unique_ids(self.boundaries, "boundary")
        return self
