"""Typed semantic plan and adapter result models.

These models intentionally use only the Python standard library.  Case-schema
models may be Pydantic models, mappings, or another typed representation; the
driver consumes their JSON-compatible projection at the compiler boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .util import stable_hash

JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class ActionKind(StrEnum):
    """Solver-aware operations understood by execution adapters."""

    RESOLVE_ASSETS = "resolve_assets"
    LOAD_ASSET = "load_asset"
    LAUNCH_SOLVER = "launch_solver"
    READ_MESH = "read_mesh"
    READ_CHECKPOINT = "read_checkpoint"
    RECONCILE_SETTINGS = "reconcile_settings"
    CREATE_REGISTER = "create_register"
    INITIALIZE = "initialize"
    PATCH = "patch"
    ITERATE = "iterate"
    ADVANCE_TIME = "advance_time"
    SAMPLE = "sample"
    GATE = "gate"
    WRITE_CHECKPOINT = "write_checkpoint"
    PROMOTE_CHECKPOINT = "promote_checkpoint"
    SNAPSHOT = "snapshot"
    TUI = "tui"


class ConditionOperator(StrEnum):
    EXISTS = "exists"
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    IN = "in"


@dataclass(frozen=True, slots=True)
class Condition:
    """An assertion over a dotted path in an observed state mapping."""

    path: str
    operator: ConditionOperator = ConditionOperator.EQUALS
    expected: JsonValue = None
    message: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> Condition:
        condition_type = str(value.get("type", "state"))
        operator_aliases = {
            "lt": "less_than",
            "le": "less_than_or_equal",
            "gt": "greater_than",
            "ge": "greater_than_or_equal",
            "eq": "equals",
        }
        if condition_type == "metric":
            limit = value.get("limit", {})
            expected = limit.get("value") if isinstance(limit, Mapping) else limit
            return cls(
                path=f"metrics.{value['monitor']}",
                operator=ConditionOperator(
                    operator_aliases.get(str(value.get("operator")), str(value.get("operator")))
                ),
                expected=expected,
                message=str(value["message"]) if value.get("message") is not None else None,
            )
        if condition_type == "asset_available":
            return cls(
                path=f"assets.{value['asset']}.available",
                operator=ConditionOperator.EQUALS,
                expected=True,
                message=str(value["message"]) if value.get("message") is not None else None,
            )
        return cls(
            path=str(value["path"]),
            operator=ConditionOperator(
                operator_aliases.get(
                    str(value.get("operator", "equals")), str(value.get("operator", "equals"))
                )
            ),
            expected=value.get("expected"),
            message=str(value["message"]) if value.get("message") is not None else None,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {
            "path": self.path,
            "operator": self.operator.value,
            "expected": self.expected,
        }
        if self.message is not None:
            result["message"] = self.message
        return result


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Deterministic retry bounds for one action."""

    max_attempts: int = 1
    backoff_seconds: float = 0.0

    @classmethod
    def from_value(cls, value: Mapping[str, Any] | int | None) -> RetryPolicy:
        if value is None:
            return cls()
        if isinstance(value, int):
            return cls(max_attempts=value + 1)
        attempts = int(value.get("max_attempts", value.get("attempts", 1)))
        raw_backoff = value.get("backoff_seconds", value.get("backoff", 0.0))
        if isinstance(raw_backoff, Mapping):
            amount = float(raw_backoff.get("value", 0.0))
            unit = str(raw_backoff.get("unit", "s"))
            factor = {"ms": 0.001, "s": 1.0, "min": 60.0}.get(unit)
            if factor is None:
                raise ValueError(f"unsupported retry backoff unit: {unit}")
            backoff = amount * factor
        else:
            backoff = float(raw_backoff)
        if attempts < 1:
            raise ValueError("retry.max_attempts must be at least 1")
        if backoff < 0:
            raise ValueError("retry.backoff_seconds cannot be negative")
        return cls(max_attempts=attempts, backoff_seconds=backoff)

    def to_dict(self) -> dict[str, JsonValue]:
        return {"max_attempts": self.max_attempts, "backoff_seconds": self.backoff_seconds}


@dataclass(frozen=True, slots=True)
class GateSpec:
    """Scientific or numerical assertions evaluated after an action."""

    conditions: tuple[Condition, ...] = ()
    category: str = "orchestration"
    required: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> GateSpec | None:
        if value is None:
            return None
        raw_conditions = value.get("conditions", value.get("all", ()))
        return cls(
            conditions=tuple(Condition.from_mapping(item) for item in raw_conditions),
            category=str(value.get("category", "orchestration")),
            required=bool(value.get("required", True)),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "conditions": [item.to_dict() for item in self.conditions],
            "category": self.category,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class CheckpointSpec:
    """Checkpoint output and optional promotion contract."""

    name: str
    role: str = "recovery"
    promote_when_gates_pass: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | str | None) -> CheckpointSpec | None:
        if value is None:
            return None
        if isinstance(value, str):
            return cls(name=value)
        return cls(
            name=str(value["name"]),
            role=str(value.get("role", "recovery")),
            promote_when_gates_pass=bool(value.get("promote_when_gates_pass", False)),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "name": self.name,
            "role": self.role,
            "promote_when_gates_pass": self.promote_when_gates_pass,
        }


