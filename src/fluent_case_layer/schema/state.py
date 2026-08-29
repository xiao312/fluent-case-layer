"""Partial Fluent-state ownership over fresh cases or locked checkpoints."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, TypeAlias

from pydantic import Field, field_validator, model_validator

from .common import (
    Identifier,
    JsonScalar,
    Quantity,
    StrictModel,
    VectorQuantity,
    VersionedDocument,
)

DottedStatePath = Annotated[
    str,
    Field(
        min_length=1,
        max_length=512,
        pattern=r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$",
    ),
]
DocumentPath = Literal[
    "constant/physics.yaml",
    "constant/materials.yaml",
    "constant/chemistry.yaml",
    "0/fields.yaml",
    "0/boundary-conditions.yaml",
    "system/numerics.yaml",
    "system/initialization.yaml",
    "system/monitors.yaml",
    "system/control.yaml",
]


class LockedAssetReference(StrictModel):
    """An asset id plus the exact digest expected by this state policy."""

    asset: Identifier
    sha256: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{64}$")]

    @field_validator("sha256")
    @classmethod
    def normalize_hash(cls, value: str) -> str:
        return value.lower()


class CheckpointBaseline(StrictModel):
    case: LockedAssetReference
    data: LockedAssetReference | None = None
    label: str | None = None
    fluent_version: str | None = None

    @model_validator(mode="after")
    def distinct_assets(self) -> CheckpointBaseline:
        if self.data is not None and self.case.asset == self.data.asset:
            raise ValueError("checkpoint case and data must reference distinct assets")
        return self


class CaseDocumentStateSource(StrictModel):
    type: Literal["case_document"]
    document: DocumentPath
    pointer: Annotated[str, Field(max_length=512)]

    @field_validator("pointer")
    @classmethod
    def valid_json_pointer(cls, pointer: str) -> str:
        if pointer == "":
            return pointer
        if not pointer.startswith("/"):
            raise ValueError("document pointer must be an RFC 6901 JSON pointer beginning with '/'")
        if re.search(r"~(?:[^01]|$)", pointer):
            raise ValueError("document pointer contains an invalid '~' escape")
        return pointer


InlineStateValue: TypeAlias = JsonScalar | Quantity | VectorQuantity


class InlineStateSource(StrictModel):
    type: Literal["inline"]
    value: InlineStateValue


DeclaredStateSource = Annotated[
    CaseDocumentStateSource | InlineStateSource,
    Field(discriminator="type"),
]


class DeclaredStatePath(StrictModel):
    path: DottedStatePath
    source: DeclaredStateSource
    rationale: str | None = None


class ObservedStatePath(StrictModel):
    path: DottedStatePath
    capture: Literal["exact", "summary", "digest"] = "exact"
    purpose: Literal["verification", "diagnostic", "provenance"] = "verification"
    required: bool = True


def resolve_json_pointer(document: object, pointer: str) -> object:
    """Resolve an RFC 6901 pointer, including list indices, or raise ``ValueError``."""

    if pointer == "":
        return document
    current = document
    for encoded_token in pointer[1:].split("/"):
        token = encoded_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise ValueError(f"mapping key {token!r} does not exist")
            current = current[token]
            continue
        if isinstance(current, Sequence) and not isinstance(current, (str, bytes, bytearray)):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise ValueError(f"list token {token!r} is not a canonical non-negative index")
            index = int(token)
            if index >= len(current):
                raise ValueError(f"list index {index} is out of range")
            current = current[index]
            continue
        raise ValueError(f"cannot traverse token {token!r} through a scalar value")
    return current


def _validate_nonoverlapping_paths(
    entries: list[DeclaredStatePath] | list[ObservedStatePath], label: str
) -> None:
    paths = sorted(entry.path for entry in entries)
    for index, path in enumerate(paths):
        if index and path == paths[index - 1]:
            raise ValueError(f"duplicate {label} state path: {path}")
        for candidate in paths[index + 1 :]:
            if candidate.startswith(path + "."):
                raise ValueError(f"overlapping {label} state paths: {path} and {candidate}")


class StateOwnershipDocument(VersionedDocument):
    """Declares only state this layer owns and state it intentionally records.

    In ``checkpoint_overlay`` mode, every undeclared path remains inherited
    from the hash-locked baseline.  In ``full_definition`` mode, undeclared
    paths retain fresh-case or Fluent defaults.  Neither mode uses an exhaustive
    allowlist.
    """

    mode: Literal["full_definition", "checkpoint_overlay"]
    baseline: CheckpointBaseline | None = None
    declared_paths: list[DeclaredStatePath] = Field(default_factory=list)
    observed_paths: list[ObservedStatePath] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_mode_and_paths(self) -> StateOwnershipDocument:
        if self.mode == "checkpoint_overlay" and self.baseline is None:
            raise ValueError("checkpoint_overlay mode requires a hash-locked case baseline")
        if self.mode == "full_definition" and self.baseline is not None:
            raise ValueError("full_definition mode cannot declare a checkpoint baseline")
        _validate_nonoverlapping_paths(self.declared_paths, "declared")
        _validate_nonoverlapping_paths(self.observed_paths, "observed")
        return self
