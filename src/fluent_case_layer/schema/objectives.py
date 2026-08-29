"""Engineer-authored objectives that guide investigation without acting as gates."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import Identifier, Quantity, StrictModel, VersionedDocument, ensure_unique_ids


class ObjectiveRevision(StrictModel):
    """Identity and authorship of one objective-document revision."""

    id: Identifier
    sequence: int = Field(ge=1)
    recorded_at: datetime
    recorded_by: Annotated[str, Field(min_length=1)]
    change_summary: str | None = None
    supersedes: Identifier | None = None

    @field_validator("recorded_at")
    @classmethod
    def timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone")
        return value

    @model_validator(mode="after")
    def not_self_superseding(self) -> ObjectiveRevision:
        if self.supersedes == self.id:
            raise ValueError("an objective revision cannot supersede itself")
        return self


class EngineerStatementProvenance(StrictModel):
    type: Literal["engineer_statement"]
    author: Annotated[str, Field(min_length=1)]
    role: str | None = None
    organization: str | None = None
    context: str | None = None


class SourceAssetProvenance(StrictModel):
    type: Literal["source_asset"]
    asset: Identifier
    locator: str | None = None
    recorded_by: str | None = None
    interpretation: str | None = None


ObjectiveProvenance = Annotated[
    EngineerStatementProvenance | SourceAssetProvenance,
    Field(discriminator="type"),
]


ObjectivePriority = Literal["primary", "secondary", "exploratory"]


class ObserveAspect(StrictModel):
    id: Identifier
    type: Literal["observe"]
    description: Annotated[str, Field(min_length=1)]
    monitors: Annotated[list[Identifier], Field(min_length=1)]
    priority: ObjectivePriority = "secondary"

    @field_validator("monitors")
    @classmethod
    def unique_monitors(cls, monitors: list[str]) -> list[str]:
        if len(monitors) != len(set(monitors)):
            raise ValueError("objective aspect monitors must be unique")
        return monitors


class DirectionalAspect(StrictModel):
    id: Identifier
    type: Literal["directional"]
    description: Annotated[str, Field(min_length=1)]
    monitor: Identifier
    direction: Literal["minimize", "maximize", "increase", "decrease", "hold"]
    priority: ObjectivePriority = "secondary"


class ExperimentalValueReference(StrictModel):
    type: Literal["experimental_value"]
    label: Annotated[str, Field(min_length=1)]
    value: Quantity
    uncertainty: Quantity | None = None
    source_note: str | None = None

    @model_validator(mode="after")
    def compatible_uncertainty(self) -> ExperimentalValueReference:
        if self.uncertainty is None:
            return self
        if self.uncertainty.value < 0:
            raise ValueError("experimental uncertainty cannot be negative")
        if self.uncertainty.unit != self.value.unit:
            raise ValueError("experimental value and uncertainty must use the same unit")
        return self


class ReferenceAsset(StrictModel):
    type: Literal["reference_asset"]
    asset: Identifier
    role: Literal["experiment", "simulation", "analytical"]
    locator: str | None = None
    observable: str | None = None


ObjectiveReference = Annotated[
    ExperimentalValueReference | ReferenceAsset,
    Field(discriminator="type"),
]


class ComparisonIntent(StrictModel):
    """A non-enforcing hint for how an engineer intends to inspect agreement."""

    method: Literal[
        "absolute_difference",
        "relative_difference",
        "normalized_rmse",
        "profile_shape",
        "qualitative",
    ]
    alignment: str | None = None
    notes: str | None = None


class MatchReferenceAspect(StrictModel):
    id: Identifier
    type: Literal["match_reference"]
    description: Annotated[str, Field(min_length=1)]
    monitor: Identifier
    reference: ObjectiveReference
    comparison: ComparisonIntent | None = None
    priority: ObjectivePriority = "primary"


class InvestigateAspect(StrictModel):
    id: Identifier
    type: Literal["investigate"]
    description: Annotated[str, Field(min_length=1)]
    questions: Annotated[list[str], Field(min_length=1)]
    monitors: list[Identifier] = Field(default_factory=list)
    priority: ObjectivePriority = "exploratory"

    @field_validator("questions")
    @classmethod
    def nonempty_questions(cls, questions: list[str]) -> list[str]:
        if any(not question.strip() for question in questions):
            raise ValueError("investigation questions cannot be blank")
        return questions

    @field_validator("monitors")
    @classmethod
    def unique_monitors(cls, monitors: list[str]) -> list[str]:
        if len(monitors) != len(set(monitors)):
            raise ValueError("objective aspect monitors must be unique")
        return monitors


ObjectiveAspect = Annotated[
    ObserveAspect | DirectionalAspect | MatchReferenceAspect | InvestigateAspect,
    Field(discriminator="type"),
]


class EngineeringObjectiveDocument(VersionedDocument):
    """Human intent kept independent from optional case-local gates."""

    revision: ObjectiveRevision
    provenance: ObjectiveProvenance
    statement: Annotated[str, Field(min_length=1)]
    enforcement: Literal["none"] = "none"
    aspects: list[ObjectiveAspect] = Field(default_factory=list)

    @field_validator("statement")
    @classmethod
    def nonblank_statement(cls, statement: str) -> str:
        if not statement.strip():
            raise ValueError("engineering objective statement cannot be blank")
        return statement

    @model_validator(mode="after")
    def unique_aspects(self) -> EngineeringObjectiveDocument:
        ensure_unique_ids(self.aspects, "objective aspect")
        return self
