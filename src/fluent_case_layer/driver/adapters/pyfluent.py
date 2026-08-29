"""Lazy PyFluent adapter.

Importing this module does not import ``ansys.fluent.core``.  The dependency
and a Fluent license are needed only when a launch/attach action executes.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..errors import AdapterMappingError, DriverError, OptionalDependencyError
from ..types import ActionKind, ActionResult, ArtifactRecord, CompiledPlan, SemanticAction
from ..util import file_sha256, to_jsonable


class PyFluentAdapter:
    name = "pyfluent"
    evaluates_solver_results = True

    def __init__(
        self, *, session: Any = None, launch_config: Mapping[str, Any] | None = None
    ) -> None:
        self.session = session
        self.launch_config = dict(launch_config or {})
        self._owns_session = session is None
        self._observed: dict[str, Any] = {}
        self._assets: dict[str, Any] = {}
        self._resolved_assets: dict[str, str] = {}
        self._metrics: dict[str, Any] = {}
        self._metric_history: dict[str, list[Any]] = {}

    requires_materialized_artifacts = True

    def prepare(self, plan: CompiledPlan) -> None:
        """Resolve local locked assets and verify bytes before Fluent launches."""

        for action in plan.actions:
            referenced = list(action.parameters.get("referenced_assets", ()))
            for spec_key in ("asset_spec", "data_asset_spec"):
                legacy = action.parameters.get(spec_key)
                if isinstance(legacy, Mapping):
                    referenced.append(legacy)
            for asset in referenced:
                if not isinstance(asset, Mapping) or not asset.get("id"):
                    continue
                identifier = str(asset["id"])
                if identifier not in self._assets:
                    self._prepare_asset(identifier, asset)
        unavailable = sorted(
            identifier for identifier, state in self._assets.items() if not state["available"]
        )
        if unavailable:
            details = "; ".join(
                f"{identifier}: {self._assets[identifier].get('reason')}"
                for identifier in unavailable
            )
            raise DriverError(
                "referenced Fluent assets are unavailable or failed SHA-256 verification: "
                + details
            )

    def rehydrate(
        self,
        plan: CompiledPlan,
        completed_actions: frozenset[str],
        run_directory: Path,
    ) -> bool:
        """Fail closed until checkpoint/session state rehydration is implemented."""

        return False

    def _prepare_asset(self, identifier: str, asset: Mapping[str, Any]) -> None:
        source = asset.get("source", {})
        path: Path | None = None
        reason: str | None = None
        if isinstance(source, Mapping) and source.get("type") == "environment":
            variable = str(source["root_variable"])
            root = os.environ.get(variable)
            if root:
                path = Path(root) / str(source["relative_path"])
            else:
                reason = f"environment variable {variable} is unset"
        elif isinstance(source, Mapping) and source.get("type") == "repository":
            path = Path(str(source["path"]))
        elif isinstance(source, Mapping) and source.get("type") == "remote":
            reason = "remote asset requires an external content-addressed materializer"
        else:
            reason = "unsupported asset source"

        available = bool(path and path.is_file())
        content_verified = False
        observed_hash: str | None = None
        if available and path is not None:
            observed_hash = file_sha256(path)
            content_verified = observed_hash == asset.get("sha256")
            available = content_verified
            if not content_verified:
                reason = "SHA-256 mismatch"
            else:
                self._resolved_assets[identifier] = str(path.resolve())
        elif path is not None and reason is None:
            reason = f"resolved path is not a file: {path}"
        self._assets[identifier] = {
            "available": available,
            "availability_evidence": "local_sha256_verification",
            "content_verified": content_verified,
            "expected_sha256": asset.get("sha256"),
            "observed_sha256": observed_hash,
            "resolved_path": str(path) if path is not None else None,
            "reason": reason,
        }

    def snapshot(self, *, scope: str = "all") -> Mapping[str, Any]:
        snapshot: dict[str, Any] = {
            "adapter": self.name,
            "scope": scope,
            "connected": self.session is not None,
            "observed_settings": dict(self._observed),
            "assets": dict(self._assets),
            "metrics": dict(self._metrics),
            "metric_history": {name: list(values) for name, values in self._metric_history.items()},
        }
        if self.session is not None:
            getter = getattr(self.session, "get_fluent_version", None)
            if callable(getter):
                try:
                    snapshot["fluent_version"] = str(getter())
                except Exception as exc:  # noqa: BLE001 - evidence probe must not abort a run
                    snapshot["fluent_version_error"] = repr(exc)
        return snapshot

    def execute(self, action: SemanticAction) -> ActionResult:
        if action.kind is ActionKind.RESOLVE_ASSETS:
            return ActionResult(details={"asset_resolution": "delegated_to_platform"})
        if action.kind is ActionKind.LAUNCH_SOLVER:
            self._connect(action.parameters)
            return ActionResult(details={"connected": True})
        self._require_session(action.id)
        parameters = dict(action.parameters)
        operation_metrics: dict[str, Any] = {}

        if action.kind is ActionKind.LOAD_ASSET:
            self._load_asset(parameters)
        elif action.kind is ActionKind.READ_MESH:
            path = self._required_path(parameters)
            self._call("file.read_mesh", kwargs={"file_name": path})
        elif action.kind is ActionKind.READ_CHECKPOINT:
            path = self._required_path(parameters)
            mode = str(parameters.get("mode", parameters.get("type", "case_data")))
            call_path = "file.read_case" if mode == "case" else "file.read_case_data"
            self._call(call_path, kwargs={"file_name": path})
        elif action.kind in {
            ActionKind.RECONCILE_SETTINGS,
            ActionKind.CREATE_REGISTER,
            ActionKind.PATCH,
        }:
            operations = self._required_operations(action, parameters)
            self._execute_operations(operations, action.id)
        elif action.kind is ActionKind.SAMPLE:
            operations = self._required_operations(action, parameters)
            operation_metrics = self._execute_operations(operations, action.id)
            expected_metrics = {
                str(monitor["id"])
                for monitor in parameters.get("resolved_monitors", ())
                if isinstance(monitor, Mapping) and monitor.get("id")
            }
            missing_metrics = sorted(expected_metrics - operation_metrics.keys())
            if missing_metrics:
                raise AdapterMappingError(
                    self._mapping_gap_message(
                        action,
                        "sample collectors did not capture metrics: " + ", ".join(missing_metrics),
                    )
                )
        elif action.kind is ActionKind.INITIALIZE:
            operations = parameters.get("operations")
            if operations:
                self._execute_operations(operations, action.id)
            elif "resolved_actions" in parameters:
                self._execute_resolved_initialization(action, parameters["resolved_actions"])
            else:
                method = str(parameters.get("method", "hybrid"))
                if method != "hybrid":
                    raise AdapterMappingError(
                        self._mapping_gap_message(
                            action,
                            f"initialization method {method!r} requires explicit settings operations",
                        )
                    )
                self._call("solution.initialization.hybrid_initialize")
        elif action.kind is ActionKind.ITERATE:
            iterations = int(parameters.get("iterations", parameters.get("count", 1)))
            self._call("solution.run_calculation.iterate", kwargs={"iter_count": iterations})
        elif action.kind is ActionKind.ADVANCE_TIME:
            steps = int(parameters.get("time_steps", parameters.get("count", 1)))
            iterations = int(parameters.get("max_iterations_per_step", 20))
            self._call(
                "solution.run_calculation.dual_time_iterate",
                kwargs={"time_step_count": steps, "max_iter_per_step": iterations},
            )
        elif action.kind is ActionKind.WRITE_CHECKPOINT:
            self._write_checkpoint(parameters)
        elif action.kind is ActionKind.PROMOTE_CHECKPOINT:
            # Promotion is a manifest operation; no solver mutation is implied.
            pass
        elif action.kind in {ActionKind.GATE, ActionKind.SNAPSHOT}:
            pass
        elif action.kind is ActionKind.TUI:
            self._execute_tui(parameters)
        else:  # pragma: no cover - enum exhaustiveness guard
            raise DriverError(f"unsupported PyFluent action kind: {action.kind}")

        artifacts = tuple(self._collect_artifacts(parameters.get("artifacts", ())))
        checkpoints: tuple[ArtifactRecord, ...] = ()
        if action.kind is ActionKind.WRITE_CHECKPOINT or action.checkpoint is not None:
            role = action.checkpoint.role if action.checkpoint else "recovery"
            checkpoint_paths = [
                item.get("path_template")
                for item in parameters.get("declared_outputs", ())
                if isinstance(item, Mapping)
                and item.get("kind") in {"case", "data", "checkpoint"}
                and item.get("path_template")
            ]
            fallback = parameters.get("path", parameters.get("file_name"))
            if fallback:
                checkpoint_paths.append(fallback)
            checkpoints = tuple(
                self._path_record(Path(str(path)), role) for path in checkpoint_paths
            )
        metrics = parameters.get("metrics", {})
        normalized_metrics = dict(metrics) if isinstance(metrics, Mapping) else {}
        normalized_metrics.update(operation_metrics)
        if action.kind is ActionKind.SAMPLE:
            for name, value in normalized_metrics.items():
                normalized = to_jsonable(value)
                self._metrics[str(name)] = normalized
                self._metric_history.setdefault(str(name), []).append(normalized)
        return ActionResult(
            details={"adapter": self.name, "action_kind": action.kind.value},
            metrics=normalized_metrics,
            artifacts=artifacts,
            checkpoints=checkpoints,
        )

    def _connect(self, action_parameters: Mapping[str, Any]) -> None:
        if self.session is not None:
            return
        try:
            pyfluent = importlib.import_module("ansys.fluent.core")
        except ImportError as exc:
            raise OptionalDependencyError(
                "PyFluent adapter selected but ansys-fluent-core is not installed; "
                "install the project 'fluent' extra"
            ) from exc
        config = {**self.launch_config, **dict(action_parameters)}
        connection_mode = str(config.pop("connection", config.pop("mode", "launch")))
        kwargs = dict(config.pop("kwargs", {}))
        reserved = {
            "close_on_exit",
            "platform_id",
            "runtime",
            "environment",
            "resources",
        }
        kwargs.update({key: value for key, value in config.items() if key not in reserved})
        if connection_mode in {"attach", "connect"}:
            connector = getattr(pyfluent, "connect_to_fluent", None)
            if not callable(connector):
                raise DriverError("installed PyFluent does not expose connect_to_fluent")
            self.session = connector(**kwargs)
        else:
            launcher = getattr(pyfluent, "launch_fluent", None)
            if not callable(launcher):
                raise DriverError("installed PyFluent does not expose launch_fluent")
            self.session = launcher(**kwargs)

    def _require_session(self, action_id: str) -> None:
        if self.session is None:
            raise DriverError(
                f"action {action_id!r} requires a Fluent session; add launch_solver or pass a session"
            )

    @staticmethod
    def _required_path(parameters: Mapping[str, Any]) -> str:
        path = parameters.get("path", parameters.get("file_name", parameters.get("uri")))
        if not path:
            raise DriverError("file action requires parameters.path or parameters.file_name")
        value = str(path)
        if value.startswith("file://"):
            return value[7:]
        return value

    def _load_asset(self, parameters: Mapping[str, Any]) -> None:
        load_as = str(parameters.get("load_as", ""))
        path = parameters.get("resolved_path", parameters.get("path"))
        asset_id = parameters.get("asset")
        asset = parameters.get("asset_spec", {})
        if not asset and asset_id:
            asset = next(
                (
                    item
                    for item in parameters.get("referenced_assets", ())
                    if isinstance(item, Mapping) and item.get("id") == asset_id
                ),
                {},
            )
        if not path and asset_id in self._resolved_assets:
            path = self._resolved_assets[str(asset_id)]
        if not path and isinstance(asset, Mapping):
            source = asset.get("source", {})
            if isinstance(source, Mapping) and source.get("type") == "environment":
                root_variable = str(source["root_variable"])
                root = os.environ.get(root_variable)
                if not root:
                    raise DriverError(
                        f"asset {asset.get('id')!r} requires environment variable {root_variable}"
                    )
                path = str(Path(root) / str(source["relative_path"]))
            elif isinstance(source, Mapping) and source.get("type") == "repository":
                path = str(Path(str(source["path"])))
        if not path:
            raise DriverError(
                f"load_asset({load_as}) requires a platform-resolved path; immutable asset "
                "identity remains available in parameters.asset_spec"
            )
        local_path = Path(str(path))
        expected_hash = asset.get("sha256") if isinstance(asset, Mapping) else None
        if expected_hash:
            if not local_path.is_file():
                raise DriverError(f"resolved asset is not a file: {local_path}")
            observed_hash = file_sha256(local_path)
            if observed_hash != expected_hash:
                raise DriverError(
                    f"asset hash mismatch for {local_path}: expected {expected_hash}, got {observed_hash}"
                )
        if load_as == "mesh":
            self._call("file.read_mesh", kwargs={"file_name": str(path)})
        elif load_as == "case":
            self._call("file.read_case", kwargs={"file_name": str(path)})
        elif load_as == "case_data":
            self._call("file.read_case_data", kwargs={"file_name": str(path)})
        else:
            operations = parameters.get("operations", ())
            if not operations:
                raise DriverError(
                    f"load_asset({load_as}) requires explicit PyFluent settings operations"
                )
            self._execute_operations(operations, f"load-{load_as}")

    def _write_checkpoint(self, parameters: Mapping[str, Any]) -> None:
        declared = parameters.get("declared_outputs", ())
        wrote = False
        for output in declared or ():
            if not isinstance(output, Mapping) or not output.get("path_template"):
                continue
            kind = str(output.get("kind", ""))
            path = str(output["path_template"])
            if kind == "case" and parameters.get("write_case", True):
                self._call("file.write_case", kwargs={"file_name": path})
                wrote = True
            elif kind == "data" and parameters.get("write_data", True):
                self._call("file.write_data", kwargs={"file_name": path})
                wrote = True
        if wrote:
            return
        path = self._required_path(parameters)
        call_path = str(parameters.get("call_path", "file.write_case_data"))
        self._call(call_path, kwargs={"file_name": path})

    def _resolve(self, dotted_path: str) -> Any:
        current = self.session
        normalized = dotted_path.removeprefix("settings.")
        for component in normalized.split("."):
            if not component:
                continue
            if isinstance(current, Mapping):
                current = current[component]
            else:
                current = getattr(current, component)
        return current

    def _resolve_parent(self, dotted_path: str) -> tuple[Any, str]:
        components = dotted_path.removeprefix("settings.").split(".")
        if not components:
            raise DriverError("empty settings path")
        parent = self.session
        for component in components[:-1]:
            parent = (
                parent[component] if isinstance(parent, Mapping) else getattr(parent, component)
            )
        return parent, components[-1]

    def _call(
        self,
        path: str,
        *,
        args: Iterable[Any] = (),
        kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        target = self._resolve(path)
        if not callable(target):
            raise DriverError(f"PyFluent settings target is not callable: {path}")
        return target(*tuple(args), **dict(kwargs or {}))

    def _required_operations(
        self, action: SemanticAction, parameters: Mapping[str, Any]
    ) -> list[Mapping[str, Any]]:
        operations = parameters.get("operations")
        if not isinstance(operations, list) or not operations:
            semantic_payload = []
            for key in ("sections", "desired", "resolved_monitors", "name", "target"):
                if parameters.get(key):
                    semantic_payload.append(key)
            detail = (
                "semantic payload " + ", ".join(semantic_payload)
                if semantic_payload
                else "this semantic action"
            )
            raise AdapterMappingError(
                self._mapping_gap_message(
                    action,
                    f"{detail} has no compiled PyFluent settings operations",
                )
            )
        if not all(isinstance(operation, Mapping) for operation in operations):
            raise AdapterMappingError(
                self._mapping_gap_message(action, "operations must be a non-empty list of mappings")
            )
        return operations

    @staticmethod
    def _mapping_gap_message(action: SemanticAction, detail: str) -> str:
        return (
            f"PyFluent adapter mapping gap for {action.kind.value} stage {action.id!r}: "
            f"{detail}; refusing a silent no-op or partial fallback"
        )

    def _execute_resolved_initialization(
        self, action: SemanticAction, resolved_actions: Any
    ) -> None:
        if not isinstance(resolved_actions, list) or not resolved_actions:
            raise AdapterMappingError(
                self._mapping_gap_message(
                    action,
                    "resolved initialization actions are empty or invalid",
                )
            )
        action_types = [
            str(item.get("type")) if isinstance(item, Mapping) else type(item).__name__
            for item in resolved_actions
        ]
        # This exact one-action form has a direct, unambiguous settings API mapping.
        if len(resolved_actions) == 1 and action_types == ["hybrid"]:
            self._call("solution.initialization.hybrid_initialize")
            return
        raise AdapterMappingError(
            self._mapping_gap_message(
                action,
                "resolved initialization sequence is not implemented: " + ", ".join(action_types),
            )
        )

    def _execute_operations(self, operations: Any, action_id: str) -> dict[str, Any]:
        captured: dict[str, Any] = {}
        for index, operation in enumerate(operations or ()):
            if not isinstance(operation, Mapping):
                raise DriverError(f"{action_id} operation {index} must be a mapping")
            path = str(operation.get("path", ""))
            if not path:
                raise DriverError(f"{action_id} operation {index} is missing path")
            mode = str(operation.get("mode", "set"))
            if mode in {"call", "invoke"}:
                result = self._call(
                    path,
                    args=operation.get("args", ()),
                    kwargs=operation.get("kwargs", {}),
                )
                self._observed[path] = to_jsonable(result) if result is not None else None
            elif mode in {"set", "set_state"}:
                value = operation.get("value")
                target = self._resolve(path)
                setter = getattr(target, "set_state", None)
                if callable(setter):
                    setter(value)
                else:
                    parent, name = self._resolve_parent(path)
                    if isinstance(parent, Mapping):
                        parent[name] = value
                    else:
                        setattr(parent, name, value)
                self._observed[path] = to_jsonable(value)
            elif mode in {"get", "observe"}:
                target = self._resolve(path)
                getter = getattr(target, "get_state", None)
                result = getter() if callable(getter) else target
                self._observed[path] = to_jsonable(result)
            else:
                raise DriverError(f"unsupported settings operation mode {mode!r} at {path}")
            capture_as = operation.get("capture_as", operation.get("metric"))
            if capture_as:
                captured[str(capture_as)] = self._observed[path]
        return captured

    def _execute_tui(self, parameters: Mapping[str, Any]) -> None:
        call_path = parameters.get("call_path")
        if call_path:
            self._call(
                str(call_path),
                args=parameters.get("args", ()),
                kwargs=parameters.get("kwargs", {}),
            )
            return
        command = str(parameters["command"])
        executor = getattr(self.session, "execute_tui", None)
        if callable(executor):
            executor(command)
            return
        raise DriverError(
            "this PyFluent session has no raw execute_tui method; provide the generated "
            "TUI call as parameters.call_path while retaining parameters.command for audit"
        )

    def _collect_artifacts(self, values: Any) -> list[ArtifactRecord]:
        result: list[ArtifactRecord] = []
        for value in values or ():
            if isinstance(value, str):
                result.append(self._path_record(Path(value), "output"))
            elif isinstance(value, Mapping):
                path = value.get("path")
                if path:
                    result.append(
                        ArtifactRecord(
                            uri=Path(str(path)).resolve().as_uri(),
                            role=str(value.get("role", "output")),
                            metadata=dict(value.get("metadata", {})),
                        )
                    )
                elif value.get("uri"):
                    result.append(
                        ArtifactRecord(
                            uri=str(value["uri"]),
                            role=str(value.get("role", "output")),
                            sha256=str(value["sha256"]) if value.get("sha256") else None,
                            metadata=dict(value.get("metadata", {})),
                        )
                    )
        return result

    @staticmethod
    def _path_record(path: Path, role: str) -> ArtifactRecord:
        return ArtifactRecord(uri=path.resolve().as_uri(), role=role)

    def close(self) -> None:
        if self.session is None:
            return
        if self._owns_session and bool(self.launch_config.get("close_on_exit", True)):
            exit_method = getattr(self.session, "exit", None)
            if callable(exit_method):
                exit_method()
        self.session = None
