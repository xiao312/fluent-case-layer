from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from fluent_case_layer.schema import CaseLoadError, export_json_schemas, load_case

CASE_TEMPLATE = Path(__file__).resolve().parents[1] / "case"


def copy_case(tmp_path: Path) -> Path:
    destination = tmp_path / "case"
    shutil.copytree(CASE_TEMPLATE, destination)
    return destination


def mutate_yaml(path: Path, transform) -> None:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    transform(payload)
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_canonical_case_loads_without_fluent() -> None:
    before = set(sys.modules)
    case = load_case(CASE_TEMPLATE)

    assert case.physics.case.id == "illustrative-reacting-flow"
    assert case.control.default_platform == "scnet-cpu-small"
    assert [stage.id for stage in case.control.stages][-1] == "final-checkpoint"
    assert case.assets.assets[0].sha256 == case.assets.assets[0].sha256.lower()
    assert "ansys.fluent.core" not in set(sys.modules) - before
    assert case.model_dump(mode="json")["physics"]["case"]["readiness"] == "illustrative"


def test_schema_export_is_machine_readable(tmp_path: Path) -> None:
    paths = export_json_schemas(tmp_path / "schemas")

    assert len(paths) >= 10
    aggregate = json.loads((tmp_path / "schemas" / "case-spec.schema.json").read_text())
    assert aggregate["title"] == "CaseSpec"
    assert "control" in aggregate["properties"]
    assert (tmp_path / "schemas" / "objectives.schema.json").is_file()
    assert (tmp_path / "schemas" / "state.schema.json").is_file()


def test_bad_sha256_is_rejected_with_path(tmp_path: Path) -> None:
    root = copy_case(tmp_path)
    mutate_yaml(root / "assets.lock.yaml", lambda data: data["assets"][0].update(sha256="bad"))

    with pytest.raises(CaseLoadError, match=r"assets\.lock\.yaml"):
        load_case(root)


def test_unknown_cross_file_asset_is_rejected(tmp_path: Path) -> None:
    root = copy_case(tmp_path)

    def make_unknown(data) -> None:
        data["stages"][0]["asset"] = "missing-mesh"

    mutate_yaml(root / "system" / "control.yaml", make_unknown)
    with pytest.raises(CaseLoadError, match="unknown asset references"):
        load_case(root)


def test_stage_cycle_is_rejected(tmp_path: Path) -> None:
    root = copy_case(tmp_path)

    def add_cycle(data) -> None:
        data["stages"][0]["requires"] = ["final-checkpoint"]

    mutate_yaml(root / "system" / "control.yaml", add_cycle)
    with pytest.raises(CaseLoadError, match="cycle in stage graph"):
        load_case(root)


def test_stage_output_must_come_from_an_ancestor(tmp_path: Path) -> None:
    root = copy_case(tmp_path)

    def invalid_input(data) -> None:
        configure = data["stages"][1]
        configure["inputs"] = [
            {
                "type": "stage_output",
                "name": "future",
                "stage": "sample",
                "output": "sampled-metrics",
            }
        ]

    mutate_yaml(root / "system" / "control.yaml", invalid_input)
    with pytest.raises(CaseLoadError, match="is not an ancestor"):
        load_case(root)


def test_register_must_precede_patch(tmp_path: Path) -> None:
    root = copy_case(tmp_path)

    def reverse_register_and_patch(data) -> None:
        data["actions"][1], data["actions"][2] = data["actions"][2], data["actions"][1]

    mutate_yaml(root / "system" / "initialization.yaml", reverse_register_and_patch)
    with pytest.raises(CaseLoadError, match="before it is created"):
        load_case(root)


def test_platform_filename_must_equal_platform_id(tmp_path: Path) -> None:
    root = copy_case(tmp_path)
    source = root / "platforms" / "scnet-cpu-small.yaml"
    source.rename(root / "platforms" / "renamed.yaml")

    with pytest.raises(CaseLoadError, match="must match platform id"):
        load_case(root)
