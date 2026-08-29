"""Ordered initialization, register, and patch actions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import (
    FieldValue,
    Identifier,
    Quantity,
    StrictModel,
    TuiEscape,
    VectorQuantity,
    VersionedDocument,
    ZoneSelector,
    ensure_unique_ids,
)


class CylinderRegion(StrictModel):
    type: Literal["cylinder"]
    start: VectorQuantity
    end: VectorQuantity
    radius: Quantity

    @model_validator(mode="after")
    def compatible_geometry(self) -> CylinderRegion:
        if self.start.unit != self.end.unit or self.radius.unit != self.start.unit:
            raise ValueError("cylinder start, end, and radius must use the same length unit")
        if self.radius.value <= 0:
            raise ValueError("cylinder radius must be positive")
        return self


class BoxRegion(StrictModel):
    type: Literal["box"]
    minimum: VectorQuantity
    maximum: VectorQuantity

    @model_validator(mode="after")
    def compatible_bounds(self) -> BoxRegion:
        if self.minimum.unit != self.maximum.unit:
            raise ValueError("box bounds must use the same unit")
        if any(
            low >= high for low, high in zip(self.minimum.value, self.maximum.value, strict=True)
        ):
            raise ValueError("each box minimum component must be less than its maximum")
        return self


class ZoneRegion(StrictModel):
    type: Literal["zones"]
    zones: ZoneSelector


RegisterRegion = Annotated[CylinderRegion | BoxRegion | ZoneRegion, Field(discriminator="type")]


class RegisterPatchTarget(StrictModel):
    type: Literal["register"]
    register_name: Identifier = Field(alias="register", serialization_alias="register")


class ZonePatchTarget(StrictModel):
    type: Literal["zones"]
    zones: ZoneSelector


PatchTarget = Annotated[RegisterPatchTarget | ZonePatchTarget, Field(discriminator="type")]


class ReadCheckpointAction(StrictModel):
    id: Identifier
    type: Literal["read_checkpoint"]
    case_asset: Identifier
    data_asset: Identifier | None = None


class HybridInitializationAction(StrictModel):
    id: Identifier
    type: Literal["hybrid"]


class StandardInitializationAction(StrictModel):
    id: Identifier
    type: Literal["standard"]
    reference_zone: ZoneSelector | None = None


class CreateRegisterAction(StrictModel):
    id: Identifier
    type: Literal["create_register"]
    name: Identifier
    region: RegisterRegion


class PatchAction(StrictModel):
    id: Identifier
    type: Literal["patch"]
    target: PatchTarget
    field: str
    value: FieldValue


class TuiInitializationAction(StrictModel):
    id: Identifier
    type: Literal["tui"]
    escape: TuiEscape


InitializationAction = Annotated[
    ReadCheckpointAction
    | HybridInitializationAction
    | StandardInitializationAction
    | CreateRegisterAction
    | PatchAction
    | TuiInitializationAction,
    Field(discriminator="type"),
]


class InitializationDocument(VersionedDocument):
    actions: list[InitializationAction]

    @model_validator(mode="after")
    def valid_sequence(self) -> InitializationDocument:
        ensure_unique_ids(self.actions, "initialization action")
        registers: set[str] = set()
        for action in self.actions:
            if isinstance(action, CreateRegisterAction):
                if action.name in registers:
                    raise ValueError(f"register {action.name!r} is created more than once")
                registers.add(action.name)
            elif isinstance(action, PatchAction) and isinstance(action.target, RegisterPatchTarget):
                if action.target.register_name not in registers:
                    raise ValueError(
                        f"patch {action.id!r} references register {action.target.register_name!r} "
                        "before it is created"
                    )
        return self
