from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from fluent_case_layer.schema import CaseLoadError, load_case
from fluent_case_layer.schema.monitors import MonitorsDocument
from fluent_case_layer.schema.objectives import EngineeringObjectiveDocument
from fluent_case_layer.schema.state import StateOwnershipDocument, resolve_json_pointer

CASE_TEMPLATE = Path(__file__).resolve().parents[1] / "case"


def objective_payload() -> dict:
    return {
        "schema_version": "1.0",
        "revision": {
            "id": "objective-r1",
            "sequence": 1,
            "recorded_at": "2026-08-29T12:00:00+08:00",
            "recorded_by": "CFD engineer",
        },
        "provenance": {
            "type": "engineer_statement",
            "author": "CFD engineer",
        },
        "statement": "Understand the flow before selecting the next candidate change.",
        "enforcement": "none",
        "aspects": [],
    }


def locked_reference(asset: str = "checkpoint-case", digest: str = "a" * 64) -> dict:
    return {"asset": asset, "sha256": digest}


def declared(path: str) -> dict:
    return {
        "path": path,
        "source": {
            "type": "case_document",
            "document": "constant/physics.yaml",
            "pointer": "/solver",
        },
    }


def observed(path: str) -> dict:
    return {"path": path, "capture": "exact", "purpose": "verification"}


def copy_case(tmp_path: Path) -> Path:
    destination = tmp_path / "case"
    shutil.copytree(CASE_TEMPLATE, destination)
    return destination


def mutate_yaml(path: Path, transform) -> None:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    transform(payload)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_free_form_objective_can_omit_typed_aspects() -> None:
    objective = EngineeringObjectiveDocument.model_validate(objective_payload())

    assert objective.statement.startswith("Understand")
    assert objective.aspects == []
    assert objective.enforcement == "none"


def test_objective_is_non_enforcing_and_revision_is_timezone_aware() -> None:
    payload = objective_payload()
    payload["enforcement"] = "required"
    with pytest.raises(ValidationError):
        EngineeringObjectiveDocument.model_validate(payload)

    payload = objective_payload()
    payload["revision"]["recorded_at"] = "2026-08-29T12:00:00"
    with pytest.raises(ValidationError, match="timezone"):
        EngineeringObjectiveDocument.model_validate(payload)


def test_experimental_reference_has_compatible_uncertainty() -> None:
    payload = objective_payload()
    payload["aspects"] = [
        {
            "id": "pressure-match",
            "type": "match_reference",
            "description": "Compare mean chamber pressure.",
            "monitor": "chamber-pressure",
            "reference": {
                "type": "experimental_value",
                "label": "experiment",
                "value": {"value": 1.83, "unit": "MPa"},
                "uncertainty": {"value": 0.02, "unit": "bar"},
            },
        }
    ]
    with pytest.raises(ValidationError, match="same unit"):
        EngineeringObjectiveDocument.model_validate(payload)


def test_full_definition_allows_empty_or_cross_observed_ownership() -> None:
    empty = StateOwnershipDocument(
        schema_version="1.0",
        mode="full_definition",
        declared_paths=[],
        observed_paths=[],
    )
    assert empty.baseline is None

    overlapping_across_sets = StateOwnershipDocument(
        schema_version="1.0",
        mode="full_definition",
        declared_paths=[declared("setup.models.energy")],
        observed_paths=[observed("setup.models")],
    )
    assert overlapping_across_sets.observed_paths[0].path == "setup.models"


def test_case_only_checkpoint_overlay_is_valid() -> None:
    state = StateOwnershipDocument(
        schema_version="1.0",
        mode="checkpoint_overlay",
        baseline={"case": locked_reference()},
        declared_paths=[],
        observed_paths=[observed("setup.models")],
    )

    assert state.baseline is not None
    assert state.baseline.data is None


def test_state_mode_controls_baseline_presence() -> None:
    with pytest.raises(ValidationError, match="requires a hash-locked case baseline"):
        StateOwnershipDocument(
            schema_version="1.0",
            mode="checkpoint_overlay",
            declared_paths=[],
            observed_paths=[],
        )

    with pytest.raises(ValidationError, match="cannot declare a checkpoint baseline"):
        StateOwnershipDocument(
            schema_version="1.0",
            mode="full_definition",
            baseline={"case": locked_reference()},
            declared_paths=[],
            observed_paths=[],
        )


@pytest.mark.parametrize("collection", ["declared_paths", "observed_paths"])
def test_state_paths_cannot_overlap_within_one_collection(collection: str) -> None:
    values = (
        [declared("setup.models"), declared("setup.models.energy")]
        if collection == "declared_paths"
        else [observed("setup.models"), observed("setup.models.energy")]
    )
    payload = {
        "schema_version": "1.0",
        "mode": "full_definition",
        "declared_paths": [],
        "observed_paths": [],
    }
    payload[collection] = values

    with pytest.raises(ValidationError, match=f"overlapping {collection.removesuffix('_paths')}"):
        StateOwnershipDocument.model_validate(payload)


