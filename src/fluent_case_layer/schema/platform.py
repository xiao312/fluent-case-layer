"""Machine-independent local and Slurm platform profiles."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import (
    EnvironmentVariable,
    Identifier,
    Quantity,
    StrictModel,
    VersionedDocument,
    require_unit,
)


class ResourceSpec(StrictModel):
    nodes: int = Field(default=1, ge=1)
    ranks: int = Field(default=1, ge=1)
    tasks_per_node: int | None = Field(default=None, ge=1)
    threads_per_rank: int = Field(default=1, ge=1)
    memory_per_node: Quantity
    accelerators_per_node: int = Field(default=0, ge=0)
    walltime: Quantity
    exclusive: bool = False

    @field_validator("memory_per_node")
    @classmethod
    def memory_unit(cls, value: Quantity) -> Quantity:
        if value.value <= 0:
            raise ValueError("memory_per_node must be positive")
        return require_unit(value, {"MiB", "GiB", "TiB"}, "memory_per_node")

    @field_validator("walltime")
    @classmethod
    def walltime_unit(cls, value: Quantity) -> Quantity:
        if value.value <= 0:
            raise ValueError("walltime must be positive")
        return require_unit(value, {"min", "h"}, "walltime")

    @model_validator(mode="after")
    def feasible_rank_layout(self) -> ResourceSpec:
        if self.tasks_per_node is not None and self.ranks > self.nodes * self.tasks_per_node:
            raise ValueError("ranks exceed nodes * tasks_per_node")
        return self


class FluentRuntime(StrictModel):
    version: str
    mode: Literal["solver", "meshing"] = "solver"
    graphics: Literal["none", "null", "native"] = "none"


class EnvironmentSpec(StrictModel):
    setup_script_variable: EnvironmentVariable
    python_environment_variable: EnvironmentVariable | None = None
    exports: dict[EnvironmentVariable, str] = Field(default_factory=dict)


class SlurmScheduler(StrictModel):
    partition: str
    account_variable: EnvironmentVariable | None = None
    qos: str | None = None
    constraint: str | None = None


class SlurmPlatform(StrictModel):
    id: Identifier
    kind: Literal["slurm"]
    enabled: bool = True
    hardware: Literal["cpu", "gpu", "dcu"] = "cpu"
    scheduler: SlurmScheduler
    resources: ResourceSpec
    environment: EnvironmentSpec
    fluent: FluentRuntime
    capabilities: list[
        Literal["settings_api", "tui", "udf_compile", "dpm", "postprocess", "accelerator"]
    ] = Field(default_factory=lambda: ["settings_api", "tui"])
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def accelerator_layout(self) -> SlurmPlatform:
        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("platform capabilities must be unique")
        if self.hardware == "cpu" and self.resources.accelerators_per_node != 0:
            raise ValueError("CPU platforms cannot request accelerators")
        if self.hardware != "cpu" and self.resources.accelerators_per_node == 0:
            raise ValueError("GPU/DCU platforms must request at least one accelerator per node")
        if self.hardware != "cpu" and "accelerator" not in self.capabilities:
            raise ValueError("GPU/DCU platforms must declare the accelerator capability")
        return self


class LocalPlatform(StrictModel):
    id: Identifier
    kind: Literal["local"]
    enabled: bool = True
    resources: ResourceSpec
    environment: EnvironmentSpec | None = None
    fluent: FluentRuntime
    capabilities: list[Literal["settings_api", "tui", "udf_compile", "dpm", "postprocess"]] = Field(
        default_factory=lambda: ["settings_api"]
    )
    notes: list[str] = Field(default_factory=list)

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(cls, capabilities: list[str]) -> list[str]:
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("platform capabilities must be unique")
        return capabilities


PlatformSpec = Annotated[SlurmPlatform | LocalPlatform, Field(discriminator="kind")]


class PlatformDocument(VersionedDocument):
    platform: PlatformSpec
