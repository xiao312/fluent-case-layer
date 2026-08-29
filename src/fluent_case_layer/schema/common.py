"""Shared, solver-independent value objects for case documents."""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=96,
        pattern=r"^[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*$",
    ),
]
EnvironmentVariable = Annotated[
    str,
    Field(pattern=r"^[A-Z][A-Z0-9_]*$", min_length=2, max_length=128),
]
JsonScalar: TypeAlias = str | int | float | bool | None


class StrictModel(BaseModel):
    """Base model used by every user-authored document."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
        str_strip_whitespace=True,
    )


class VersionedDocument(StrictModel):
    """Version marker shared by the split YAML documents."""

    schema_version: Literal["1.0"] = "1.0"


class Quantity(StrictModel):
    """A finite scalar whose unit is always explicit.

    Unit conversion deliberately belongs to the compiler.  The schema keeps
    the authored value and unit intact so plans and evidence remain auditable.
    """

    value: float
    unit: Annotated[str, Field(min_length=1, max_length=64)]

    @field_validator("value")
    @classmethod
    def finite_value(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("quantity value must be finite")
        return value

    @field_validator("unit")
    @classmethod
    def valid_unit(cls, unit: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9%°µμ_./*^() -]+", unit):
            raise ValueError("unit contains unsupported characters")
        return unit


class VectorQuantity(StrictModel):
    """A three-component finite vector with one shared unit."""

    value: tuple[float, float, float]
    unit: Annotated[str, Field(min_length=1, max_length=64)]

    @field_validator("value")
    @classmethod
    def finite_vector(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        if not all(math.isfinite(component) for component in value):
            raise ValueError("vector components must be finite")
        return value

    @field_validator("unit")
    @classmethod
    def valid_unit(cls, unit: str) -> str:
        return Quantity(value=0.0, unit=unit).unit


def require_unit(quantity: Quantity, allowed: set[str], label: str) -> Quantity:
    """Validate a quantity against the units accepted by one semantic field."""

    if quantity.unit not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{label} must use one of: {choices}")
    return quantity


class Cardinality(StrictModel):
    """Expected number of zones resolved by a selector."""

    exactly: int | None = Field(default=None, ge=0)
    at_least: int | None = Field(default=None, ge=0)
    at_most: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_bounds(self) -> Cardinality:
        if self.exactly is None and self.at_least is None and self.at_most is None:
            raise ValueError("cardinality requires exactly, at_least, and/or at_most")
        if self.exactly is not None and (self.at_least is not None or self.at_most is not None):
            raise ValueError("exactly cannot be combined with at_least or at_most")
        if self.at_least is not None and self.at_most is not None and self.at_least > self.at_most:
            raise ValueError("at_least cannot exceed at_most")
        return self


class ZoneNamesSelector(StrictModel):
    type: Literal["names"]
    names: Annotated[list[str], Field(min_length=1)]
    cardinality: Cardinality = Field(default_factory=lambda: Cardinality(at_least=1))

    @field_validator("names")
    @classmethod
    def unique_names(cls, names: list[str]) -> list[str]:
        if len(names) != len(set(names)):
            raise ValueError("zone names must be unique")
        return names


class ZonePatternSelector(StrictModel):
    type: Literal["pattern"]
    pattern: Annotated[str, Field(min_length=1)]
    cardinality: Cardinality = Field(default_factory=lambda: Cardinality(at_least=1))

    @field_validator("pattern")
    @classmethod
    def compilable_pattern(cls, pattern: str) -> str:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid zone regex: {exc}") from exc
        return pattern


class ZoneTypeSelector(StrictModel):
    type: Literal["zone_type"]
    zone_type: Literal[
        "fluid",
        "solid",
        "mass-flow-inlet",
        "velocity-inlet",
        "pressure-outlet",
        "wall",
        "symmetry",
        "axis",
        "interior",
    ]
    cardinality: Cardinality = Field(default_factory=lambda: Cardinality(at_least=1))


class ZoneIdsSelector(StrictModel):
    type: Literal["ids"]
    ids: Annotated[list[int], Field(min_length=1)]
    cardinality: Cardinality = Field(default_factory=lambda: Cardinality(at_least=1))

    @field_validator("ids")
    @classmethod
    def valid_ids(cls, ids: list[int]) -> list[int]:
        if any(zone_id < 0 for zone_id in ids):
            raise ValueError("zone ids must be non-negative")
        if len(ids) != len(set(ids)):
            raise ValueError("zone ids must be unique")
        return ids


ZoneSelector = Annotated[
    ZoneNamesSelector | ZonePatternSelector | ZoneTypeSelector | ZoneIdsSelector,
    Field(discriminator="type"),
]


class TuiEscape(StrictModel):
    """An explicit, reviewable escape from the PyFluent settings API."""

    reason: Annotated[str, Field(min_length=12)]
    fluent_version: Annotated[str, Field(min_length=1)]
    command: Annotated[str, Field(min_length=1)]
    expected_postcondition: Annotated[str, Field(min_length=8)]


class UniformScalarValue(StrictModel):
    type: Literal["uniform_scalar"]
    value: Quantity


class UniformVectorValue(StrictModel):
    type: Literal["uniform_vector"]
    value: VectorQuantity


class ProfileValue(StrictModel):
    type: Literal["profile"]
    asset: Identifier
    field: Annotated[str, Field(min_length=1)]
    scale: float = 1.0


class ExpressionValue(StrictModel):
    type: Literal["expression"]
    expression: Annotated[str, Field(min_length=1)]
    unit: Annotated[str, Field(min_length=1)]


FieldValue = Annotated[
    UniformScalarValue | UniformVectorValue | ProfileValue | ExpressionValue,
    Field(discriminator="type"),
]


class AssetInput(StrictModel):
    type: Literal["asset"]
    name: Identifier
    asset: Identifier


class StageOutputInput(StrictModel):
    type: Literal["stage_output"]
    name: Identifier
    stage: Identifier
    output: Identifier


class LiteralInput(StrictModel):
    type: Literal["literal"]
    name: Identifier
    value: JsonScalar
    unit: str | None = None


StageInput = Annotated[AssetInput | StageOutputInput | LiteralInput, Field(discriminator="type")]


class StageOutput(StrictModel):
    id: Identifier
    kind: Literal[
        "case", "data", "checkpoint", "report", "metrics", "log", "field_data", "image", "manifest"
    ]
    path_template: Annotated[str, Field(min_length=1)]
    required: bool = True
    sha256: bool = True

    @field_validator("path_template")
    @classmethod
    def relative_output_path(cls, path: str) -> str:
        if path.startswith(("/", "~")) or ".." in path.split("/"):
            raise ValueError("stage output paths must be workspace-relative")
        return path


class AssetAvailableCondition(StrictModel):
    type: Literal["asset_available"]
    asset: Identifier


class StateCondition(StrictModel):
    type: Literal["state"]
    path: Annotated[str, Field(min_length=1)]
    operator: Literal["exists", "equals", "not_equals"] = "exists"
    expected: JsonScalar = None

    @model_validator(mode="after")
    def expected_for_comparison(self) -> StateCondition:
        if self.operator != "exists" and self.expected is None:
            raise ValueError("state comparisons require expected")
        return self


class MetricCondition(StrictModel):
    type: Literal["metric"]
    monitor: Identifier
    operator: Literal["lt", "le", "gt", "ge", "eq"]
    limit: Quantity


StageCondition = Annotated[
    AssetAvailableCondition | StateCondition | MetricCondition,
    Field(discriminator="type"),
]


class RetryPolicy(StrictModel):
    max_attempts: int = Field(default=1, ge=1, le=10)
    backoff: Quantity = Field(default_factory=lambda: Quantity(value=0, unit="s"))
    retry_on: list[Literal["launcher_error", "api_error", "precondition", "numerical_health"]] = (
        Field(default_factory=lambda: ["launcher_error", "api_error"])
    )

    @field_validator("retry_on")
    @classmethod
    def unique_retry_reasons(cls, reasons: list[str]) -> list[str]:
        if len(reasons) != len(set(reasons)):
            raise ValueError("retry_on reasons must be unique")
        return reasons

    @field_validator("backoff")
    @classmethod
    def backoff_is_time(cls, value: Quantity) -> Quantity:
        if value.value < 0:
            raise ValueError("retry backoff cannot be negative")
        return require_unit(value, {"ms", "s", "min"}, "retry backoff")


def ensure_unique_ids(items: list[Any], label: str) -> None:
    ids = [item.id for item in items]
    if len(ids) != len(set(ids)):
        duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
        raise ValueError(f"duplicate {label} ids: {', '.join(duplicates)}")
