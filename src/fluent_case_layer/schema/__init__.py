"""Public schema API; safe to import without PyFluent installed."""

from pathlib import Path

from .case import CaseSpec
from .chemistry import DiffusionFgmSetupProbe, FluentDefaultsProbe
from .loader import CaseLoadError, load_case, load_document
from .objectives import EngineeringObjectiveDocument
from .state import StateOwnershipDocument


def export_json_schemas(output_directory: str | Path) -> list[Path]:
    """Lazily import the exporter so ``python -m ...schema.export`` stays clean."""

    from .export import export_json_schemas as _export_json_schemas

    return _export_json_schemas(output_directory)


__all__ = [
    "CaseLoadError",
    "CaseSpec",
    "DiffusionFgmSetupProbe",
    "EngineeringObjectiveDocument",
    "FluentDefaultsProbe",
    "StateOwnershipDocument",
    "export_json_schemas",
    "load_case",
    "load_document",
]