@dataclass(frozen=True, slots=True)
class SemanticAction:
    """One typed, auditable node in the execution DAG."""

    id: str
    kind: ActionKind
    depends_on: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)
    preconditions: tuple[Condition, ...] = ()
    postconditions: tuple[Condition, ...] = ()
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    gate: GateSpec | None = None
    checkpoint: CheckpointSpec | None = None
    description: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SemanticAction:
        identifier = str(value.get("id", value.get("name", ""))).strip()
        if not identifier:
            raise ValueError("stage.id is required")
        raw_kind = value.get("action", value.get("kind", value.get("type")))
        if raw_kind is None:
            raise ValueError(f"stage {identifier!r} is missing action/kind")
        kind_aliases = {
            "reconcile": ActionKind.RECONCILE_SETTINGS.value,
            "checkpoint": ActionKind.WRITE_CHECKPOINT.value,
        }
        normalized_kind = kind_aliases.get(str(raw_kind), str(raw_kind))
        common_fields = {
            "id",
            "name",
            "action",
            "kind",
            "type",
            "depends_on",
            "requires",
            "parameters",
            "with",
            "preconditions",
            "postconditions",
            "retry",
            "retries",
            "gate",
            "checkpoint",
            "description",
            "enabled",
        }
        parameters = value.get("parameters", value.get("with"))
        if parameters is None:
            parameters = {key: item for key, item in value.items() if key not in common_fields}
        if not isinstance(parameters, Mapping):
            raise TypeError(f"stage {identifier!r} parameters must be a mapping")
        parameters = dict(parameters)
        if normalized_kind == ActionKind.TUI.value and isinstance(
            parameters.get("escape"), Mapping
        ):
            escape = dict(parameters.pop("escape"))
            parameters = {**escape, **parameters}
        checkpoint = CheckpointSpec.from_mapping(value.get("checkpoint"))
        if normalized_kind == ActionKind.WRITE_CHECKPOINT.value and checkpoint is None:
            promotion = parameters.get("promotion", {})
            promoted = isinstance(promotion, Mapping) and promotion.get("type") == "when_gates_pass"
            role = (
                str(promotion.get("role", "recovery"))
                if isinstance(promotion, Mapping)
                else "recovery"
            )
            checkpoint = CheckpointSpec(
                name=str(parameters.get("label", identifier)),
                role=role,
                promote_when_gates_pass=promoted,
            )
        action = cls(
            id=identifier,
            kind=ActionKind(normalized_kind),
            depends_on=tuple(
                str(item) for item in value.get("depends_on", value.get("requires", ()))
            ),
            parameters=parameters,
            preconditions=tuple(
                Condition.from_mapping(item) for item in value.get("preconditions", ())
            ),
            postconditions=tuple(
                Condition.from_mapping(item) for item in value.get("postconditions", ())
            ),
            retry=RetryPolicy.from_value(value.get("retry", value.get("retries"))),
            gate=GateSpec.from_mapping(value.get("gate")),
            checkpoint=checkpoint,
            description=str(value["description"]) if value.get("description") else None,
        )
        action.validate_audit_contract()
        return action

    def validate_audit_contract(self) -> None:
        if self.kind is not ActionKind.TUI:
            return
        required = ("command", "reason", "fluent_version", "expected_postcondition")
        missing = [key for key in required if not self.parameters.get(key)]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"TUI stage {self.id!r} is missing audit fields: {joined}")

    def to_dict(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {
            "id": self.id,
            "kind": self.kind.value,
            "depends_on": list(self.depends_on),
            "parameters": dict(self.parameters),
            "preconditions": [item.to_dict() for item in self.preconditions],
            "postconditions": [item.to_dict() for item in self.postconditions],
            "retry": self.retry.to_dict(),
        }
        if self.gate is not None:
            result["gate"] = self.gate.to_dict()
        if self.checkpoint is not None:
            result["checkpoint"] = self.checkpoint.to_dict()
        if self.description is not None:
            result["description"] = self.description
        return result


@dataclass(frozen=True, slots=True)
class CompiledPlan:
    """Canonical execution plan. Its hash excludes no mutable runtime fields."""

    schema_version: str
    case_id: str
    case_digest: str
    actions: tuple[SemanticAction, ...]
    platform: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    plan_hash: str = ""

    def unsigned_dict(self) -> dict[str, JsonValue]:
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "case_digest": self.case_digest,
            "platform": dict(self.platform),
            "metadata": dict(self.metadata),
            "actions": [action.to_dict() for action in self.actions],
        }

    def with_hash(self) -> CompiledPlan:
        digest = stable_hash(self.unsigned_dict())
        return CompiledPlan(
            schema_version=self.schema_version,
            case_id=self.case_id,
            case_digest=self.case_digest,
            actions=self.actions,
            platform=self.platform,
            metadata=self.metadata,
            plan_hash=digest,
        )

    def to_dict(self) -> dict[str, JsonValue]:
        result = self.unsigned_dict()
        result["plan_hash"] = self.plan_hash or stable_hash(result)
        return result


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """A content-addressed artifact emitted by an adapter action."""

    uri: str
    role: str
    sha256: str | None = None
    size_bytes: int | None = None
    media_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_path(cls, path: Path, role: str, sha256: str, size_bytes: int) -> ArtifactRecord:
        return cls(uri=path.resolve().as_uri(), role=role, sha256=sha256, size_bytes=size_bytes)

    def to_dict(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {"uri": self.uri, "role": self.role}
        if self.sha256 is not None:
            result["sha256"] = self.sha256
        if self.size_bytes is not None:
            result["size_bytes"] = self.size_bytes
        if self.media_type is not None:
            result["media_type"] = self.media_type
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True, slots=True)
class ActionResult:
    """Normalized result returned by every execution adapter."""

    details: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)
    artifacts: tuple[ArtifactRecord, ...] = ()
    checkpoints: tuple[ArtifactRecord, ...] = ()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "details": dict(self.details),
            "metrics": dict(self.metrics),
            "artifacts": [item.to_dict() for item in self.artifacts],
            "checkpoints": [item.to_dict() for item in self.checkpoints],
        }