def test_rfc6901_pointer_resolves_escaped_keys_and_list_indices() -> None:
    document = {"a/b": [{"~key": 42}]}
    assert resolve_json_pointer(document, "/a~1b/0/~0key") == 42
    assert resolve_json_pointer(document, "") is document


def test_declared_document_pointer_must_resolve_in_parsed_case(tmp_path: Path) -> None:
    root = copy_case(tmp_path)

    def invalid_pointer(data) -> None:
        data["declared_paths"][0]["source"]["pointer"] = "/solver/not-a-setting"

    mutate_yaml(root / "system" / "state.yaml", invalid_pointer)
    with pytest.raises(CaseLoadError, match="source pointer.*does not resolve"):
        load_case(root)


def test_objective_monitor_and_reference_asset_are_cross_validated(tmp_path: Path) -> None:
    root = copy_case(tmp_path)

    def unknown_monitor(data) -> None:
        data["aspects"][0]["monitors"] = ["not-a-monitor"]

    mutate_yaml(root / "system" / "objectives.yaml", unknown_monitor)
    with pytest.raises(CaseLoadError, match="objectives reference unknown monitors"):
        load_case(root)

    root = copy_case(tmp_path / "second")

    def wrong_reference_kind(data) -> None:
        for asset in data["assets"]:
            if asset["id"] == "outlet-pressure-reference":
                asset["kind"] = "other"

    mutate_yaml(root / "assets.lock.yaml", wrong_reference_kind)
    with pytest.raises(CaseLoadError, match="kind=reference_data"):
        load_case(root)


def test_overlay_digest_and_asset_kind_are_cross_validated(tmp_path: Path) -> None:
    root = copy_case(tmp_path)
    case_hash = "b" * 64
    data_hash = "c" * 64

    def add_checkpoint_assets(data) -> None:
        data["assets"].extend(
            [
                {
                    "id": "baseline-case",
                    "kind": "case",
                    "source": {
                        "type": "remote",
                        "uri": "https://example.invalid/checkpoint.cas.h5",
                    },
                    "sha256": case_hash,
                },
                {
                    "id": "baseline-data",
                    "kind": "data",
                    "source": {
                        "type": "remote",
                        "uri": "https://example.invalid/checkpoint.dat.h5",
                    },
                    "sha256": data_hash,
                },
            ]
        )

    mutate_yaml(root / "assets.lock.yaml", add_checkpoint_assets)

    def make_overlay(data) -> None:
        data["mode"] = "checkpoint_overlay"
        data["baseline"] = {
            "case": {"asset": "baseline-case", "sha256": case_hash},
            "data": {"asset": "baseline-data", "sha256": data_hash},
        }

    mutate_yaml(root / "system" / "state.yaml", make_overlay)
    with pytest.raises(CaseLoadError, match="cannot reconcile whole sections"):
        load_case(root)

    def authorize_whole_sections(data) -> None:
        documents = {
            "setup.physics": "constant/physics.yaml",
            "setup.materials": "constant/materials.yaml",
            "setup.chemistry": "constant/chemistry.yaml",
            "solution.fields": "0/fields.yaml",
            "setup.boundaries": "0/boundary-conditions.yaml",
            "solution.numerics": "system/numerics.yaml",
        }
        data["declared_paths"] = [
            {
                "path": path,
                "source": {"type": "case_document", "document": document, "pointer": ""},
            }
            for path, document in documents.items()
        ]

    mutate_yaml(root / "system" / "state.yaml", authorize_whole_sections)
    assert load_case(root).state.mode == "checkpoint_overlay"

    def corrupt_digest(data) -> None:
        data["baseline"]["case"]["sha256"] = "d" * 64

    mutate_yaml(root / "system" / "state.yaml", corrupt_digest)
    with pytest.raises(CaseLoadError, match="digest does not match assets.lock"):
        load_case(root)

    def restore_digest(data) -> None:
        data["baseline"]["case"]["sha256"] = case_hash

    mutate_yaml(root / "system" / "state.yaml", restore_digest)

    def corrupt_kind(data) -> None:
        for asset in data["assets"]:
            if asset["id"] == "baseline-case":
                asset["kind"] = "other"

    mutate_yaml(root / "assets.lock.yaml", corrupt_kind)
    with pytest.raises(CaseLoadError, match="must have kind=case"):
        load_case(root)


def test_objectives_and_state_are_required_documents(tmp_path: Path) -> None:
    root = copy_case(tmp_path)
    (root / "system" / "objectives.yaml").unlink()
    with pytest.raises(CaseLoadError, match="objectives.yaml"):
        load_case(root)


def test_gate_collection_remains_optional() -> None:
    document = MonitorsDocument(schema_version="1.0", monitors=[], gates=[])
    assert document.gates == []
