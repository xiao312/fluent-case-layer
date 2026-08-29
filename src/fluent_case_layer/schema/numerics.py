"""Named numerical-control profiles that stages can apply explicitly."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import Identifier, Quantity, StrictModel, VersionedDocument, require_unit

SpatialScheme = Literal[
    "first_order_upwind",
    "second_order_upwind",
    "power_law",
    "quick",
    "bounded_central_differencing",
    "central_differencing",
]
PressureScheme = Literal[
    "standard",
    "presto",
    "linear",
    "second_order",
    "body_force_weighted",
]


class EquationNumerics(StrictModel):
    enabled: bool = True
    spatial_scheme: SpatialScheme | None = None
    under_relaxation: float | None = Field(default=None, gt=0, le=1)


class TransientNumerics(StrictModel):
    formulation: Literal[
        "first_order_implicit", "second_order_implicit", "bounded_second_order_implicit"
    ]
    time_step: Quantity | None = None
    max_iterations_per_step: int = Field(default=20, ge=1)
    max_courant: float | None = Field(default=None, gt=0)

    @field_validator("time_step")
    @classmethod
    def time_unit(cls, value: Quantity | None) -> Quantity | None:
        if value is None:
            return value
        if value.value <= 0:
            raise ValueError("time step must be positive")
        return require_unit(value, {"s", "ms", "us"}, "time step")


class NumericsProfile(StrictModel):
    extends: Identifier | None = None
    pressure_velocity_coupling: Literal["simple", "simplec", "piso", "coupled"] | None = None
    gradient: (
        Literal[
            "green_gauss_cell_based",
            "green_gauss_node_based",
            "least_squares_cell_based",
        ]
        | None
    ) = None
    pressure: PressureScheme | None = None
    equations: dict[Identifier, EquationNumerics] = Field(default_factory=dict)
    transient: TransientNumerics | None = None
    expert_controls: dict[str, float | int | bool | str] = Field(default_factory=dict)


class NumericsDocument(VersionedDocument):
    default_profile: Identifier
    profiles: dict[Identifier, NumericsProfile]

    @model_validator(mode="after")
    def valid_profile_graph(self) -> NumericsDocument:
        if self.default_profile not in self.profiles:
            raise ValueError(f"default numerics profile {self.default_profile!r} does not exist")

        for name, profile in self.profiles.items():
            if profile.extends is not None and profile.extends not in self.profiles:
                raise ValueError(
                    f"numerics profile {name!r} extends unknown profile {profile.extends!r}"
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visiting:
                raise ValueError(f"cycle in numerics profile inheritance at {name!r}")
            if name in visited:
                return
            visiting.add(name)
            parent = self.profiles[name].extends
            if parent is not None:
                visit(parent)
            visiting.remove(name)
            visited.add(name)

        for profile_name in self.profiles:
            visit(profile_name)
        return self
