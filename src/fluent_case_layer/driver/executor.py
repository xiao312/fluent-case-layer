"""Resumable plan executor with snapshots, gates, and evidence manifests."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .adapters.base import ExecutionAdapter
from .errors import DriverError, ExecutionFailedError
from .events import EventLog
from .evidence import ManifestStore, SnapshotStore, write_plan_lock
from .types import (
    ActionKind,
    ActionResult,
    ArtifactRecord,
    CompiledPlan,
    Condition,
    ConditionOperator,
    SemanticAction,
)
from .util import atomic_write_json, dotted_get, file_sha256, stable_hash, to_jsonable


@dataclass(frozen=True, slots=True)
class ExecutionSummary:
    run_id: str
    case_id: str
    plan_hash: str
    run_directory: str
    orchestration_status: str
    numerical_status: str
    scientific_status: str
    completed_actions: tuple[str, ...]
    failed_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "case_id": self.case_id,
            "plan_hash": self.plan_hash,
            "run_directory": self.run_directory,
            "orchestration_status": self.orchestration_status,
            "numerical_status": self.numerical_status,
            "scientific_status": self.scientific_status,
            "completed_actions": list(self.completed_actions),
            "failed_action": self.failed_action,
        }


def evaluate_condition(condition: Condition, observed: Mapping[str, Any]) -> tuple[bool, str]:
    exists, actual = dotted_get(observed, condition.path)
    operator = condition.operator
    passed = False
    if operator is ConditionOperator.EXISTS:
        passed = exists == bool(condition.expected if condition.expected is not None else True)
    elif not exists:
        passed = False
    elif operator is ConditionOperator.EQUALS:
        passed = actual == condition.expected
    elif operator is ConditionOperator.NOT_EQUALS:
        passed = actual != condition.expected
    elif operator is ConditionOperator.LESS_THAN:
        passed = actual < condition.expected
    elif operator is ConditionOperator.LESS_THAN_OR_EQUAL:
        passed = actual <= condition.expected
    elif operator is ConditionOperator.GREATER_THAN:
        passed = actual > condition.expected
    elif operator is ConditionOperator.GREATER_THAN_OR_EQUAL:
        passed = actual >= condition.expected
    elif operator is ConditionOperator.IN:
        passed = actual in condition.expected
    detail = condition.message or (
        f"{condition.path} {operator.value} {condition.expected!r}; observed {actual!r}"
    )
    return passed, detail


class PlanExecutor:
    def __init__(
        self,
        plan: CompiledPlan,
        adapter: ExecutionAdapter,
        run_directory: Path,
        *,
        run_id: str | None = None,
    ) -> None:
        self.plan = plan
        self.adapter = adapter
        self.run_directory = run_directory.resolve()
        self.run_directory.mkdir(parents=True, exist_ok=True)
        write_plan_lock(self.run_directory / "plan.lock.json", plan)
        self.run_id = self._load_or_create_run_identity(run_id)
        self.events = EventLog(
            self.run_directory / "events.jsonl",
            run_id=self.run_id,
            plan_hash=plan.plan_hash,
        )
        self.snapshots = SnapshotStore(self.run_directory / "snapshots")
        self.artifacts = ManifestStore(
            self.run_directory / "artifacts.manifest.json",
            manifest_type="artifacts",
            plan_hash=plan.plan_hash,
        )
        self.checkpoints = ManifestStore(
            self.run_directory / "checkpoints.manifest.json",
            manifest_type="checkpoints",
            plan_hash=plan.plan_hash,
        )
        self._gate_status = {"numerical": "not_evaluated", "scientific": "not_evaluated"}

    def _load_or_create_run_identity(self, requested: str | None) -> str:
        path = self.run_directory / "run.meta.json"
        if path.exists():
            metadata = json.loads(path.read_text(encoding="utf-8"))
            if metadata.get("plan_hash") != self.plan.plan_hash:
                raise DriverError(f"run metadata plan hash differs from plan lock: {path}")
            if requested and requested != metadata.get("run_id"):
                raise DriverError(f"requested run id differs from existing run metadata: {path}")
            return str(metadata["run_id"])
        run_id = requested or f"{self.plan.case_id}-{uuid.uuid4()}"
        atomic_write_json(
            path,
            {
                "run_id": run_id,
                "case_id": self.plan.case_id,
                "plan_hash": self.plan.plan_hash,
                "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
        )
        return run_id

    def apply(self, *, resume: bool = True) -> ExecutionSummary:
        existing = self.events.read()
        self._restore_gate_status(existing)
        if existing and not resume:
            raise DriverError(
                f"event ledger already exists in {self.run_directory}; use resume or a new run directory"
            )
        completed = self.events.successful_actions()
        if existing and completed:
            rehydrate = getattr(self.adapter, "rehydrate", None)
            accepted = bool(
                callable(rehydrate)
                and rehydrate(self.plan, frozenset(completed), self.run_directory)
            )
            if not accepted:
                self.events.append(
                    "run_resume_rejected",
                    payload={
                        "adapter": self.adapter.name,
                        "completed_actions": sorted(completed),
                        "reason": "adapter has no accepted state-rehydration contract",
                    },
                )
                try:
                    self.adapter.close()
                finally:
                    raise DriverError(
                        f"adapter {self.adapter.name!r} cannot safely resume completed actions "
                        "on a fresh solver state; use a new run directory or implement and "
                        "audit an explicit adapter rehydration contract"
                    )
        if existing:
            self.events.append("run_resumed", payload={"adapter": self.adapter.name})
        else:
            self.events.append("run_started", payload={"adapter": self.adapter.name})
        prepare = getattr(self.adapter, "prepare", None)
        if callable(prepare):
            prepare(self.plan)
            self.events.append(
                "adapter_prepared",
                payload={"adapter": self.adapter.name, "plan_hash": self.plan.plan_hash},
            )

        failure: tuple[str, Exception] | None = None
        try:
            for action in self.plan.actions:
                unsatisfied = sorted(set(action.depends_on) - completed)
                if unsatisfied:
                    raise DriverError(
                        f"action {action.id!r} dependencies are not complete: {', '.join(unsatisfied)}"
                    )
                if action.id in completed:
                    self.events.append(
                        "action_skipped", action_id=action.id, payload={"reason": "resume"}
                    )
                    continue
                try:
                    self._execute_action(action)
                    completed.add(action.id)
                except Exception as exc:  # noqa: BLE001 - adapters surface solver-specific errors
                    failure = (action.id, exc)
                    self.events.append(
                        "run_failed",
                        action_id=action.id,
                        payload={"error_type": type(exc).__name__, "error": str(exc)},
                    )
                    break
            if failure is None:
                self.events.append(
                    "run_succeeded", payload={"completed_actions": sorted(completed)}
                )
        finally:
            try:
                self.adapter.close()
            except Exception as exc:  # noqa: BLE001 - close failure is recorded, not substituted
                self.events.append(
                    "adapter_close_failed",
                    payload={"error_type": type(exc).__name__, "error": str(exc)},
                )

        summary = ExecutionSummary(
            run_id=self.run_id,
            case_id=self.plan.case_id,
            plan_hash=self.plan.plan_hash,
            run_directory=str(self.run_directory),
            orchestration_status="failed" if failure else "succeeded",
            numerical_status=self._gate_status["numerical"],
            scientific_status=self._gate_status["scientific"],
            completed_actions=tuple(
                action.id for action in self.plan.actions if action.id in completed
            ),
            failed_action=failure[0] if failure else None,
        )
        atomic_write_json(self.run_directory / "run-summary.json", summary.to_dict())
        if failure:
            identifier, exc = failure
            raise ExecutionFailedError(
                f"action {identifier!r} failed after its retry policy: {exc}"
            ) from exc
        return summary

    def _execute_action(self, action: SemanticAction) -> None:
        prior_attempts = self.events.attempts(action.id)
        last_error: Exception | None = None
        for local_attempt in range(1, action.retry.max_attempts + 1):
            attempt = prior_attempts + local_attempt
            self.events.append(
                "action_started",
                action_id=action.id,
                payload={
                    "attempt": attempt,
                    "invocation_attempt": local_attempt,
                    "kind": action.kind.value,
                },
            )
            before = self._safe_snapshot(action.id)
            before_record = self.snapshots.write(action.id, attempt, "before", before)
            self.events.append(
                "snapshot_recorded",
                action_id=action.id,
                payload={"attempt": attempt, "phase": "before", **before_record},
            )
            try:
                self._assert_conditions(
                    action.preconditions, self._condition_scope(before), "precondition"
                )
                if action.kind is ActionKind.TUI:
                    self.events.append(
                        "tui_escape_requested",
                        action_id=action.id,
                        payload={
                            key: action.parameters[key]
                            for key in (
                                "command",
                                "reason",
                                "fluent_version",
                                "expected_postcondition",
                            )
                        },
                    )
                runtime_action = self._runtime_action(action)
                result = self.adapter.execute(runtime_action)
                after = self._safe_snapshot(action.id)
                after_record = self.snapshots.write(action.id, attempt, "after", after)
                self.events.append(
                    "snapshot_recorded",
                    action_id=action.id,
                    payload={"attempt": attempt, "phase": "after", **after_record},
                )
                scope = self._condition_scope(after, result)
                self._assert_conditions(action.postconditions, scope, "postcondition")
                gate_passed = self._evaluate_gate(action, scope)
                self._record_result(action, attempt, result, gate_passed=gate_passed)
                if action.kind is ActionKind.TUI:
                    self.events.append(
                        "tui_escape_executed",
                        action_id=action.id,
                        payload={"attempt": attempt, "command": action.parameters["command"]},
                    )
                self.events.append(
                    "action_succeeded",
                    action_id=action.id,
                    payload={"attempt": attempt, "result": result.to_dict()},
                )
                return
            except Exception as exc:  # noqa: BLE001 - retry policy applies to adapter errors
                last_error = exc
                failure_after = self._safe_snapshot(action.id)
                failure_record = self.snapshots.write(action.id, attempt, "failure", failure_after)
                self.events.append(
                    "action_failed",
                    action_id=action.id,
                    payload={
                        "attempt": attempt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "failure_snapshot": failure_record,
                        "will_retry": local_attempt < action.retry.max_attempts,
                    },
                )
                if local_attempt < action.retry.max_attempts and action.retry.backoff_seconds:
                    time.sleep(action.retry.backoff_seconds)
        assert last_error is not None
        raise last_error

    def _runtime_action(self, action: SemanticAction) -> SemanticAction:
        """Resolve output templates beneath this run root before solver mutation."""

        parameters = dict(to_jsonable(action.parameters))
        declared_outputs = []
        for output in parameters.get("declared_outputs", ()):
            if not isinstance(output, Mapping):
                raise DriverError(f"stage {action.id!r} declared output must be a mapping")
            runtime_output = dict(output)
            template = runtime_output.get("path_template")
            if not template:
                raise DriverError(f"stage {action.id!r} declared output is missing path_template")
            runtime_output["path_template"] = self._render_output_path(str(template), action.id)
            declared_outputs.append(runtime_output)
        if declared_outputs:
            parameters["declared_outputs"] = declared_outputs

        artifacts = []
        for artifact in parameters.get("artifacts", ()):
            if isinstance(artifact, str):
                artifacts.append(
                    artifact
                    if urlparse(artifact).scheme
                    else self._render_output_path(artifact, action.id)
                )
                continue
            if not isinstance(artifact, Mapping):
                raise DriverError(f"stage {action.id!r} artifact output must be a mapping")
            runtime_artifact = dict(artifact)
            if runtime_artifact.get("path"):
                runtime_artifact["path"] = self._render_output_path(
                    str(runtime_artifact["path"]), action.id
                )
            artifacts.append(runtime_artifact)
        if artifacts:
            parameters["artifacts"] = artifacts
        return replace(action, parameters=parameters)

    def _render_output_path(self, template: str, action_id: str) -> str:
        rendered = template.replace("{run_id}", self.run_id).replace("{case_id}", self.plan.case_id)
        if "{" in rendered or "}" in rendered:
            raise DriverError(
                f"stage {action_id!r} output template has unsupported placeholder: {template}"
            )
        candidate = Path(rendered)
        if not candidate.is_absolute():
            candidate = self.run_directory / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.run_directory)
        except ValueError as exc:
            raise DriverError(
                f"stage {action_id!r} output path escapes the run root: {template}"
            ) from exc
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return str(resolved)

    def _safe_snapshot(self, scope: str) -> Mapping[str, Any]:
        try:
            return dict(to_jsonable(self.adapter.snapshot(scope=scope)))
        except Exception as exc:  # noqa: BLE001 - snapshots are best-effort evidence probes
            return {"snapshot_error": {"type": type(exc).__name__, "message": str(exc)}}

    @staticmethod
    def _condition_scope(
        state: Mapping[str, Any], result: ActionResult | None = None
    ) -> dict[str, Any]:
        scope = {**dict(state), "state": dict(state)}
        if result is not None:
            scope["result"] = result.to_dict()
            if result.metrics:
                scope["metrics"] = dict(result.metrics)
            elif "metrics" not in scope:
                scope["metrics"] = {}
        return scope

    @staticmethod
    def _assert_conditions(
        conditions: tuple[Condition, ...], observed: Mapping[str, Any], label: str
    ) -> None:
        failed = [
            message
            for condition in conditions
            if not (outcome := evaluate_condition(condition, observed))[0]
            for message in [outcome[1]]
        ]
        if failed:
            raise DriverError(f"{label} failed: {'; '.join(failed)}")

    def _evaluate_gate(self, action: SemanticAction, observed: Mapping[str, Any]) -> bool:
        groups: list[dict[str, Any]] = []
        if action.gate is not None:
            evaluations = []
            for condition in action.gate.conditions:
                passed, message = evaluate_condition(condition, observed)
                evaluations.append(
                    {"passed": passed, "message": message, "condition": condition.to_dict()}
                )
            groups.append(
                {
                    "gate_id": action.id,
                    "category": action.gate.category,
                    "required": action.gate.required,
                    "passed": all(item["passed"] for item in evaluations),
                    "evaluations": evaluations,
                }
            )
        for gate in action.parameters.get("named_gates", ()):
            if isinstance(gate, Mapping):
                groups.append(self._evaluate_named_gate(gate, observed))
        if not groups:
            return True

        required_failures = []
        for group in groups:
            category = str(group["category"])
            passed = group["passed"]
            if category in self._gate_status and passed is not None:
                prior = self._gate_status[category]
                self._gate_status[category] = (
                    "failed" if not passed or prior == "failed" else "passed"
                )
            self.events.append("gate_evaluated", action_id=action.id, payload=group)
            if group["required"] and passed is False:
                required_failures.extend(
                    item["message"] for item in group["evaluations"] if not item["passed"]
                )
        if required_failures:
            raise DriverError("required gate failed: " + "; ".join(required_failures))
        return all(group["passed"] is True for group in groups)

    def _evaluate_named_gate(
        self, gate: Mapping[str, Any], observed: Mapping[str, Any]
    ) -> dict[str, Any]:
        gate_type = str(gate.get("type"))
        category = str(gate.get("category", "orchestration"))
        required = gate.get("severity", "required") == "required"
        monitor = str(gate.get("monitor", ""))
        metric_namespace = "metric_history" if gate_type == "steady_window" else "metrics"
        exists, actual = dotted_get(observed, f"{metric_namespace}.{monitor}")
        evaluations: list[dict[str, Any]] = []

        if (
            gate_type in {"threshold", "range", "steady_window"}
            and not exists
            and not getattr(self.adapter, "evaluates_solver_results", True)
        ):
            return {
                "gate_id": str(gate.get("id", gate_type)),
                "category": category,
                "required": required,
                "passed": None,
                "status": "not_evaluated",
                "evaluations": [
                    {
                        "passed": None,
                        "message": (
                            f"{metric_namespace}.{monitor} was not evaluated by the "
                            "recording adapter; "
                            "no numerical or scientific claim is made"
                        ),
                    }
                ],
            }

        if gate_type == "threshold":
            limit = gate.get("limit", {})
            expected = limit.get("value") if isinstance(limit, Mapping) else limit
            aliases = {
                "lt": ConditionOperator.LESS_THAN,
                "le": ConditionOperator.LESS_THAN_OR_EQUAL,
                "gt": ConditionOperator.GREATER_THAN,
                "ge": ConditionOperator.GREATER_THAN_OR_EQUAL,
                "eq": ConditionOperator.EQUALS,
            }
            condition = Condition(
                path=f"metrics.{monitor}",
                operator=aliases[str(gate.get("operator"))],
                expected=expected,
            )
            passed, message = evaluate_condition(condition, observed)
            evaluations.append({"passed": passed, "message": message})
        elif gate_type == "range":
            if gate.get("minimum") is not None:
                minimum = gate["minimum"]
                expected = minimum.get("value") if isinstance(minimum, Mapping) else minimum
                passed = exists and actual >= expected
                evaluations.append(
                    {
                        "passed": passed,
                        "message": f"metrics.{monitor} >= {expected!r}; observed {actual!r}",
                    }
                )
            if gate.get("maximum") is not None:
                maximum = gate["maximum"]
                expected = maximum.get("value") if isinstance(maximum, Mapping) else maximum
                passed = exists and actual <= expected
                evaluations.append(
                    {
                        "passed": passed,
                        "message": f"metrics.{monitor} <= {expected!r}; observed {actual!r}",
                    }
                )
        elif gate_type == "steady_window":
            samples = actual if isinstance(actual, list) else []
            required_samples = int(gate.get("samples", 3))
            window = samples[-required_samples:]
            if len(window) >= required_samples and all(
                isinstance(item, (int, float)) for item in window
            ):
                mean = sum(window) / len(window)
                span = (max(window) - min(window)) / max(abs(mean), 1e-300)
                passed = span <= float(gate["relative_span"])
            else:
                span = None
                passed = False
            evaluations.append(
                {
                    "passed": passed,
                    "message": (
                        f"metrics.{monitor} steady-window relative span <= "
                        f"{gate.get('relative_span')}; observed {span!r}"
                    ),
                }
            )
        elif gate_type == "artifact_exists":
            manifest_path = self.run_directory / "artifacts.manifest.json"
            entries = []
            if manifest_path.exists():
                entries = json.loads(manifest_path.read_text(encoding="utf-8")).get("entries", [])
            expected_stage = gate.get("stage")
            expected_output = gate.get("output")
            matches = [
                entry
                for entry in entries
                if entry.get("action_id") == expected_stage
                and entry.get("metadata", {}).get("output_id") == expected_output
            ]
            if getattr(self.adapter, "requires_materialized_artifacts", True):
                passed = any(self._verified_local_artifact(entry) for entry in matches)
                message = (
                    f"artifact output {expected_stage}.{expected_output} exists as a local "
                    "file matching its manifest SHA-256"
                )
            elif category in {"numerical", "scientific"}:
                passed = None
                message = (
                    f"artifact output {expected_stage}.{expected_output} was only declared by "
                    "the recording adapter; no numerical or scientific claim is made"
                )
            else:
                passed = bool(matches)
                message = (
                    f"artifact output {expected_stage}.{expected_output} has a simulated "
                    "recording-adapter declaration"
                )
            evaluations.append(
                {
                    "passed": passed,
                    "message": message,
                }
            )
        else:
            evaluations.append(
                {"passed": False, "message": f"unsupported named gate type {gate_type!r}"}
            )
        outcomes = [item["passed"] for item in evaluations]
        aggregate = None if any(item is None for item in outcomes) else all(outcomes)
        return {
            "gate_id": str(gate.get("id", gate_type)),
            "category": category,
            "required": required,
            "passed": aggregate,
            "evaluations": evaluations,
        }

    @staticmethod
    def _verified_local_artifact(entry: Mapping[str, Any]) -> bool:
        uri = str(entry.get("uri", ""))
        parsed = urlparse(uri)
        if parsed.scheme != "file":
            return False
        path = Path(unquote(parsed.path))
        expected = entry.get("sha256")
        return bool(expected and path.is_file() and file_sha256(path) == expected)

    def _restore_gate_status(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            if event.get("event") != "gate_evaluated":
                continue
            payload = event.get("payload", {})
            category = payload.get("category")
            if category not in self._gate_status:
                continue
            if payload.get("passed") is None:
                continue
            if not payload.get("passed"):
                self._gate_status[category] = "failed"
            elif self._gate_status[category] != "failed":
                self._gate_status[category] = "passed"

    def _record_result(
        self,
        action: SemanticAction,
        attempt: int,
        result: ActionResult,
        *,
        gate_passed: bool,
    ) -> None:
        for artifact in result.artifacts:
            artifact = self._runtime_record(artifact)
            entry = self.artifacts.add(artifact, action_id=action.id, attempt=attempt)
            self.events.append("artifact_recorded", action_id=action.id, payload=entry)
        checkpoints = list(result.checkpoints)
        if action.kind is ActionKind.PROMOTE_CHECKPOINT and action.parameters.get("uri"):
            checkpoints.append(
                ArtifactRecord(
                    uri=str(action.parameters["uri"]),
                    role=str(action.parameters.get("role", "trusted")),
                    sha256=(
                        str(action.parameters["sha256"])
                        if action.parameters.get("sha256")
                        else None
                    ),
                    metadata={"promotion": True},
                )
            )
        for checkpoint in checkpoints:
            checkpoint = self._runtime_record(checkpoint)
            entry = self.checkpoints.add(checkpoint, action_id=action.id, attempt=attempt)
            self.events.append("checkpoint_recorded", action_id=action.id, payload=entry)
            if action.checkpoint and action.checkpoint.promote_when_gates_pass and gate_passed:
                self.events.append(
                    "checkpoint_promoted",
                    action_id=action.id,
                    payload={"checkpoint": entry, "reason": "configured gates passed"},
                )

    def _runtime_record(self, record: ArtifactRecord) -> ArtifactRecord:
        rendered = record.uri.replace("{run_id}", self.run_id).replace(
            "{case_id}", self.plan.case_id
        )
        parsed = urlparse(rendered)
        if parsed.scheme or Path(rendered).is_absolute():
            return replace(record, uri=rendered)
        return replace(record, uri=(self.run_directory / rendered).resolve().as_uri())


def capture_snapshot(
    adapter: ExecutionAdapter, output: Path, *, scope: str = "all"
) -> dict[str, Any]:
    state = dict(to_jsonable(adapter.snapshot(scope=scope)))
    payload = {"scope": scope, "state": state, "snapshot_hash": stable_hash(state)}
    atomic_write_json(output, payload)
    return payload
