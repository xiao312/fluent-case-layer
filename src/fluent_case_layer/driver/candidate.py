"""Compile an auditable candidate overlay without mutating authored case YAML."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from .errors import CaseValidationError
from .loading import LoadedCase
from .planner import compile_plan
from .types import CompiledPlan
from .util import deep_merge, stable_hash, to_jsonable


def _overlay_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    projected = to_jsonable(value)
    if not isinstance(projected, Mapping):  # pragma: no cover - protocol guard
        raise CaseValidationError("candidate overlay must be a mapping")
    if not projected:
        raise CaseValidationError("candidate overlay must not be empty")
    protected = sorted({"objectives", "state"} & set(projected))
    if protected:
        raise CaseValidationError(
            "candidate overlay cannot rewrite engineer-authored objective or state-ownership "
            "contracts: " + ", ".join(protected)
        )
    return dict(projected)


def _selected_objective_ids(
    values: Sequence[str], candidate_case: Mapping[str, Any]
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise CaseValidationError("selected objective ids must be a sequence")
    selected = tuple(str(value).strip() for value in values)
    if any(not value for value in selected):
        raise CaseValidationError("selected objective ids must not be empty")
    if len(selected) != len(set(selected)):
        raise CaseValidationError("selected objective ids must be unique")

    objectives = candidate_case.get("objectives", {})
    aspects = objectives.get("aspects", ()) if isinstance(objectives, Mapping) else ()
    known = {
        str(item["id"])
        for item in aspects
        if isinstance(item, Mapping) and item.get("id") is not None
    }
    unknown = sorted(set(selected) - known)
    if unknown:
        raise CaseValidationError(
            "candidate references unknown objective aspects: " + ", ".join(unknown)
        )
    return selected


def _canonical_candidate(
    loaded: LoadedCase, overlay: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    merged = deep_merge(loaded.case, overlay)
    if loaded.schema_model != "CaseSpec":
        return merged, dict(loaded.platform)

    # The schema package owns cross-document rules. Keeping this import at the
    # boundary preserves license-free/lightweight driver fixtures.
    from fluent_case_layer.schema import CaseSpec

    try:
        validated = CaseSpec.model_validate(merged)
    except ValueError as exc:
        details = " ".join(str(exc).splitlines())
        raise CaseValidationError(
            f"canonical candidate is invalid after overlay: {details}"
        ) from exc
    case = dict(to_jsonable(validated))
    platform_id = loaded.platform.get("id")
    if platform_id is None:
        control = case.get("control", {})
        platform_id = control.get("default_platform") if isinstance(control, Mapping) else None
    platforms = case.get("platforms", {})
    if not isinstance(platforms, Mapping) or platform_id not in platforms:
        raise CaseValidationError(
            f"canonical candidate has no selected platform {platform_id!r} after overlay"
        )
    return case, dict(platforms[str(platform_id)])


def compile_candidate_plan(
    loaded: LoadedCase,
    *,
    overlay: Mapping[str, Any],
    rationale: str,
    objective_ids: Sequence[str] = (),
) -> CompiledPlan:
    """Revalidate and compile one exact, rationale-bearing candidate overlay."""

    normalized_rationale = rationale.strip()
    if not normalized_rationale:
        raise CaseValidationError("candidate rationale must not be empty")
    exact_overlay = _overlay_mapping(overlay)
    candidate_case, candidate_platform = _canonical_candidate(loaded, exact_overlay)
    selected = _selected_objective_ids(objective_ids, candidate_case)
    plan = compile_plan(candidate_case, candidate_platform)
    objectives = plan.metadata.get("objectives", {})
    objective_document = objectives.get("document", {}) if isinstance(objectives, Mapping) else {}
    aspects = (
        objective_document.get("aspects", ()) if isinstance(objective_document, Mapping) else ()
    )
    selected_aspects = [
        dict(item)
        for item in aspects
        if isinstance(item, Mapping) and str(item.get("id")) in selected
    ]
    state_ownership = plan.metadata.get("state_ownership", {})
    state_policy = state_ownership.get("policy", {}) if isinstance(state_ownership, Mapping) else {}
    candidate_metadata = {
        "schema_version": "1",
        "base_case_digest": stable_hash(loaded.case),
        "overlay": exact_overlay,
        "overlay_sha256": stable_hash(exact_overlay),
        "rationale": normalized_rationale,
        "selected_objective_ids": list(selected),
        "objective_context": {
            "revision": objectives.get("revision", {}) if isinstance(objectives, Mapping) else {},
            "content_digest": objectives.get("content_digest")
            if isinstance(objectives, Mapping)
            else None,
            "provenance": objective_document.get("provenance", {})
            if isinstance(objective_document, Mapping)
            else {},
            "statement": objective_document.get("statement")
            if isinstance(objective_document, Mapping)
            else None,
            "selected_aspects": selected_aspects,
        },
        "state_ownership": {
            "mode": state_policy.get("mode") if isinstance(state_policy, Mapping) else None,
            "content_digest": state_ownership.get("content_digest")
            if isinstance(state_ownership, Mapping)
            else None,
        },
    }
    return replace(
        plan,
        metadata={**dict(plan.metadata), "candidate": candidate_metadata},
    ).with_hash()
