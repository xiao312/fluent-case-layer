"""Expand and execute case/variant matrices with bounded concurrency."""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.base import ExecutionAdapter
from .errors import CaseValidationError
from .evidence import write_plan_lock
from .executor import PlanExecutor
from .loading import AutoCaseLoader, CaseLoader, load_data
from .planner import compile_plan
from .types import CompiledPlan
from .util import deep_merge, dotted_set, stable_hash, to_jsonable


@dataclass(frozen=True, slots=True)
class CampaignCase:
    id: str
    source: str
    platform: str | None
    overlay: Mapping[str, Any]
    plan: CompiledPlan

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "platform": self.platform,
            "overlay": dict(self.overlay),
            "plan": self.plan.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CompiledCampaign:
    id: str
    cases: tuple[CampaignCase, ...]
    campaign_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "campaign_id": self.id,
            "campaign_hash": self.campaign_hash,
            "cases": [item.to_dict() for item in self.cases],
        }


def _slug(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-") or "value"


def _matrix_overlays(matrix: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    if not matrix:
        return [("", {})]
    keys = sorted(matrix)
    values: list[Sequence[Any]] = []
    for key in keys:
        options = matrix[key]
        if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
            raise CaseValidationError(f"campaign matrix value for {key!r} must be a list")
        values.append(options)
    variants: list[tuple[str, dict[str, Any]]] = []
    for combination in itertools.product(*values):
        overlay: dict[str, Any] = {}
        labels = []
        for key, value in zip(keys, combination, strict=True):
            dotted_set(overlay, key, value)
            labels.append(f"{_slug(key.split('.')[-1])}-{_slug(value)}")
        variants.append(("__".join(labels), overlay))
    return variants


def _validated_variant(
    loaded_case: Mapping[str, Any],
    loaded_platform: Mapping[str, Any],
    overlay: Mapping[str, Any],
    *,
    schema_model: str | None,
    platform: Any,
    item_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge a variant and re-run canonical cross-document validation."""

    merged = deep_merge(loaded_case, overlay)
    if schema_model != "CaseSpec":
        return merged, dict(loaded_platform)

    # AutoCaseLoader already proved this dependency is available. Importing at
    # the boundary keeps lightweight fixtures independent of Pydantic.
    from fluent_case_layer.schema import CaseSpec

    try:
        validated = CaseSpec.model_validate(merged)
    except ValueError as exc:
        details = " ".join(str(exc).splitlines())
        raise CaseValidationError(
            f"canonical campaign variant {item_id!r} is invalid after overlay: {details}"
        ) from exc
    case = dict(to_jsonable(validated))
    requested_platform = (
        Path(str(platform)).stem if platform is not None else case["control"]["default_platform"]
    )
    try:
        selected_platform = case["platforms"][requested_platform]
    except KeyError as exc:  # defensive: CaseSpec validates authored references
        raise CaseValidationError(
            f"canonical campaign variant {item_id!r} has no platform {requested_platform!r}"
        ) from exc
    return case, dict(selected_platform)


def _portable_source_reference(authored: Any, resolved: Path) -> str:
    authored_path = Path(str(authored))
    if not authored_path.is_absolute():
        return authored_path.as_posix()
    # Absolute locations are runtime provenance, not portable campaign identity.
    return f"external:{resolved.name}"


def compile_campaign(
    source: str | Path,
    *,
    loader: CaseLoader | None = None,
) -> CompiledCampaign:
    source_path = Path(source).resolve()
    raw = load_data(source_path)
    if not isinstance(raw, Mapping):
        raise CaseValidationError("campaign document must be a mapping")
    identifier = str(raw.get("campaign_id", raw.get("id", source_path.stem)))
    defaults = raw.get("defaults", {})
    if not isinstance(defaults, Mapping):
        raise CaseValidationError("campaign.defaults must be a mapping")
    entries = raw.get("cases", ())
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)) or not entries:
        raise CaseValidationError("campaign.cases must be a non-empty list")
    case_loader = loader or AutoCaseLoader()
    compiled: list[CampaignCase] = []
    seen: set[str] = set()

    for index, raw_entry in enumerate(entries):
        entry: Mapping[str, Any]
        if isinstance(raw_entry, str):
            entry = {"path": raw_entry}
        elif isinstance(raw_entry, Mapping):
            entry = raw_entry
        else:
            raise CaseValidationError(f"campaign case {index} must be a path or mapping")
        relative = entry.get("path", entry.get("case"))
        if not relative:
            raise CaseValidationError(f"campaign case {index} is missing path")
        case_path = Path(str(relative))
        source_reference = _portable_source_reference(relative, case_path)
        if not case_path.is_absolute():
            case_path = (source_path.parent / case_path).resolve()
        platform = entry.get("platform", defaults.get("platform"))
        base_overlay = deep_merge(
            defaults.get("overlay", {}) if isinstance(defaults.get("overlay", {}), Mapping) else {},
            entry.get("overlay", {}) if isinstance(entry.get("overlay", {}), Mapping) else {},
        )
        matrix = entry.get("matrix", {})
        if not isinstance(matrix, Mapping):
            raise CaseValidationError(f"campaign case {index} matrix must be a mapping")
        variants = _matrix_overlays(matrix)
        explicit_variants = entry.get("variants", ())
        if explicit_variants:
            if not isinstance(explicit_variants, Sequence) or isinstance(
                explicit_variants, (str, bytes)
            ):
                raise CaseValidationError(f"campaign case {index} variants must be a list")
            variants = []
            for variant_index, variant in enumerate(explicit_variants):
                if not isinstance(variant, Mapping):
                    raise CaseValidationError(
                        f"campaign case {index} variant {variant_index} must be a mapping"
                    )
                variants.append(
                    (
                        str(variant.get("id", variant_index)),
                        dict(variant.get("overlay", {})),
                    )
                )

        loaded = case_loader.load(case_path, str(platform) if platform is not None else None)
        base_id = str(entry.get("id", case_path.name))
        for variant_label, variant_overlay in variants:
            item_id = base_id if not variant_label else f"{base_id}__{_slug(variant_label)}"
            if item_id in seen:
                raise CaseValidationError(f"duplicate campaign case id: {item_id}")
            seen.add(item_id)
            overlay = deep_merge(base_overlay, variant_overlay)
            variant_case, variant_platform = _validated_variant(
                loaded.case,
                loaded.platform,
                overlay,
                schema_model=loaded.schema_model,
                platform=platform,
                item_id=item_id,
            )
            plan = compile_plan(variant_case, variant_platform)
            compiled.append(
                CampaignCase(
                    id=item_id,
                    source=source_reference,
                    platform=str(platform) if platform is not None else None,
                    overlay=overlay,
                    plan=plan,
                )
            )

    unsigned = {
        "campaign_id": identifier,
        "cases": [{"id": item.id, "plan_hash": item.plan.plan_hash} for item in compiled],
    }
    return CompiledCampaign(identifier, tuple(compiled), stable_hash(unsigned))


def validate_campaign(campaign: CompiledCampaign) -> dict[str, Any]:
    cases = []
    valid = True
    for item in campaign.cases:
        # Compilation already performed structural validation. Preserve the
        # compiler warnings from the normalized plan shape.
        has_solve = any(
            action.kind.value in {"iterate", "advance_time"} for action in item.plan.actions
        )
        issues = (
            []
            if has_solve
            else [
                {
                    "severity": "warning",
                    "code": "no_solve_stage",
                    "message": "plan has no solve stage",
                    "path": "system.control.stages",
                }
            ]
        )
        cases.append({"id": item.id, "valid": True, "issues": issues})
    return {"valid": valid, "campaign_id": campaign.id, "cases": cases}


def materialize_campaign_plans(campaign: CompiledCampaign, output_root: Path) -> None:
    for item in campaign.cases:
        write_plan_lock(output_root / campaign.id / item.id / "plan.lock.json", item.plan)


def apply_campaign(
    campaign: CompiledCampaign,
    output_root: Path,
    adapter_factory: Callable[[CampaignCase], ExecutionAdapter],
    *,
    max_workers: int = 1,
    resume: bool = True,
) -> dict[str, Any]:
    if max_workers < 1:
        raise CaseValidationError("campaign max_workers must be at least 1")

    def run(item: CampaignCase) -> dict[str, Any]:
        directory = output_root / campaign.id / item.id
        executor = PlanExecutor(item.plan, adapter_factory(item), directory)
        return executor.apply(resume=resume).to_dict()

    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fluent-case") as pool:
        futures = {pool.submit(run, item): item for item in campaign.cases}
        for future in as_completed(futures):
            item = futures[future]
            try:
                results[item.id] = future.result()
            except Exception as exc:  # noqa: BLE001 - isolate failures between campaign cases
                results[item.id] = {
                    "case_id": item.plan.case_id,
                    "orchestration_status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
    ordered = {item.id: results[item.id] for item in campaign.cases}
    return {
        "campaign_id": campaign.id,
        "campaign_hash": campaign.campaign_hash,
        "status": (
            "succeeded"
            if all(value.get("orchestration_status") == "succeeded" for value in ordered.values())
            else "failed"
        ),
        "cases": ordered,
    }
