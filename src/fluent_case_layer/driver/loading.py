"""Case source loading behind a small protocol.

The schema package owns semantic validation.  This module deliberately accepts
its Pydantic model output *or* a plain split-directory mapping so the executor
does not depend on schema implementation details.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .errors import CaseValidationError, OptionalDependencyError
from .util import deep_merge, to_jsonable


@dataclass(frozen=True, slots=True)
class LoadedCase:
    case: Mapping[str, Any]
    platform: Mapping[str, Any]
    root: Path
    schema_model: str | None = None


class CaseLoader(Protocol):
    """Boundary implemented by schema-aware and lightweight loaders."""

    def load(self, source: Path, platform: str | Path | None = None) -> LoadedCase: ...


def load_data(path: Path) -> Any:
    """Load JSON or YAML while keeping PyYAML optional to the core driver."""

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise OptionalDependencyError(
                f"PyYAML is required to load non-JSON YAML file {path}"
            ) from exc
    return yaml.safe_load(text)


def _normal_key(filename: str) -> str:
    name = filename
    for suffix in (".yaml", ".yml", ".json"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("-", "_").replace(".", "_")


class DirectoryCaseLoader:
    """Load the OpenFOAM-inspired split layout into one JSON-like mapping."""

    _SECTIONS = ("constant", "0", "system")

    def load(self, source: Path, platform: str | Path | None = None) -> LoadedCase:
        source = source.resolve()
        if source.is_file():
            raw = load_data(source)
            if not isinstance(raw, Mapping):
                raise CaseValidationError(f"case document must be a mapping: {source}")
            root = source.parent
            case = dict(to_jsonable(raw))
        elif source.is_dir():
            root = source
            case = self._load_directory(source)
        else:
            raise CaseValidationError(f"case source does not exist: {source}")
        platform_data = self._load_platform(root, platform)
        return LoadedCase(case=case, platform=platform_data, root=root)

    def _load_directory(self, root: Path) -> dict[str, Any]:
        case: dict[str, Any] = {}
        for filename in ("case.yaml", "case.yml", "case.json"):
            path = root / filename
            if path.exists():
                raw = load_data(path)
                if not isinstance(raw, Mapping):
                    raise CaseValidationError(f"{path} must contain a mapping")
                case = deep_merge(case, raw)
                break

        for section in self._SECTIONS:
            directory = root / section
            if not directory.is_dir():
                continue
            section_data: dict[str, Any] = {}
            paths = sorted(
                (*directory.glob("*.yaml"), *directory.glob("*.yml"), *directory.glob("*.json"))
            )
            for path in paths:
                raw = load_data(path)
                if raw is None:
                    raw = {}
                section_data[_normal_key(path.name)] = to_jsonable(raw)
            case[section] = deep_merge(case.get(section, {}), section_data)

        for filename in ("assets.lock.yaml", "assets.lock.yml", "assets.lock.json"):
            path = root / filename
            if path.exists():
                case["assets_lock"] = to_jsonable(load_data(path))
                break
        if not case:
            raise CaseValidationError(f"no case documents found below {root}")
        return case

    def _load_platform(self, root: Path, platform: str | Path | None) -> dict[str, Any]:
        if platform is None:
            return {}
        candidate = Path(platform)
        if not candidate.is_absolute():
            direct = root / candidate
            if direct.exists():
                candidate = direct
            else:
                name = str(platform)
                variants = (
                    [name] if Path(name).suffix else [f"{name}.yaml", f"{name}.yml", f"{name}.json"]
                )
                matches = [root / "platforms" / item for item in variants]
                candidate = next((item for item in matches if item.exists()), matches[0])
        if not candidate.exists():
            raise CaseValidationError(f"platform profile does not exist: {candidate}")
        raw = load_data(candidate)
        if not isinstance(raw, Mapping):
            raise CaseValidationError(f"platform profile must be a mapping: {candidate}")
        return dict(to_jsonable(raw))


class AutoCaseLoader:
    """Prefer the canonical typed schema when a complete split case is present."""

    _CANONICAL_FILES = (
        "constant/physics.yaml",
        "constant/materials.yaml",
        "constant/chemistry.yaml",
        "0/fields.yaml",
        "0/boundary-conditions.yaml",
        "system/numerics.yaml",
        "system/initialization.yaml",
        "system/monitors.yaml",
        "system/control.yaml",
        "assets.lock.yaml",
    )

    def load(self, source: Path, platform: str | Path | None = None) -> LoadedCase:
        source = source.resolve()
        if source.is_dir() and all((source / item).is_file() for item in self._CANONICAL_FILES):
            try:
                from fluent_case_layer.schema import CaseLoadError
                from fluent_case_layer.schema import load_case as load_typed_case
            except ImportError:
                return DirectoryCaseLoader().load(source, platform)
            try:
                model = load_typed_case(source)
            except CaseLoadError as exc:
                raise CaseValidationError(str(exc)) from exc
            case = dict(to_jsonable(model))
            platforms = case.get("platforms", {})
            default_platform = case.get("control", {}).get("default_platform")
            requested = Path(platform).stem if platform is not None else default_platform
            if requested not in platforms:
                raise CaseValidationError(f"case does not define platform profile {requested!r}")
            return LoadedCase(
                case=case,
                platform=dict(platforms[requested]),
                root=source,
                schema_model="CaseSpec",
            )
        return DirectoryCaseLoader().load(source, platform)


def load_case(
    source: str | Path,
    platform: str | Path | None = None,
    *,
    loader: CaseLoader | None = None,
) -> LoadedCase:
    return (loader or AutoCaseLoader()).load(Path(source), platform)
