"""Solver and physical-model intent."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from .common import Identifier, Quantity, StrictModel, VersionedDocument, require_unit


class CaseMetadata(StrictModel):
    id: Identifier
    title: str
    readiness: Literal[
        "illustrative",
        "draft",
        "smoke_validated",
        "numerically_validated",
        "scientifically_validated",
        "blocked",
    ] = "draft"
    description: str | None = None
    known_blockers: list[str] = Field(default_factory=list)


class SolverSpec(StrictModel):
    dimension: Literal["2d_planar", "2d_axisymmetric", "3d"]
    formulation: Literal["pressure_based", "density_based"] = "pressure_based"
    time: Literal["steady", "transient"] = "steady"
    precision: Literal["single", "double"] = "double"
    velocity_formulation: Literal["absolute", "relative"] = "absolute"
    energy: bool = True
    operating_pressure: Quantity

    @field_validator("operating_pressure")
    @classmethod
    def pressure_unit(cls, value: Quantity) -> Quantity:
        if value.value <= 0:
            raise ValueError("operating pressure must be positive")
        return require_unit(value, {"Pa", "kPa", "MPa", "bar", "atm"}, "operating pressure")


class LaminarTurbulence(StrictModel):
    type: Literal["laminar"]


class KEpsilonTurbulence(StrictModel):
    type: Literal["k_epsilon"]
    variant: Literal["standard", "realizable", "rng"] = "realizable"
    near_wall: Literal[
        "standard_wall_functions", "enhanced_wall_treatment", "scalable_wall_functions"
    ] = "standard_wall_functions"


class KOmegaTurbulence(StrictModel):
    type: Literal["k_omega"]
    variant: Literal["standard", "sst"] = "sst"


class ReynoldsStressTurbulence(StrictModel):
    type: Literal["reynolds_stress"]
    variant: Literal["linear_pressure_strain", "ssg"] = "ssg"


class LesTurbulence(StrictModel):
    type: Literal["les"]
    subgrid: Literal["smagorinsky_lilly", "wale", "dynamic_smagorinsky"] = "wale"
    synthetic_turbulence: bool = False


TurbulenceModel = Annotated[
    LaminarTurbulence
    | KEpsilonTurbulence
    | KOmegaTurbulence
    | ReynoldsStressTurbulence
    | LesTurbulence,
    Field(discriminator="type"),
]


class SpeciesDisabled(StrictModel):
    type: Literal["none"]


class SpeciesTransport(StrictModel):
    type: Literal["species_transport"]
    volumetric_reactions: bool = True
    diffusion_energy_source: bool = True
    turbulence_chemistry: Literal[
        "none", "eddy_dissipation", "finite_rate_eddy_dissipation", "edc"
    ] = "none"


class NonPremixedPdf(StrictModel):
    type: Literal["nonpremixed_pdf"]
    nonadiabatic: bool = True
    progress_variable: bool = False


class PartiallyPremixedPdf(StrictModel):
    type: Literal["partially_premixed_pdf"]
    nonadiabatic: bool = True
    progress_variable: bool = True


SpeciesModel = Annotated[
    SpeciesDisabled | SpeciesTransport | NonPremixedPdf | PartiallyPremixedPdf,
    Field(discriminator="type"),
]


class RadiationDisabled(StrictModel):
    type: Literal["none"]


class P1Radiation(StrictModel):
    type: Literal["p1"]
    absorption: Literal["wsggm", "constant"] = "wsggm"


class DiscreteOrdinatesRadiation(StrictModel):
    type: Literal["discrete_ordinates"]
    theta_divisions: int = Field(default=4, ge=1)
    phi_divisions: int = Field(default=4, ge=1)


RadiationModel = Annotated[
    RadiationDisabled | P1Radiation | DiscreteOrdinatesRadiation,
    Field(discriminator="type"),
]


class DiscretePhaseModel(StrictModel):
    enabled: bool = False
    interaction_with_continuous_phase: bool = False
    unsteady_tracking: bool = False
    update_every_flow_iterations: int = Field(default=10, ge=1)
    max_tracking_steps: int = Field(default=50000, ge=1)


class PhysicsDocument(VersionedDocument):
    case: CaseMetadata
    solver: SolverSpec
    turbulence: TurbulenceModel
    species: SpeciesModel = Field(default_factory=lambda: SpeciesDisabled(type="none"))
    radiation: RadiationModel = Field(default_factory=lambda: RadiationDisabled(type="none"))
    discrete_phase: DiscretePhaseModel = Field(default_factory=DiscretePhaseModel)
