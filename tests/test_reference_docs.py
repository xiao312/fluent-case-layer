from __future__ import annotations

import json
from pathlib import Path

from fluent_case_layer.cli import main
from fluent_case_layer.reference import find_entries, get_entry
from fluent_case_layer.reference.catalog import COUPLING_STATUSES, DOCUMENTS, build_catalog
from fluent_case_layer.reference.render import check_outputs

REPOSITORY = Path(__file__).resolve().parents[1]


def test_catalog_covers_every_split_dictionary_with_unique_entries() -> None:
    catalog = build_catalog()
    entries = catalog["entries"]

    assert len(catalog["documents"]) == len(DOCUMENTS) == 13
    assert len(entries) >= 500
    assert len({entry["id"] for entry in entries}) == len(entries)
    assert len(
        {(entry["document"], entry["reference"]["anchor"]) for entry in entries}
    ) == len(entries)
    assert sum(item["entry_count"] for item in catalog["documents"]) == len(entries)
    assert {entry["coupling"]["adapter"]["status"] for entry in entries} <= COUPLING_STATUSES
    assert all(entry["coupling"]["pyfluent"]["option_source"] for entry in entries)


def test_catalog_separates_static_options_from_adapter_support() -> None:
    time_mode = get_entry("constant/physics.yaml#/solver/time")
    assert time_mode["schema"]["choices"] == ["steady", "transient"]
    assert time_mode["coupling"]["pyfluent"] == {
        "confidence": "official",
        "interface": "settings",
        "operation": "set_state",
        "option_source": "runtime_allowed_values",
        "path": "setup.general.solver.time",
    }
    assert time_mode["coupling"]["adapter"]["status"] == "planned"

    iterations = get_entry("system/control.yaml#/stages/*/iterations")
    assert iterations["schema"]["constraints"]["minimum"] == 1
    assert iterations["schema"]["available_in"] == ["/stages/*:type=iterate"]
    assert iterations["coupling"]["adapter"]["status"] == "implemented"


def test_partial_entries_publish_option_specific_support() -> None:
    load_as = get_entry("system/control.yaml#/stages/*/load_as")
    assert load_as["schema"]["choices"] == [
        "case",
        "case_data",
        "chemistry_table",
        "mesh",
        "profile",
    ]
    support = load_as["coupling"]["adapter"]["option_support"]
    assert support["mesh"] == "implemented"
    assert support["chemistry_table"] == "explicit_operations_required"


def test_reference_search_is_filterable_and_deterministic() -> None:
    first = find_entries("run calculation", status="implemented", limit=10)
    second = find_entries("run calculation", status="implemented", limit=10)
    assert first == second
    assert {entry["document"] for entry in first} == {"control"}
    assert any(entry["pointer"] == "/stages/*/iterations" for entry in first)


def test_generated_reference_has_no_drift() -> None:
    assert check_outputs(REPOSITORY) == []


def test_reference_cli_outputs_agent_readable_json(capsys) -> None:
    assert main(["reference", "show", "constant/physics.yaml#/solver/time"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["schema"]["choices"] == ["steady", "transient"]

    assert main(["reference", "list", "--document", "control", "--limit", "2"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 2
    assert all(entry["id"].startswith("system/control.yaml#") for entry in listed["entries"])


def test_reference_cli_rejects_unknown_entry(capsys) -> None:
    assert main(["reference", "show", "missing.yaml#/field"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["error_type"] == "ValueError"
    assert "unknown dictionary entry" in error["error"]
