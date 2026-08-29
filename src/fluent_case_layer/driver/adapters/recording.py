"""License-free recording adapter for tests, reviews, and dry runs."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..types import ActionKind, ActionResult, ArtifactRecord, CompiledPlan, SemanticAction
from ..util import dotted_set, stable_hash, to_jsonable


class RecordingAdapter:
    """Apply semantic state transitions without importing or launching Fluent."""

    name = "recording"
    evaluates_solver_results = False
    requires_materialized_artifacts = False

    def __init__(
        self,
        *,
        initial_state: Mapping[str, Any] | None = None,
        failures: Mapping[str, int] | None = None,
    ) -> None:
        self.state: dict[str, Any] = dict(to_jsonable(initial_state or {}))
        self.state.setdefault("connected", False)
        self.executed: list[str] = []
        self.failures = dict(failures or {})

    def prepare(self, plan: CompiledPlan) -> None:
        """Declare locked inputs available only inside this explicit simulation."""

        self.state["execution_mode"] = "simulated"
        assets = self.state.setdefault("assets", {})
        for action in plan.actions:
            referenced = list(action.parameters.get("referenced_assets", ()))
            legacy = action.parameters.get("asset_spec")
            if isinstance(legacy, Mapping):
                referenced.append(legacy)
            for asset in referenced:
                if not isinstance(asset, Mapping) or not asset.get("id"):
                    continue
                asset_id = str(asset["id"])
                current = assets.setdefault(
                    asset_id,
                    {
                        "available": True,
                        "availability_evidence": "simulated_by_recording_adapter",
                        "content_verified": False,
                        "sha256": asset.get("sha256"),
                        "source": asset.get("source"),
                        "referenced_by": [],
                    },
                )
                if action.id not in current["referenced_by"]:
                    current["referenced_by"].append(action.id)

    def rehydrate(
        self,
        plan: CompiledPlan,
        completed_actions: frozenset[str],
        run_directory: Path,
    ) -> bool:
        """Allow evidence-only skip semantics without claiming solver state."""

        self.state["resume_mode"] = "simulated_from_event_ledger"
        self.state["rehydrated_actions"] = sorted(completed_actions)
        return True

    def snapshot(self, *, scope: str = "all") -> Mapping[str, Any]:
        return {"adapter": self.name, "scope": scope, **deepcopy(self.state)}

    def execute(self, action: SemanticAction) -> ActionResult:
        remaining = self.failures.get(action.id, 0)
        if remaining > 0:
            self.failures[action.id] = remaining - 1
            raise RuntimeError(f"injected recording-adapter failure for {action.id}")
        self.executed.append(action.id)
        parameters = dict(action.parameters)

        if action.kind is ActionKind.LAUNCH_SOLVER:
            self.state["connected"] = True
            self.state["launch"] = to_jsonable(parameters)
        elif action.kind in {
            ActionKind.LOAD_ASSET,
            ActionKind.READ_MESH,
            ActionKind.READ_CHECKPOINT,
        }:
            self.state["input"] = {
                "kind": action.kind.value,
                **to_jsonable(parameters),
            }
        elif action.kind is ActionKind.RECONCILE_SETTINGS:
            desired = parameters.get("desired", parameters.get("settings", {}))
            self.state["desired_settings"] = to_jsonable(desired)
            self._record_operations(parameters.get("operations", ()))
        elif action.kind is ActionKind.CREATE_REGISTER:
            registers = self.state.setdefault("registers", {})
            name = str(parameters.get("name", action.id))
            registers[name] = to_jsonable(parameters)
        elif action.kind is ActionKind.INITIALIZE:
            self.state["initialized"] = True
            self.state["initialization"] = to_jsonable(parameters)
            self._record_operations(parameters.get("operations", ()))
        elif action.kind is ActionKind.PATCH:
            patches = self.state.setdefault("patches", [])
            patches.append(to_jsonable(parameters))
            self._record_operations(parameters.get("operations", ()))
        elif action.kind is ActionKind.ITERATE:
            count = int(parameters.get("iterations", parameters.get("count", 0)))
            self.state["iteration"] = int(self.state.get("iteration", 0)) + count
        elif action.kind is ActionKind.ADVANCE_TIME:
            count = int(parameters.get("time_steps", parameters.get("count", 0)))
            self.state["time_step"] = int(self.state.get("time_step", 0)) + count
        elif action.kind is ActionKind.TUI:
            commands = self.state.setdefault("audited_tui_commands", [])
            commands.append(
                {
                    "command": parameters["command"],
                    "reason": parameters["reason"],
                    "fluent_version": parameters["fluent_version"],
                    "expected_postcondition": parameters["expected_postcondition"],
                }
            )
        elif action.kind is ActionKind.PROMOTE_CHECKPOINT:
            self.state["promoted_checkpoint"] = to_jsonable(parameters)
        elif action.kind is ActionKind.SAMPLE:
            self.state["last_sample"] = to_jsonable(parameters)
            if isinstance(parameters.get("metrics"), Mapping):
                metrics = self.state.setdefault("metrics", {})
                history = self.state.setdefault("metric_history", {})
                for name, value in parameters["metrics"].items():
                    metrics[str(name)] = to_jsonable(value)
                    history.setdefault(str(name), []).append(to_jsonable(value))

        artifacts = tuple(self._artifacts(parameters.get("artifacts", ()), action.id))
        checkpoints = list(self._artifacts(parameters.get("checkpoints", ()), action.id))
        if action.kind is ActionKind.WRITE_CHECKPOINT or action.checkpoint is not None:
            checkpoint_name = (
                action.checkpoint.name
                if action.checkpoint is not None
                else str(parameters.get("name", action.id))
            )
            role = action.checkpoint.role if action.checkpoint is not None else "recovery"
            uri = str(parameters.get("uri", f"recording://checkpoint/{checkpoint_name}"))
            checkpoints.append(
                ArtifactRecord(
                    uri=uri,
                    role=role,
                    sha256=stable_hash({"action": action.id, "state": self.state}),
                    metadata={"checkpoint_name": checkpoint_name},
                )
            )
        metrics = parameters.get("metrics", {})
        return ActionResult(
            details={"adapter": self.name, "action_kind": action.kind.value},
            metrics=dict(metrics) if isinstance(metrics, Mapping) else {},
            artifacts=artifacts,
            checkpoints=tuple(checkpoints),
        )

    def _record_operations(self, operations: Any) -> None:
        for operation in operations or ():
            if not isinstance(operation, Mapping):
                continue
            path = operation.get("path")
            if path and "value" in operation:
                settings = self.state.setdefault("settings_api", {})
                dotted_set(settings, str(path), operation["value"])

    @staticmethod
    def _artifacts(values: Any, action_id: str) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
        for index, value in enumerate(values or ()):
            if isinstance(value, str):
                records.append(ArtifactRecord(uri=value, role="output"))
                continue
            if isinstance(value, Mapping):
                uri = str(value.get("uri", value.get("path", f"recording://{action_id}/{index}")))
                records.append(
                    ArtifactRecord(
                        uri=uri,
                        role=str(value.get("role", "output")),
                        sha256=str(value["sha256"]) if value.get("sha256") else None,
                        size_bytes=int(value["size_bytes"]) if value.get("size_bytes") else None,
                        media_type=str(value["media_type"]) if value.get("media_type") else None,
                        metadata={
                            **dict(value.get("metadata", {})),
                            "materialization": "simulated_not_created",
                        },
                    )
                )
        return records

    def close(self) -> None:
        self.state["connected"] = False
