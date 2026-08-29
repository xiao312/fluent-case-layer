"""Typed execution-stage DAG and artifact contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import (
    Identifier,
    Quantity,
    RetryPolicy,
    StageCondition,
    StageInput,
    StageOutput,
    StageOutputInput,
    StrictModel,
    TuiEscape,
    VersionedDocument,
    ensure_unique_ids,
    require_unit,
)


class StageBase(StrictModel):
    id: Identifier
    requires: list[Identifier] = Field(default_factory=list)
    platform: Identifier | None = None
    inputs: list[StageInput] = Field(default_factory=list)
    outputs: list[StageOutput] = Field(default_factory=list)
    preconditions: list[StageCondition] = Field(default_factory=list)
    postconditions: list[StageCondition] = Field(default_factory=list)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout: Quantity | None = None

    @field_validator("requires")
    @classmethod
    def unique_requirements(cls, requires: list[str]) -> list[str]:
        if len(requires) != len(set(requires)):
            raise ValueError("stage requirements must be unique")
        return requires

    @field_validator("timeout")
    @classmethod
    def timeout_is_time(cls, timeout: Quantity | None) -> Quantity | None:
        if timeout is None:
            return timeout
        if timeout.value <= 0:
            raise ValueError("stage timeout must be positive")
        return require_unit(timeout, {"s", "min", "h"}, "stage timeout")

    @model_validator(mode="after")
    def unique_ports(self) -> StageBase:
        input_names = [stage_input.name for stage_input in self.inputs]
        if len(input_names) != len(set(input_names)):
            raise ValueError(f"stage {self.id!r} has duplicate input names")
        ensure_unique_ids(self.outputs, f"output in stage {self.id}")
        return self


class LoadAssetStage(StageBase):
    type: Literal["load_asset"]
    asset: Identifier
    load_as: Literal["mesh", "case", "case_data", "chemistry_table", "profile"]
    data_asset: Identifier | None = None

    @model_validator(mode="after")
    def paired_case_data(self) -> LoadAssetStage:
        if self.load_as == "case_data" and self.data_asset is None:
            raise ValueError("load_as=case_data requires data_asset")
        if self.load_as != "case_data" and self.data_asset is not None:
            raise ValueError("data_asset is only valid for load_as=case_data")
        return self


class ReconcileStage(StageBase):
    type: Literal["reconcile"]
    sections: Annotated[
        list[
            Literal[
                "physics",
                "materials",
                "chemistry",
                "fields",
                "boundary_conditions",
                "numerics",
            ]
        ],
        Field(min_length=1),
    ]
    numerics_profile: Identifier | None = None

    @field_validator("sections")
    @classmethod
    def unique_sections(cls, sections: list[str]) -> list[str]:
        if len(sections) != len(set(sections)):
            raise ValueError("reconcile sections must be unique")
        return sections


class InitializeStage(StageBase):
    type: Literal["initialize"]
    actions: Annotated[list[Identifier], Field(min_length=1)]


class IterateStage(StageBase):
    type: Literal["iterate"]
    iterations: int = Field(ge=1)
    report_every: int = Field(default=10, ge=1)


class AdvanceTimeStage(StageBase):
    type: Literal["advance_time"]
    time_steps: int = Field(ge=1)
    time_step: Quantity | None = None
    max_iterations_per_step: int | None = Field(default=None, ge=1)

    @field_validator("time_step")
    @classmethod
    def time_step_unit(cls, time_step: Quantity | None) -> Quantity | None:
        if time_step is None:
            return time_step
        if time_step.value <= 0:
            raise ValueError("time step must be positive")
        return require_unit(time_step, {"s", "ms", "us"}, "time step")


class SampleStage(StageBase):
    type: Literal["sample"]
    monitors: Annotated[list[Identifier], Field(min_length=1)]


class GateStage(StageBase):
    type: Literal["gate"]
    gates: Annotated[list[Identifier], Field(min_length=1)]


class NoPromotion(StrictModel):
    type: Literal["none"]


class GatePromotion(StrictModel):
    type: Literal["when_gates_pass"]
    gates: Annotated[list[Identifier], Field(min_length=1)]
    role: Literal["candidate", "trusted", "production_restart"]


PromotionPolicy = Annotated[NoPromotion | GatePromotion, Field(discriminator="type")]


class CheckpointStage(StageBase):
    type: Literal["checkpoint"]
    label: Identifier
    write_case: bool = True
    write_data: bool = True
    promotion: PromotionPolicy = Field(default_factory=lambda: NoPromotion(type="none"))

    @model_validator(mode="after")
    def writes_something(self) -> CheckpointStage:
        if not self.write_case and not self.write_data:
            raise ValueError("checkpoint stage must write case and/or data")
        return self


class TuiStage(StageBase):
    type: Literal["tui"]
    escape: TuiEscape


StageSpec = Annotated[
    LoadAssetStage
    | ReconcileStage
    | InitializeStage
    | IterateStage
    | AdvanceTimeStage
    | SampleStage
    | GateStage
    | CheckpointStage
    | TuiStage,
    Field(discriminator="type"),
]


class ControlDocument(VersionedDocument):
    default_platform: Identifier
    stages: Annotated[list[StageSpec], Field(min_length=1)]

    @model_validator(mode="after")
    def valid_stage_dag(self) -> ControlDocument:
        ensure_unique_ids(self.stages, "stage")
        stage_by_id = {stage.id: stage for stage in self.stages}

        for stage in self.stages:
            if stage.id in stage.requires:
                raise ValueError(f"stage {stage.id!r} cannot require itself")
            missing = sorted(set(stage.requires) - stage_by_id.keys())
            if missing:
                raise ValueError(
                    f"stage {stage.id!r} requires unknown stages: {', '.join(missing)}"
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(stage_id: str) -> None:
            if stage_id in visiting:
                raise ValueError(f"cycle in stage graph at {stage_id!r}")
            if stage_id in visited:
                return
            visiting.add(stage_id)
            for dependency in stage_by_id[stage_id].requires:
                visit(dependency)
            visiting.remove(stage_id)
            visited.add(stage_id)

        for stage_id in stage_by_id:
            visit(stage_id)

        def ancestors(stage_id: str) -> set[str]:
            result: set[str] = set()
            pending = list(stage_by_id[stage_id].requires)
            while pending:
                dependency = pending.pop()
                if dependency not in result:
                    result.add(dependency)
                    pending.extend(stage_by_id[dependency].requires)
            return result

        for stage in self.stages:
            available_ancestors = ancestors(stage.id)
            for stage_input in stage.inputs:
                if not isinstance(stage_input, StageOutputInput):
                    continue
                if stage_input.stage not in available_ancestors:
                    raise ValueError(
                        f"stage {stage.id!r} consumes output from {stage_input.stage!r}, "
                        "which is not an ancestor"
                    )
                source_outputs = {output.id for output in stage_by_id[stage_input.stage].outputs}
                if stage_input.output not in source_outputs:
                    raise ValueError(
                        f"stage {stage.id!r} consumes unknown output "
                        f"{stage_input.stage}.{stage_input.output}"
                    )
        return self
