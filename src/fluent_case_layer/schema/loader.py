"""Load the canonical split directory into one validated :class:`CaseSpec`."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from .assets import AssetsLock
from .case import CaseSpec
from .chemistry import ChemistryDocument
from .control import ControlDocument
from .fields import BoundaryConditionsDocument, FieldsDocument
from .initialization import InitializationDocument
from .materials import MaterialsDocument
from .monitors import MonitorsDocument
from .numerics import NumericsDocument
from .physics import PhysicsDocument
from .platform import PlatformDocument

DocumentT = TypeVar("DocumentT", bound=BaseModel)


class CaseLoadError(ValueError):
    """A path-aware error raised while assembling split case documents."""


DOCUMENTS: dict[str, type[BaseModel]] = {
    "constant/physics.yaml": PhysicsDocument,
    "constant/materials.yaml": MaterialsDocument,
    "constant/chemistry.yaml": ChemistryDocument,
    "0/fields.yaml": FieldsDocument,
    "0/boundary-conditions.yaml": BoundaryConditionsDocument,
    "system/numerics.yaml": NumericsDocument,
    "system/initialization.yaml": InitializationDocument,
    "system/monitors.yaml": MonitorsDocument,
    "system/control.yaml": ControlDocument,
    "assets.lock.yaml": AssetsLock,
}


def _read_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise CaseLoadError(f"required case document is missing: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CaseLoadError(f"cannot read YAML document {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise CaseLoadError(f"case document must contain a YAML mapping: {path}")
    return loaded


def load_document(path: str | Path, model: type[DocumentT]) -> DocumentT:
    """Validate one YAML document with a supplied split-document model."""

    resolved = Path(path)
    try:
        return model.model_validate(_read_mapping(resolved))
    except ValidationError as exc:
        raise CaseLoadError(f"invalid case document {resolved}:\n{exc}") from exc


def load_case(case_directory: str | Path) -> CaseSpec:
    """Load and cross-validate a canonical OpenFOAM-like case directory.

    This function imports no Fluent modules and performs no environment-variable
    expansion or I/O against locked assets.
    """

    root = Path(case_directory).expanduser().resolve()
    if not root.is_dir():
        raise CaseLoadError(f"case directory does not exist: {root}")

    parsed: dict[str, BaseModel] = {}
    for relative_path, model in DOCUMENTS.items():
        parsed[relative_path] = load_document(root / relative_path, model)

    platform_directory = root / "platforms"
    if not platform_directory.is_dir():
        raise CaseLoadError(f"required platform directory is missing: {platform_directory}")
    platform_files = sorted(platform_directory.glob("*.yaml"))
    if not platform_files:
        raise CaseLoadError(f"no platform YAML files found in: {platform_directory}")

    platforms = {}
    for path in platform_files:
        document = load_document(path, PlatformDocument)
        platform = document.platform
        if path.stem != platform.id:
            raise CaseLoadError(
                f"platform filename {path.name!r} must match platform id {platform.id!r}"
            )
        if platform.id in platforms:
            raise CaseLoadError(f"duplicate platform id: {platform.id}")
        platforms[platform.id] = platform

    try:
        return CaseSpec(
            physics=parsed["constant/physics.yaml"],
            materials=parsed["constant/materials.yaml"],
            chemistry=parsed["constant/chemistry.yaml"],
            fields=parsed["0/fields.yaml"],
            boundary_conditions=parsed["0/boundary-conditions.yaml"],
            numerics=parsed["system/numerics.yaml"],
            initialization=parsed["system/initialization.yaml"],
            monitors=parsed["system/monitors.yaml"],
            control=parsed["system/control.yaml"],
            platforms=platforms,
            assets=parsed["assets.lock.yaml"],
        )
    except ValidationError as exc:
        raise CaseLoadError(f"invalid assembled case {root}:\n{exc}") from exc
