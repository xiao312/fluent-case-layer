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


class StiffSolverControls(StrictModel):
    absolute_ode_tolerance: float = Field(gt=0)
    relative_ode_tolerance: float = Field(gt=0)

    @field_validator("absolute_ode_tolerance", "relative_ode_tolerance")
    @classmethod
    def finite_tolerance(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("ODE tolerance must be finite")
        return value


class EdcControls(StrictModel):
    aggressiveness_factor: float = Field(ge=0, le=1)
    flow_iterations_per_chemistry_update: int = Field(ge=1)


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
    stiff_solver_controls: StiffSolverControls | None = None
    edc_controls: EdcControls | None = None

    @model_validator(mode="after")
    def controls_match_selected_closures(self) -> FiniteRateChemistry:
        if self.stiff_solver_controls is not None and not self.stiff_chemistry_solver:
            raise ValueError(
                "stiff_solver_controls require stiff_chemistry_solver=true"
            )
        if self.edc_controls is not None and self.turbulence_interaction != "edc":
            raise ValueError("edc_controls require turbulence_interaction=edc")
        return self


FlameletReadbackGroup = Literal[
    "chemistry",
    "boundary",
    "progress_variable_definition",
    "control",
    "flamelet",
    "table",
    "premix",
    "combustion_parameters",
    "material_density",
]

REQUIRED_FLAMELET_READBACK_GROUPS = {
    "chemistry",
    "boundary",
    "progress_variable_definition",
    "control",
    "flamelet",
    "table",
    "premix",
    "combustion_parameters",
    "material_density",
}


class FluentDefaultsProbe(StrictModel):
    """Runtime defaults that must be captured and frozen before table generation.

    This is intentionally a setup-only contract.  It makes release-specific Fluent
    defaults visible without pretending that a paper specified them or allowing a
    table calculation to proceed with implicit choices.
    """

    fluent_release: Literal["2026R1"]
    groups: Annotated[list[FlameletReadbackGroup], Field(min_length=1)]
    require_complete_group_state: Literal[True] = True
    record_allowed_values: Literal[True] = True
    freeze_before_table_generation: Literal[True] = True

    @field_validator("groups")
    @classmethod
    def complete_unique_groups(cls, groups: list[str]) -> list[str]:
        if len(groups) != len(set(groups)):
            raise ValueError("Fluent default readback groups must be unique")
        missing = sorted(REQUIRED_FLAMELET_READBACK_GROUPS - set(groups))
        extra = sorted(set(groups) - REQUIRED_FLAMELET_READBACK_GROUPS)
        if missing or extra:
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if extra:
                details.append("unknown " + ", ".join(extra))
            raise ValueError(
                "setup-only FGM probes must capture the complete active state: "
                + "; ".join(details)
            )
        return groups


class DiffusionFgmSetupProbe(StrictModel):
    """Fully declared exploratory setup for discovering Fluent 2026 R1 defaults.

    The scope is deliberately limited to model setup and readback.  ``calc_fla`` and
    ``calc_pdf`` are prohibited until every runtime-derived value is reviewed and
    replaced by a frozen, hash-audited table-generation definition.
    """

    type: Literal["fluent_diffusion_fgm_setup_probe"]
    classification: Literal["engineer_selected_exploratory"]
    execution_scope: Literal["setup_readback_only"]
    table_generation_permission: Literal["prohibited"]
    fluent_release: Literal["2026R1"]
    mixture_name: Identifier
    fuel_stream: Identifier
    oxidizer_stream: Identifier
    equilibrium_operating_pressure: Quantity
    compressibility: Literal[True] = True
    progress_variable_definition: Literal["fluent_default"]
    turbulence_chemistry_interaction: Literal["finite_rate"]
    progress_variable_variance: Literal["transport"]
    probability_density_function: Literal["beta"]
    runtime_defaults: FluentDefaultsProbe

    @field_validator("equilibrium_operating_pressure")
    @classmethod
    def pressure_in_pascal(cls, value: Quantity) -> Quantity:
        if value.value <= 0:
            raise ValueError("equilibrium operating pressure must be positive")
        return require_unit(value, {"Pa"}, "FGM equilibrium operating pressure")

    @model_validator(mode="after")
    def matching_release(self) -> DiffusionFgmSetupProbe:
        if self.runtime_defaults.fluent_release != self.fluent_release:
            raise ValueError("runtime-default probe release must match the generation release")
        return self


class FlameletChemistry(StrictModel):
    type: Literal["flamelet"]
    mechanism: MechanismSource
    table_asset: Identifier | None = None
    table_mode: Literal["read", "calculate"] = "read"
    nonadiabatic: bool = True
    partially_premixed: bool = False
    progress_variable: bool = True
    generation: DiffusionFgmSetupProbe | None = None

    @model_validator(mode="after")
    def table_required_when_reading(self) -> FlameletChemistry:
        if self.table_mode == "read" and self.table_asset is None:
            raise ValueError("flamelet table_mode=read requires table_asset")
        if self.table_mode == "read" and self.generation is not None:
            raise ValueError("flamelet generation is incompatible with table_mode=read")
        if self.generation is not None:
            if self.table_mode != "calculate":
                raise ValueError("flamelet generation requires table_mode=calculate")
            if not self.partially_premixed or not self.progress_variable:
                raise ValueError(
                    "diffusion FGM setup requires partially_premixed=true and "
                    "progress_variable=true"
                )
            if not self.nonadiabatic:
                raise ValueError("the typed diffusion FGM setup probe is nonadiabatic")
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

    @model_validator(mode="after")
    def generation_streams(self) -> ChemistryDocument:
        if not isinstance(self.model, FlameletChemistry) or self.model.generation is None:
            return self
        generation = self.model.generation
        if generation.fuel_stream == generation.oxidizer_stream:
            raise ValueError("FGM fuel_stream and oxidizer_stream must differ")
        missing = sorted(
            {generation.fuel_stream, generation.oxidizer_stream} - self.streams.keys()
        )
        if missing:
            raise ValueError("FGM generation references unknown streams: " + ", ".join(missing))
        stream_temperatures = [
            self.streams[generation.fuel_stream].temperature,
            self.streams[generation.oxidizer_stream].temperature,
        ]
        if any(item.unit != "K" for item in stream_temperatures):
            raise ValueError("FGM setup-probe stream temperatures must use K")
        return self
