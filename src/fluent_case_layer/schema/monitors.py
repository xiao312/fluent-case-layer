"""Monitor definitions and separately classified acceptance gates."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .common import (
    Identifier,
    Quantity,
    StrictModel,
    VersionedDocument,
    ZoneSelector,
    ensure_unique_ids,
)


class ResidualMonitor(StrictModel):
    id: Identifier
    type: Literal["residual"]
    thresholds: dict[Identifier, float]
    check_every: int = Field(default=1, ge=1)

    @field_validator("thresholds")
    @classmethod
    def positive_thresholds(cls, thresholds: dict[str, float]) -> dict[str, float]:
        if not thresholds:
            raise ValueError("residual monitor requires at least one equation threshold")
        if any(not math.isfinite(value) or value <= 0 for value in thresholds.values()):
            raise ValueError("residual thresholds must be finite and positive")
        return thresholds


class SurfaceReportMonitor(StrictModel):
    id: Identifier
    type: Literal["surface_report"]
    operation: Literal[
        "area_weighted_average",
        "mass_weighted_average",
        "integral",
        "mass_flow_rate",
        "minimum",
        "maximum",
    ]
    field: str
    zones: ZoneSelector
    unit: str
    check_every: int = Field(default=10, ge=1)


class VolumeReportMonitor(StrictModel):
    id: Identifier
    type: Literal["volume_report"]
    operation: Literal[
        "volume_weighted_average", "mass_weighted_average", "integral", "minimum", "maximum"
    ]
    field: str
    zones: ZoneSelector
    unit: str
    check_every: int = Field(default=10, ge=1)


class MassBalanceMonitor(StrictModel):
    id: Identifier
    type: Literal["mass_balance"]
    inlets: ZoneSelector
    outlets: ZoneSelector
    include_discrete_phase: bool = False
    check_every: int = Field(default=10, ge=1)


class ExpressionMonitor(StrictModel):
    id: Identifier
    type: Literal["expression"]
    expression: str
    unit: str
    check_every: int = Field(default=10, ge=1)


MonitorSpec = Annotated[
    ResidualMonitor
    | SurfaceReportMonitor
    | VolumeReportMonitor
    | MassBalanceMonitor
    | ExpressionMonitor,
    Field(discriminator="type"),
]


GateCategory = Literal["orchestration", "numerical", "scientific"]
GateSeverity = Literal["advisory", "required"]


class ThresholdGate(StrictModel):
    id: Identifier
    type: Literal["threshold"]
    category: GateCategory
    severity: GateSeverity = "required"
    monitor: Identifier
    operator: Literal["lt", "le", "gt", "ge", "eq"]
    limit: Quantity


class RangeGate(StrictModel):
    id: Identifier
    type: Literal["range"]
    category: GateCategory
    severity: GateSeverity = "required"
    monitor: Identifier
    minimum: Quantity | None = None
    maximum: Quantity | None = None

    @model_validator(mode="after")
    def valid_range(self) -> RangeGate:
        if self.minimum is None and self.maximum is None:
            raise ValueError("range gate requires minimum and/or maximum")
        if self.minimum is not None and self.maximum is not None:
            if self.minimum.unit != self.maximum.unit:
                raise ValueError("range gate bounds must use the same unit")
            if self.minimum.value > self.maximum.value:
                raise ValueError("range gate minimum cannot exceed maximum")
        return self


class SteadyWindowGate(StrictModel):
    id: Identifier
    type: Literal["steady_window"]
    category: GateCategory = "numerical"
    severity: GateSeverity = "required"
    monitor: Identifier
    samples: int = Field(ge=3)
    relative_span: float = Field(gt=0, le=1)


class ArtifactGate(StrictModel):
    id: Identifier
    type: Literal["artifact_exists"]
    category: GateCategory = "orchestration"
    severity: GateSeverity = "required"
    stage: Identifier
    output: Identifier


GateSpec = Annotated[
    ThresholdGate | RangeGate | SteadyWindowGate | ArtifactGate,
    Field(discriminator="type"),
]


class MonitorsDocument(VersionedDocument):
    monitors: list[MonitorSpec]
    gates: list[GateSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_monitor_references(self) -> MonitorsDocument:
        ensure_unique_ids(self.monitors, "monitor")
        ensure_unique_ids(self.gates, "gate")
        monitor_ids = {monitor.id for monitor in self.monitors}
        referenced = {
            gate.monitor
            for gate in self.gates
            if isinstance(gate, (ThresholdGate, RangeGate, SteadyWindowGate))
        }
        missing = sorted(referenced - monitor_ids)
        if missing:
            raise ValueError(f"gates reference unknown monitors: {', '.join(missing)}")
        return self
