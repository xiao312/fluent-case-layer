"""Compile desired case intent into a deterministic, dependency-ordered plan."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .errors import CaseValidationError
from .types import ActionKind, CompiledPlan, SemanticAction
from .util import deep_merge, dotted_get, stable_hash, to_jsonable

_RECONCILE_DOCUMENTS = {
    "physics": "constant/physics.yaml",
    "materials": "constant/materials.yaml",
    "chemistry": "constant/chemistry.yaml",
    "fields": "0/fields.yaml",
    "boundary_conditions": "0/boundary-conditions.yaml",
    "numerics": "system/numerics.yaml",
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.valid, "issues": [issue.to_dict() for issue in self.issues]}


def _mapping(value: Any, label: str = "case") -> dict[str, Any]:
    projected = to_jsonable(value)
    if not isinstance(projected, Mapping):
        raise CaseValidationError(f"{label} must project to a mapping")
    return dict(projected)


def _first(case: Mapping[str, Any], paths: Iterable[str], default: Any = None) -> Any:
    for path in paths:
        found, value = dotted_get(case, path)
        if found and value is not None:
            return value
    return default


def case_identifier(case: Mapping[str, Any]) -> str:
    value = _first(
        case,
        (
            "case_id",
            "id",
            "case.id",
            "metadata.id",
            "constant.physics.case_id",
            "constant.physics.case.id",
            "constant.physics.id",
            "physics.case.id",
        ),
    )
    if value is None or not str(value).strip():
        raise CaseValidationError(
            "case id is required (case_id, case.id, metadata.id, or constant.physics.case_id)"
        )
    return str(value)


def _explicit_stages(case: Mapping[str, Any]) -> Sequence[Mapping[str, Any]] | None:
    value = _first(case, ("system.control.stages", "control.stages", "stages"))
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise CaseValidationError("system.control.stages must be a list")
    stages: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise CaseValidationError(f"stage at index {index} must be a mapping")
        if item.get("enabled", True):
            stages.append(item)
    return stages


def _indexed(document: Any, key: str = "id") -> dict[str, Mapping[str, Any]]:
    if isinstance(document, Mapping):
        values = document.get(
            "assets", document.get("actions", document.get("monitors", document.get("gates", ())))
        )
    else:
        values = ()
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return {}
    return {
        str(item[key]): item
        for item in values
        if isinstance(item, Mapping) and item.get(key) is not None
    }


def _referenced_asset_ids(value: Any, known_ids: set[str]) -> set[str]:
    """Find typed asset-reference fields without traversing the lock itself."""

    referenced: set[str] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                isinstance(item, str)
                and item in known_ids
                and (str(key) == "asset" or str(key).endswith("_asset"))
            ):
                referenced.add(item)
            else:
                referenced.update(_referenced_asset_ids(item, known_ids))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            referenced.update(_referenced_asset_ids(item, known_ids))
    return referenced


def _reconcile_state_scope(
    case: Mapping[str, Any], stage_id: str, sections: Sequence[Any]
) -> dict[str, Any]:
    state = case.get("state", {})
    if not isinstance(state, Mapping):
        return {}
    mode = str(state.get("mode", ""))
    declared = state.get("declared_paths", ())
    authorized_documents = {
        str(source["document"])
        for item in declared
        if isinstance(item, Mapping)
        and isinstance((source := item.get("source")), Mapping)
        and source.get("type") == "case_document"
        and source.get("pointer") == ""
        and source.get("document")
    }
    requested = tuple(str(section) for section in sections)
    if mode == "checkpoint_overlay":
        unknown = sorted(set(requested) - set(_RECONCILE_DOCUMENTS))
        if unknown:
            raise CaseValidationError(
                f"checkpoint_overlay reconcile stage {stage_id!r} has unknown sections: "
                + ", ".join(unknown)
            )
        unauthorized = [
            section
            for section in requested
            if _RECONCILE_DOCUMENTS[section] not in authorized_documents
        ]
        if unauthorized:
            details = ", ".join(
                f"{section} ({_RECONCILE_DOCUMENTS[section]})" for section in unauthorized
            )
            raise CaseValidationError(
                f"checkpoint_overlay reconcile stage {stage_id!r} is not authorized for "
                f"whole-section mutation: {details}; declare the corresponding case_document "
                "with pointer='' or use a future path-scoped reconcile operation"
            )
    return {
        "mode": mode,
        "requested_sections": list(requested),
        "whole_document_authorizations": sorted(authorized_documents),
    }


def _enrich_explicit_action(raw: Mapping[str, Any], case: Mapping[str, Any]) -> SemanticAction:
    """Resolve schema references while preserving the semantic authored stage."""

    action = SemanticAction.from_mapping(raw)
    parameters = dict(action.parameters)
    raw_type = str(raw.get("type", raw.get("action", "")))
    assets = _indexed(case.get("assets", case.get("assets_lock", {})))

    if raw_type == "load_asset":
        asset_id = str(parameters.get("asset", ""))
        if asset_id in assets:
            parameters["asset_spec"] = dict(assets[asset_id])
        data_id = parameters.get("data_asset")
        if data_id in assets:
            parameters["data_asset_spec"] = dict(assets[str(data_id)])
    elif raw_type == "reconcile":
        sections = parameters.get("sections", ())
        parameters["state_scope"] = _reconcile_state_scope(case, action.id, sections)
        parameters["desired"] = {str(section): case.get(str(section), {}) for section in sections}
    elif raw_type == "initialize":
        action_index = _indexed(case.get("initialization", {}))
        parameters["resolved_actions"] = [
            dict(action_index[identifier])
            for identifier in parameters.get("actions", ())
            if identifier in action_index
        ]
    elif raw_type == "sample":
        monitor_index = _indexed(case.get("monitors", {}))
        parameters["resolved_monitors"] = [
            dict(monitor_index[identifier])
            for identifier in parameters.get("monitors", ())
            if identifier in monitor_index
        ]
    elif raw_type == "gate":
        gate_document = case.get("monitors", {})
        gates = gate_document.get("gates", ()) if isinstance(gate_document, Mapping) else ()
        gate_index = {
            str(item["id"]): item
            for item in gates
            if isinstance(item, Mapping) and item.get("id") is not None
        }
        parameters["named_gates"] = [
            dict(gate_index[identifier])
            for identifier in parameters.get("gates", ())
            if identifier in gate_index
        ]
    elif raw_type == "checkpoint":
        promotion = parameters.get("promotion", {})
        promotion_ids = promotion.get("gates", ()) if isinstance(promotion, Mapping) else ()
        gate_document = case.get("monitors", {})
        gates = gate_document.get("gates", ()) if isinstance(gate_document, Mapping) else ()
        gate_index = {
            str(item["id"]): item
            for item in gates
            if isinstance(item, Mapping) and item.get("id") is not None
        }
        parameters["named_gates"] = [
            dict(gate_index[identifier]) for identifier in promotion_ids if identifier in gate_index
        ]

    referenced_ids = _referenced_asset_ids(raw, set(assets))
    referenced_ids.update(_referenced_asset_ids(parameters.get("desired", {}), set(assets)))
    referenced_ids.update(
        _referenced_asset_ids(parameters.get("resolved_actions", ()), set(assets))
    )
    if referenced_ids:
        parameters["referenced_assets"] = [
            dict(assets[identifier]) for identifier in sorted(referenced_ids)
        ]

    outputs = raw.get("outputs", ())
    if outputs:
        parameters["declared_outputs"] = list(outputs)
        parameters.setdefault(
            "artifacts",
            [
                {
                    "path": item["path_template"],
                    "role": item.get("kind", "output"),
                    "metadata": {
                        "output_id": item.get("id"),
                        "required": item.get("required", True),
                    },
                }
                for item in outputs
                if isinstance(item, Mapping) and item.get("path_template")
            ],
        )
    return replace(action, parameters=parameters)


def _inject_launch(
    actions: Sequence[SemanticAction], platform: Mapping[str, Any]
) -> list[SemanticAction]:
    if any(action.kind is ActionKind.LAUNCH_SOLVER for action in actions):
        return list(actions)
    launch_parameters = _launch_parameters(platform)
    launch = SemanticAction(
        id="launch-solver",
        kind=ActionKind.LAUNCH_SOLVER,
        parameters=launch_parameters,
        description="compiler-injected platform launch or attach boundary",
    )
    enriched = [
        replace(action, depends_on=("launch-solver",)) if not action.depends_on else action
        for action in actions
    ]
    return [launch, *enriched]


def _launch_parameters(platform: Mapping[str, Any]) -> dict[str, Any]:
    """Compile a portable platform profile into PyFluent launch intent."""

    if "kind" in platform and "resources" in platform:
        resources = platform.get("resources", {})
        runtime = platform.get("fluent", {})
        kwargs: dict[str, Any] = {}
        if isinstance(resources, Mapping) and resources.get("ranks") is not None:
            kwargs["processor_count"] = int(resources["ranks"])
        if isinstance(runtime, Mapping) and runtime.get("mode") is not None:
            kwargs["mode"] = runtime["mode"]
        return {
            "connection": "launch",
            "kwargs": kwargs,
            "platform_id": platform.get("id"),
            "runtime": dict(runtime) if isinstance(runtime, Mapping) else runtime,
            "environment": platform.get("environment"),
            "resources": resources,
        }
    launch = platform.get("launch", platform.get("fluent", {}))
    return dict(launch) if isinstance(launch, Mapping) else {}


def _inferred_actions(case: Mapping[str, Any], platform: Mapping[str, Any]) -> list[SemanticAction]:
    """Create a conservative baseline DAG when control.yaml omits stages.

    The inference never attempts solver-specific magic.  It preserves desired
    sections for a reconciler and expects production cases to replace it with
    explicit semantic stages as they mature.
    """

    actions: list[SemanticAction] = []
    tail: str | None = None

    if case.get("assets_lock"):
        actions.append(
            SemanticAction(
                id="resolve-assets",
                kind=ActionKind.RESOLVE_ASSETS,
                parameters={"assets": case["assets_lock"]},
            )
        )
        tail = "resolve-assets"

    launch_parameters = _launch_parameters(platform)
    actions.append(
        SemanticAction(
            id="launch-solver",
            kind=ActionKind.LAUNCH_SOLVER,
            depends_on=(tail,) if tail else (),
            parameters=launch_parameters,
        )
    )
    tail = "launch-solver"

    control = _first(case, ("system.control", "control"), {})
    if not isinstance(control, Mapping):
        control = {}
    start = control.get("start_from", control.get("input"))
    if start:
        start_parameters = dict(start) if isinstance(start, Mapping) else {"path": str(start)}
        start_type = str(start_parameters.get("type", "mesh"))
        kind = (
            ActionKind.READ_CHECKPOINT
            if start_type in {"case", "case_data", "checkpoint", "restart"}
            else ActionKind.READ_MESH
        )
        actions.append(
            SemanticAction(
                id="read-input",
                kind=kind,
                depends_on=(tail,),
                parameters=start_parameters,
            )
        )
        tail = "read-input"

    desired = {
        "physics": _first(case, ("constant.physics", "physics"), {}),
        "materials": _first(case, ("constant.materials", "materials"), {}),
        "chemistry": _first(case, ("constant.chemistry", "chemistry"), {}),
        "fields": _first(case, ("0.fields", "initial.fields"), {}),
        "boundary_conditions": _first(
            case,
            ("0.boundary_conditions", "0.boundary-conditions", "boundary_conditions"),
            {},
        ),
        "numerics": _first(case, ("system.numerics", "numerics"), {}),
        "monitors": _first(case, ("system.monitors", "monitors"), {}),
    }
    settings_operations = control.get("settings_operations", ())
    actions.append(
        SemanticAction(
            id="reconcile-settings",
            kind=ActionKind.RECONCILE_SETTINGS,
            depends_on=(tail,),
            parameters={"desired": desired, "operations": settings_operations},
        )
    )
    tail = "reconcile-settings"

    initialization = _first(case, ("system.initialization", "initialization"), {})
    if initialization:
        actions.append(
            SemanticAction(
                id="initialize",
                kind=ActionKind.INITIALIZE,
                depends_on=(tail,),
                parameters=dict(initialization) if isinstance(initialization, Mapping) else {},
            )
        )
        tail = "initialize"

    iterations = control.get("iterations")
    time_steps = control.get("time_steps")
    if iterations is not None:
        actions.append(
            SemanticAction(
                id="run",
                kind=ActionKind.ITERATE,
                depends_on=(tail,),
                parameters={"iterations": int(iterations)},
            )
        )
        tail = "run"
    elif time_steps is not None:
        actions.append(
            SemanticAction(
                id="run",
                kind=ActionKind.ADVANCE_TIME,
                depends_on=(tail,),
                parameters={
                    "time_steps": int(time_steps),
                    "max_iterations_per_step": int(control.get("max_iterations_per_step", 20)),
                },
            )
        )
        tail = "run"

    actions.append(
        SemanticAction(
            id="final-snapshot",
            kind=ActionKind.SNAPSHOT,
            depends_on=(tail,),
            parameters={"scope": "final"},
        )
    )
    return actions


def dependency_order(actions: Sequence[SemanticAction]) -> tuple[SemanticAction, ...]:
    """Stable topological sort with duplicate, missing-edge, and cycle checks."""

    by_id: dict[str, SemanticAction] = {}
    positions: dict[str, int] = {}
    for index, action in enumerate(actions):
        if action.id in by_id:
            raise CaseValidationError(f"duplicate stage id: {action.id}")
        by_id[action.id] = action
        positions[action.id] = index
    for action in actions:
        missing = [dependency for dependency in action.depends_on if dependency not in by_id]
        if missing:
            raise CaseValidationError(
                f"stage {action.id!r} has missing dependencies: {', '.join(missing)}"
            )

    remaining = {identifier: set(action.depends_on) for identifier, action in by_id.items()}
    ordered: list[SemanticAction] = []
    emitted: set[str] = set()
    while len(ordered) < len(actions):
        ready = [
            identifier
            for identifier, dependencies in remaining.items()
            if identifier not in emitted and dependencies <= emitted
        ]
        if not ready:
            cycle = sorted(identifier for identifier in remaining if identifier not in emitted)
            raise CaseValidationError(f"stage dependency cycle involves: {', '.join(cycle)}")
        ready.sort(key=positions.__getitem__)
        for identifier in ready:
            ordered.append(by_id[identifier])
            emitted.add(identifier)
    return tuple(ordered)


def compile_plan(
    case: Any,
    platform: Mapping[str, Any] | None = None,
    *,
    overlay: Mapping[str, Any] | None = None,
) -> CompiledPlan:
    case_mapping = _mapping(case)
    if overlay:
        case_mapping = deep_merge(case_mapping, overlay)
    platform_mapping = _mapping(platform or {}, "platform")
    if not platform_mapping:
        platforms = case_mapping.get("platforms", {})
        control = case_mapping.get("control", {})
        default_platform = control.get("default_platform") if isinstance(control, Mapping) else None
        if isinstance(platforms, Mapping) and default_platform in platforms:
            platform_mapping = _mapping(platforms[default_platform], "platform")
    identifier = case_identifier(case_mapping)

    explicit = _explicit_stages(case_mapping)
    try:
        actions = (
            [_enrich_explicit_action(item, case_mapping) for item in explicit]
            if explicit is not None
            else _inferred_actions(case_mapping, platform_mapping)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CaseValidationError(str(exc)) from exc
    actions = _inject_launch(actions, platform_mapping)
    ordered = dependency_order(actions)
    schema_version = str(case_mapping.get("schema_version", "1"))
    metadata: dict[str, Any] = {
        "compiler": "fluent-case-layer",
        "explicit_stages": explicit is not None,
    }
    objectives = case_mapping.get("objectives")
    if isinstance(objectives, Mapping):
        metadata["objectives"] = {
            "revision": to_jsonable(objectives.get("revision", {})),
            "content_digest": stable_hash(objectives),
            "enforcement": objectives.get("enforcement", "none"),
            "document": to_jsonable(objectives),
        }
    state_ownership = case_mapping.get("state")
    if isinstance(state_ownership, Mapping):
        metadata["state_ownership"] = {
            "policy": to_jsonable(state_ownership),
            "content_digest": stable_hash(state_ownership),
        }
    title = _first(case_mapping, ("title", "case.title", "metadata.title"))
    if title:
        metadata["title"] = str(title)
    plan = CompiledPlan(
        schema_version=schema_version,
        case_id=identifier,
        case_digest=stable_hash(case_mapping),
        actions=ordered,
        platform=platform_mapping,
        metadata=metadata,
    )
    return plan.with_hash()


def validate_case(case: Any, platform: Mapping[str, Any] | None = None) -> ValidationReport:
    issues: list[ValidationIssue] = []
    try:
        plan = compile_plan(case, platform)
    except (CaseValidationError, TypeError, ValueError) as exc:
        return ValidationReport((ValidationIssue("error", "compile_error", str(exc)),))
    if not plan.actions:
        issues.append(ValidationIssue("error", "empty_plan", "compiled plan has no stages"))
    if not any(action.kind is ActionKind.LAUNCH_SOLVER for action in plan.actions):
        issues.append(
            ValidationIssue(
                "warning",
                "no_launch_stage",
                "plan has no launch_solver stage; the adapter must attach to an existing session",
                "system.control.stages",
            )
        )
    if not any(
        action.kind in {ActionKind.ITERATE, ActionKind.ADVANCE_TIME} for action in plan.actions
    ):
        issues.append(
            ValidationIssue(
                "warning",
                "no_solve_stage",
                "plan contains no iterate or advance_time stage",
                "system.control.stages",
            )
        )
    return ValidationReport(tuple(issues))
