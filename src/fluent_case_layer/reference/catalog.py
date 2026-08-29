"""Build a deterministic field catalog from JSON Schema and coupling metadata."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from fnmatch import fnmatchcase
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml

from fluent_case_layer.schema.export import SCHEMA_MODELS

CATALOG_VERSION = "1.0"
COUPLING_STATUSES = {
    "implemented",
    "partial",
    "planned",
    "declaration_only",
    "not_applicable",
}


@dataclass(frozen=True)
class DocumentSpec:
    key: str
    source_path: str
    schema_file: str
    title: str
    purpose: str

    @property
    def reference_page(self) -> str:
        return f"reference/{self.key}.md"


DOCUMENTS = (
    DocumentSpec(
        "physics",
        "constant/physics.yaml",
        "physics.schema.json",
        "Physics",
        "Solver formulation and enabled physical models.",
    ),
    DocumentSpec(
        "materials",
        "constant/materials.yaml",
        "materials.schema.json",
        "Materials",
        "Material definitions, properties, and cell-zone assignments.",
    ),
    DocumentSpec(
        "chemistry",
        "constant/chemistry.yaml",
        "chemistry.schema.json",
        "Chemistry",
        "Reaction model, mechanism assets, streams, and tracked species.",
    ),
    DocumentSpec(
        "fields",
        "0/fields.yaml",
        "fields.schema.json",
        "Initial fields",
        "Named initial field intent and value representations.",
    ),
    DocumentSpec(
        "boundary-conditions",
        "0/boundary-conditions.yaml",
        "boundary-conditions.schema.json",
        "Boundary conditions",
        "Zone selection and typed Fluent boundary intent.",
    ),
    DocumentSpec(
        "numerics",
        "system/numerics.yaml",
        "numerics.schema.json",
        "Numerics",
        "Reusable discretization, coupling, relaxation, and transient profiles.",
    ),
    DocumentSpec(
        "initialization",
        "system/initialization.yaml",
        "initialization.schema.json",
        "Initialization",
        "Ordered checkpoint, initialization, register, patch, and TUI actions.",
    ),
    DocumentSpec(
        "monitors",
        "system/monitors.yaml",
        "monitors.schema.json",
        "Monitors and gates",
        "Observed quantities and optional case-local engineering judgments.",
    ),
    DocumentSpec(
        "objectives",
        "system/objectives.yaml",
        "objectives.schema.json",
        "Engineering objectives",
        "Versioned engineer intent and selected comparison aspects.",
    ),
    DocumentSpec(
        "state",
        "system/state.yaml",
        "state.schema.json",
        "State ownership",
        "Full-definition or checkpoint-overlay mutation ownership.",
    ),
    DocumentSpec(
        "control",
        "system/control.yaml",
        "control.schema.json",
        "Stage control",
        "Typed dependency graph, execution policy, outputs, and checkpoints.",
    ),
    DocumentSpec(
        "platform",
        "platforms/*.yaml",
        "platform.schema.json",
        "Platforms",
        "Local or Slurm launch resources and Fluent runtime intent.",
    ),
    DocumentSpec(
        "assets-lock",
        "assets.lock.yaml",
        "assets-lock.schema.json",
        "Asset lock",
        "Immutable external inputs identified by source and SHA-256.",
    ),
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_pointer_part(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _entry_anchor(pointer: str) -> str:
    readable = re.sub(r"[^a-z0-9]+", "-", pointer.casefold()).strip("-") or "root"
    suffix = hashlib.sha256(pointer.encode("utf-8")).hexdigest()[:8]
    return f"entry-{readable}-{suffix}"


def _resolve_pointer(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"only local JSON Schema references are supported: {reference}")
    value: Any = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        value = value[part]
    if not isinstance(value, dict):
        raise TypeError(f"JSON Schema reference is not an object: {reference}")
    return value


def _dereference(node: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    result = node
    seen: set[str] = set()
    while "$ref" in result:
        reference = str(result["$ref"])
        if reference in seen:
            raise ValueError(f"recursive JSON Schema reference: {reference}")
        seen.add(reference)
        resolved = copy.deepcopy(_resolve_pointer(root, reference))
        resolved.update({key: value for key, value in result.items() if key != "$ref"})
        result = resolved
    return result


def _value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _collect_types(node: dict[str, Any], root: dict[str, Any]) -> set[str]:
    value = _dereference(node, root)
    result: set[str] = set()
    node_type = value.get("type")
    if isinstance(node_type, str):
        result.add(node_type)
    elif isinstance(node_type, list):
        result.update(str(item) for item in node_type)
    if "const" in value:
        result.add(_value_type(value["const"]))
    for keyword in ("oneOf", "anyOf", "allOf"):
        for branch in value.get(keyword, []):
            if isinstance(branch, dict):
                result.update(_collect_types(branch, root))
    if not result and ("properties" in value or "additionalProperties" in value):
        result.add("object")
    if not result and "items" in value:
        result.add("array")
    return result


def _collect_choices(node: dict[str, Any], root: dict[str, Any]) -> list[Any]:
    value = _dereference(node, root)
    choices: list[Any] = []
    if "const" in value:
        choices.append(value["const"])
    choices.extend(value.get("enum", []))
    for keyword in ("oneOf", "anyOf"):
        for branch in value.get(keyword, []):
            if isinstance(branch, dict):
                choices.extend(_collect_choices(branch, root))
    unique: dict[str, Any] = {}
    for choice in choices:
        unique[_canonical_json(choice)] = choice
    return [unique[key] for key in sorted(unique)]


def _first_value(node: dict[str, Any], root: dict[str, Any], key: str) -> Any:
    value = _dereference(node, root)
    if key in value:
        return value[key]
    for keyword in ("oneOf", "anyOf", "allOf"):
        for branch in value.get(keyword, []):
            if not isinstance(branch, dict):
                continue
            found = _first_value(branch, root, key)
            if found is not None:
                return found
    return None


def _schema_summary(node: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    value = _dereference(node, root)
    constraints = {
        key: value[key]
        for key in (
            "minimum",
            "exclusiveMinimum",
            "maximum",
            "exclusiveMaximum",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
            "pattern",
            "keyPattern",
            "format",
        )
        if key in value
    }
    item_choices: list[Any] = []
    if isinstance(value.get("items"), dict):
        item_choices = _collect_choices(value["items"], root)
    types = sorted(_collect_types(value, root))
    choices = _collect_choices(value, root)
    if "boolean" in types and not choices:
        choices = [False, True]
    summary: dict[str, Any] = {
        "types": types,
        "choices": choices,
        "item_choices": item_choices,
        "constraints": constraints,
    }
    if "default" in value:
        summary["default"] = value["default"]
    return summary


def _branch_label(
    parent: dict[str, Any], branch: dict[str, Any], root: dict[str, Any], index: int
) -> str | None:
    resolved = _dereference(branch, root)
    discriminator = parent.get("discriminator", {}).get("propertyName")
    if discriminator:
        candidate = resolved.get("properties", {}).get(discriminator, {})
        choices = _collect_choices(candidate, root) if isinstance(candidate, dict) else []
        if len(choices) == 1:
            return f"{discriminator}={choices[0]}"
    if resolved.get("type") == "null":
        return None
    title = resolved.get("title")
    if title:
        return str(title)
    types = sorted(_collect_types(resolved, root))
    if len(types) == 1:
        return types[0]
    return f"branch-{index + 1}"


class _EntryAccumulator:
    def __init__(self, document: DocumentSpec) -> None:
        self.document = document
        self.occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add(
        self,
        pointer: str,
        node: dict[str, Any],
        root: dict[str, Any],
        *,
        required: bool,
        contexts: tuple[str, ...],
    ) -> None:
        resolved = _dereference(node, root)
        self.occurrences[pointer].append(
            {
                "summary": _schema_summary(resolved, root),
                "required": required,
                "contexts": contexts,
                "title": _first_value(resolved, root, "title"),
                "description": _first_value(resolved, root, "description"),
            }
        )

    def entries(self) -> list[dict[str, Any]]:
        result = []
        context_universe: dict[str, set[str]] = defaultdict(set)
        for occurrences in self.occurrences.values():
            for occurrence in occurrences:
                for context in occurrence["contexts"]:
                    context_universe[context.rsplit(":", 1)[0]].add(context)
        for pointer, occurrences in sorted(self.occurrences.items()):
            contexts = sorted(
                {context for occurrence in occurrences for context in occurrence["contexts"]}
            )
            required_contexts = sorted(
                {
                    context
                    for occurrence in occurrences
                    if occurrence["required"]
                    for context in occurrence["contexts"]
                }
            )
            context_groups: dict[str, set[str]] = defaultdict(set)
            for context in contexts:
                context_groups[context.rsplit(":", 1)[0]].add(context)
            available_in_every_variant = all(
                values == context_universe[group] for group, values in context_groups.items()
            )
            if all(o["required"] for o in occurrences) and available_in_every_variant:
                requirement = "required"
            elif any(o["required"] for o in occurrences):
                requirement = "conditional"
            else:
                requirement = "optional"
            summaries = [occurrence["summary"] for occurrence in occurrences]
            schema: dict[str, Any] = {
                "types": sorted({item for summary in summaries for item in summary["types"]}),
                "requirement": requirement,
                "choices": _merge_json_values(summary["choices"] for summary in summaries),
                "item_choices": _merge_json_values(
                    summary["item_choices"] for summary in summaries
                ),
                "constraints": _merge_constraints(summaries),
                "available_in": contexts,
                "required_in": required_contexts,
            }
            defaults = [summary["default"] for summary in summaries if "default" in summary]
            if defaults and all(default == defaults[0] for default in defaults):
                schema["default"] = defaults[0]
            key = pointer.rsplit("/", 1)[-1].replace("~1", "/").replace("~0", "~")
            title = next((o["title"] for o in occurrences if o["title"]), None)
            description = next((o["description"] for o in occurrences if o["description"]), None)
            result.append(
                {
                    "id": f"{self.document.source_path}#{pointer}",
                    "document": self.document.key,
                    "source_path": self.document.source_path,
                    "pointer": pointer,
                    "key": key,
                    "title": title or key.replace("_", " ").title(),
                    "description": description or "",
                    "reference": {
                        "page": self.document.reference_page,
                        "anchor": _entry_anchor(pointer),
                    },
                    "schema": schema,
                }
            )
        return result


def _merge_json_values(groups: Any) -> list[Any]:
    values: dict[str, Any] = {}
    for group in groups:
        for value in group:
            values[_canonical_json(value)] = value
    return [values[key] for key in sorted(values)]


def _merge_constraints(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, list[Any]] = defaultdict(list)
    for summary in summaries:
        for key, value in summary["constraints"].items():
            if value not in merged[key]:
                merged[key].append(value)
    return {
        key: values[0] if len(values) == 1 else values for key, values in sorted(merged.items())
    }


def _walk_schema(
    node: dict[str, Any],
    root: dict[str, Any],
    accumulator: _EntryAccumulator,
    pointer: str,
    contexts: tuple[str, ...] = (),
) -> None:
    value = _dereference(node, root)
    for keyword in ("oneOf", "anyOf"):
        branches = [branch for branch in value.get(keyword, []) if isinstance(branch, dict)]
        non_null = [
            branch
            for branch in branches
            if "null" not in _collect_types(branch, root) or len(_collect_types(branch, root)) > 1
        ]
        if branches:
            contextual = len(non_null) > 1
            for index, branch in enumerate(non_null):
                label = _branch_label(value, branch, root, index)
                branch_contexts = contexts
                if contextual and label:
                    branch_contexts = contexts + (f"{pointer or '/'}:{label}",)
                _walk_schema(branch, root, accumulator, pointer, branch_contexts)
            return

    properties = value.get("properties", {})
    if isinstance(properties, dict):
        required = set(value.get("required", []))
        for key, child in sorted(properties.items()):
            if not isinstance(child, dict):
                continue
            child_pointer = f"{pointer}/{_json_pointer_part(key)}"
            accumulator.add(
                child_pointer,
                child,
                root,
                required=key in required,
                contexts=contexts,
            )
            _walk_schema(child, root, accumulator, child_pointer, contexts)

    additional = value.get("additionalProperties")
    if isinstance(additional, dict):
        child_pointer = f"{pointer}/*"
        accumulator.add(
            child_pointer,
            additional,
            root,
            required=False,
            contexts=contexts,
        )
        _walk_schema(additional, root, accumulator, child_pointer, contexts)

    pattern_properties = value.get("patternProperties", {})
    if isinstance(pattern_properties, dict):
        for key_pattern, child in sorted(pattern_properties.items()):
            if not isinstance(child, dict):
                continue
            child_pointer = f"{pointer}/*"
            annotated_child = copy.deepcopy(child)
            annotated_child["keyPattern"] = key_pattern
            accumulator.add(
                child_pointer,
                annotated_child,
                root,
                required=False,
                contexts=contexts,
            )
            _walk_schema(annotated_child, root, accumulator, child_pointer, contexts)

    items = value.get("items")
    if isinstance(items, dict):
        _walk_schema(items, root, accumulator, f"{pointer}/*", contexts)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _load_registry(path: Path | None = None) -> tuple[dict[str, Any], str]:
    if path is None:
        resource = files("fluent_case_layer.reference").joinpath("couplings.yaml")
        raw = resource.read_text(encoding="utf-8")
    else:
        raw = path.read_text(encoding="utf-8")
    payload = yaml.safe_load(raw)
    if not isinstance(payload, dict):
        raise TypeError("coupling registry must contain a mapping")
    return payload, raw


def _apply_couplings(
    entries: list[dict[str, Any]], registry: dict[str, Any]
) -> list[dict[str, Any]]:
    defaults = registry.get("document_defaults", {})
    patterns = registry.get("patterns", [])
    exact = registry.get("entries", {})
    known_ids = {entry["id"] for entry in entries}
    unknown = sorted(set(exact) - known_ids)
    if unknown:
        raise ValueError(f"coupling registry contains unknown entry ids: {', '.join(unknown)}")
    pattern_hits: Counter[int] = Counter()
    result = []
    for entry in entries:
        coupling = copy.deepcopy(defaults.get(entry["source_path"], {}))
        for index, rule in enumerate(patterns):
            if fnmatchcase(entry["id"], str(rule.get("match", ""))):
                coupling = _deep_merge(coupling, rule.get("coupling", {}))
                pattern_hits[index] += 1
        coupling = _deep_merge(coupling, exact.get(entry["id"], {}))
        status = coupling.get("adapter", {}).get("status")
        if status not in COUPLING_STATUSES:
            raise ValueError(f"{entry['id']} has invalid or missing adapter status: {status!r}")
        authored = coupling.pop("authoring", {})
        updated = copy.deepcopy(entry)
        if authored.get("description"):
            updated["description"] = authored["description"]
        if authored:
            updated["authoring"] = authored
        updated["coupling"] = coupling
        result.append(updated)
    missed = [
        str(rule.get("match"))
        for index, rule in enumerate(patterns)
        if not pattern_hits[index] and not rule.get("allow_no_match", False)
    ]
    if missed:
        raise ValueError(f"coupling patterns matched no entries: {', '.join(missed)}")
    return result


def build_catalog(registry_path: Path | None = None) -> dict[str, Any]:
    """Return the deterministic complete dictionary reference catalog."""

    registry, registry_raw = _load_registry(registry_path)
    entries: list[dict[str, Any]] = []
    schema_hashes: dict[str, str] = {}
    document_payloads = []
    for document in DOCUMENTS:
        model = SCHEMA_MODELS[document.schema_file]
        schema = model.model_json_schema(mode="validation")
        schema_hashes[document.schema_file] = _sha256_text(_canonical_json(schema))
        accumulator = _EntryAccumulator(document)
        _walk_schema(schema, schema, accumulator, "")
        document_entries = accumulator.entries()
        entries.extend(document_entries)
        document_payloads.append(
            {
                "key": document.key,
                "source_path": document.source_path,
                "schema_file": document.schema_file,
                "title": document.title,
                "purpose": document.purpose,
                "reference_page": document.reference_page,
                "entry_count": len(document_entries),
            }
        )
    entries = _apply_couplings(entries, registry)
    by_status = Counter(entry["coupling"]["adapter"]["status"] for entry in entries)
    by_document: dict[str, dict[str, Any]] = {}
    for document in DOCUMENTS:
        selected = [entry for entry in entries if entry["document"] == document.key]
        by_document[document.key] = {
            "total": len(selected),
            "by_status": dict(
                sorted(Counter(e["coupling"]["adapter"]["status"] for e in selected).items())
            ),
        }
    return {
        "catalog_version": CATALOG_VERSION,
        "target": registry.get("target", {}),
        "policy": registry.get("policy", {}),
        "generated_from": {
            "schema_sha256": dict(sorted(schema_hashes.items())),
            "couplings_sha256": _sha256_text(registry_raw),
        },
        "documents": document_payloads,
        "coverage": {
            "total_entries": len(entries),
            "by_status": dict(sorted(by_status.items())),
            "by_document": by_document,
        },
        "entries": entries,
    }


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    """Load the checked-in machine-readable catalog."""

    if path is None:
        raw = (
            files("fluent_case_layer.reference")
            .joinpath("catalog.json")
            .read_text(encoding="utf-8")
        )
    else:
        raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("catalog_version") != CATALOG_VERSION:
        raise ValueError("unsupported or invalid reference catalog")
    return payload
