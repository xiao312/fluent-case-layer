"""JSON Schema export for editors, CI, and non-Python clients."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .assets import AssetsLock
from .case import CaseSpec
from .chemistry import ChemistryDocument
from .control import ControlDocument
from .fields import BoundaryConditionsDocument, FieldsDocument
from .initialization import InitializationDocument
from .materials import MaterialsDocument
from .monitors import MonitorsDocument
from .numerics import NumericsDocument
from .objectives import EngineeringObjectiveDocument
from .physics import PhysicsDocument
from .platform import PlatformDocument
from .state import StateOwnershipDocument

SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "case-spec.schema.json": CaseSpec,
    "physics.schema.json": PhysicsDocument,
    "materials.schema.json": MaterialsDocument,
    "chemistry.schema.json": ChemistryDocument,
    "fields.schema.json": FieldsDocument,
    "boundary-conditions.schema.json": BoundaryConditionsDocument,
    "numerics.schema.json": NumericsDocument,
    "initialization.schema.json": InitializationDocument,
    "monitors.schema.json": MonitorsDocument,
    "control.schema.json": ControlDocument,
    "objectives.schema.json": EngineeringObjectiveDocument,
    "state.schema.json": StateOwnershipDocument,
    "platform.schema.json": PlatformDocument,
    "assets-lock.schema.json": AssetsLock,
}


def export_json_schemas(output_directory: str | Path) -> list[Path]:
    """Write stable, sorted JSON Schema files and return their paths."""

    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, model in SCHEMA_MODELS.items():
        path = destination / filename
        payload = model.model_json_schema(mode="validation")
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    export_json_schemas(Path(__file__).resolve().parents[3] / "schemas")
