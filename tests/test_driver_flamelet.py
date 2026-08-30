from __future__ import annotations

import ast
import hashlib
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest

from fluent_case_layer.driver.flamelet import (
    FlameletSetupError,
    ProbeAssets,
    resolve_probe_assets,
    run_diffusion_fgm_setup_probe,
)
from fluent_case_layer.schema import CaseSpec, load_case

ROOT = Path(__file__).resolve().parents[1]
CASE_PATH = ROOT / "examples" / "mascotte-g2-jl-fgm" / "case"


class FakeValue:
    def __init__(self, value: object, allowed: list[object] | None = None) -> None:
        self.value = value
        self.allowed = list(allowed or [])

    def get_state(self) -> object:
        return self.value

    def set_state(self, value: object) -> None:
        self.value = value

    def allowed_values(self) -> list[object]:
        return list(self.allowed)


class CallRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


def snapshot(value: object) -> object:
    if isinstance(value, FakeValue):
        return value.get_state()
    if isinstance(value, FakeGroup):
        return value.get_state()
    if isinstance(value, FakeNamedObjects):
        return value.get_state()
    if isinstance(value, Mapping):
        return {str(key): snapshot(child) for key, child in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class FakeGroup(SimpleNamespace):
    def get_state(self) -> dict[str, object]:
        return {
            key: snapshot(value)
            for key, value in vars(self).items()
            if not key.startswith("_") and not callable(value)
        }


class FakeNamedObjects(dict[str, object]):
    def list(self) -> list[str]:
        return list(self)

    def get_state(self) -> dict[str, object]:
        return {name: snapshot(value) for name, value in self.items()}


def make_fake_session() -> tuple[object, CallRecorder, CallRecorder, FakeValue]:
    read_mesh = CallRecorder()
    import_chemkin = CallRecorder()
    species_names = ["ch4", "o2", "co", "h2", "h2o", "o", "h", "oh", "co2"]
    species_boundary = FakeNamedObjects(
        {
            name: FakeGroup(fuel=FakeValue(0.0), oxidizer=FakeValue(0.0))
            for name in species_names
        }
    )
    progress_variable_definition = FakeGroup(
        default_progress_variable=FakeValue(False),
        definition=FakeNamedObjects(),
    )
    boundary = FakeGroup(
        fuel_temperature=FakeValue(300.0),
        oxidizer_temperature=FakeValue(300.0),
        specify_species_in=FakeValue(
            "mole-fraction", ["mass-fraction", "mole-fraction"]
        ),
        species_boundary=species_boundary,
        progress_variable_definition=progress_variable_definition,
    )
    chemistry = FakeGroup(
        state_relation=FakeValue("equilibrium", ["equilibrium", "fgm"]),
        energy_treatment=FakeValue("adia", ["adia", "non-adia"]),
        flamelet_options=FakeValue(
            "read-flamelet", ["read-flamelet", "create-flamelet"]
        ),
        flamelet_type=FakeValue(
            "premixed-flamelet", ["premixed-flamelet", "diffusion-flamelet"]
        ),
        options=FakeGroup(compressibility=FakeValue(False)),
        model_settings=FakeGroup(equilibrium_operating_pressure=FakeValue(101325.0)),
    )
    flamelet = FakeGroup(
        parameters=FakeGroup(
            initial_scalar_dissipation=FakeValue(0.01),
            scalar_dissipation_multiplier=FakeValue(1.5),
            scalar_dissipation_step=FakeValue(0.02),
        ),
        automatic_refinement=FakeValue(True),
        initial_number_grids=FakeValue(16),
        maximum_number_grids=FakeValue(64),
    )
    table = FakeGroup(
        parameters=FakeGroup(
            automatic_grid_refinement=FakeValue(True),
            maximum_grid_points=FakeValue(64),
            maximum_species=FakeValue(9),
            mean_enthalpy_points=FakeValue(41),
            minimum_temperature=FakeValue(70.0),
        )
    )
    premix = FakeGroup(
        turbulence_chemistry_interaction=FakeGroup(
            option=FakeValue("none", ["none", "fr"])
        ),
        variance_settings=FakeGroup(
            variance_method=FakeValue("algebraic", ["algebraic", "solve"])
        ),
    )
    combustion_parameters = FakeGroup(
        probability_density_function=FakeValue("double-delta", ["double-delta", "beta"])
    )
    ppm = FakeGroup(
        chemistry=chemistry,
        boundary=boundary,
        control=FakeGroup(
            initial_fourier_number=FakeValue(0.1),
            relative_tolerance=FakeValue(1.0e-5),
        ),
        flamelet=flamelet,
        table=table,
        premix=premix,
    )
    species = FakeGroup(
        model=FakeGroup(
            option=FakeValue(
                "species-transport",
                ["species-transport", "partially-premixed-combustion"],
            )
        ),
        partially_premixed_model_options=ppm,
        partially_premixed_combustion_parameters=combustion_parameters,
        import_chemkin=import_chemkin,
    )
    density_option = FakeValue(
        "constant", ["constant", "real-gas-soave-redlich-kwong"]
    )
    mixture = FakeGroup(density=FakeGroup(option=density_option))
    setup = FakeGroup(
        general=FakeGroup(
            solver=FakeGroup(
                two_dim_space=FakeValue("planar", ["planar", "axisymmetric"])
            ),
            operating_conditions=FakeGroup(operating_pressure=FakeValue(101325.0)),
        ),
        models=FakeGroup(
            energy=FakeGroup(enabled=FakeValue(False)),
            species=species,
        ),
        materials=FakeGroup(
            mixture=FakeNamedObjects({"mascotte-g2-jl9-fgm": mixture})
        ),
    )
    session = FakeGroup(
        settings=FakeGroup(file=FakeGroup(read_mesh=read_mesh), setup=setup),
        get_fluent_version=lambda: "2026 R1 (26.1.0)",
    )
    return session, read_mesh, import_chemkin, density_option


def test_setup_probe_captures_complete_groups_without_calculating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = load_case(CASE_PATH)
    paths = {
        "g2-medium-mesh": Path("/verified/g2-medium.msh"),
        "jl9-kinetics": Path("/verified/jl9.inp"),
        "jl9-thermodynamics": Path("/verified/jl9-thermo.dat"),
        "jl9-transport": Path("/verified/jl9-transport.dat"),
    }
    monkeypatch.setattr(
        "fluent_case_layer.driver.flamelet.resolve_probe_assets",
        lambda *args, **kwargs: ProbeAssets(
            paths=paths,
            evidence={name: {"verified": True} for name in paths},
            mesh_asset="g2-medium-mesh",
        ),
    )
    session, read_mesh, import_chemkin, density_option = make_fake_session()

    evidence = run_diffusion_fgm_setup_probe(session, case)

    assert read_mesh.calls == [((), {"file_name": "/verified/g2-medium.msh"})]
    assert import_chemkin.calls[0][1]["name"] == "mascotte-g2-jl9-fgm"
    assert density_option.get_state() == "real-gas-soave-redlich-kwong"
    assert evidence["status"] == "setup_readback_complete"
    assert set(evidence["readback"]) == set(
        case.chemistry.model.generation.runtime_defaults.groups
    )
    assert evidence["readback"]["flamelet"]["maximum_number_grids"] == 64
    assert evidence["readback"]["table"]["parameters"]["minimum_temperature"] == 70.0
    assert evidence["flamelet_calculation_performed"] is False
    assert evidence["pdf_calculation_performed"] is False
    assert evidence["table_generation_eligible"] is False


def test_asset_preflight_fails_before_session_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = load_case(CASE_PATH)
    monkeypatch.delenv("MASCOTTE_G2_ASSET_ROOT", raising=False)

    with pytest.raises(FlameletSetupError, match="MASCOTTE_G2_ASSET_ROOT"):
        run_diffusion_fgm_setup_probe(object(), case)


def test_asset_preflight_verifies_every_required_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    case_data = load_case(CASE_PATH).model_dump(mode="json")
    required = {
        "g2-medium-mesh": b"mesh bytes",
        "jl9-kinetics": b"kinetics bytes",
        "jl9-thermodynamics": b"thermo bytes",
        "jl9-transport": b"transport bytes",
    }
    for asset in case_data["assets"]["assets"]:
        payload = required.get(asset["id"])
        if payload is None:
            continue
        path = tmp_path / f"{asset['id']}.bin"
        path.write_bytes(payload)
        asset["source"] = {
            "type": "environment",
            "root_variable": "FCL_G2_PROBE_TEST_ROOT",
            "relative_path": path.name,
        }
        asset["sha256"] = hashlib.sha256(payload).hexdigest()
        asset["size_bytes"] = len(payload)
    case = CaseSpec.model_validate(case_data)
    monkeypatch.setenv("FCL_G2_PROBE_TEST_ROOT", str(tmp_path))

    resolved = resolve_probe_assets(case)

    assert set(resolved.paths) == set(required)
    assert all(item["verified"] for item in resolved.evidence.values())
    (tmp_path / "jl9-kinetics.bin").write_bytes(b"tampered")
    with pytest.raises(FlameletSetupError, match="(size|SHA-256) mismatch"):
        resolve_probe_assets(case)


def test_probe_and_scaffold_have_no_calculation_or_iteration_calls() -> None:
    paths = [
        ROOT / "src" / "fluent_case_layer" / "driver" / "flamelet.py",
        ROOT
        / "examples"
        / "mascotte-g2-jl-fgm"
        / "automation"
        / "setup_readback_smoke.py",
    ]
    forbidden = {"calc_fla", "calc_pdf", "iterate"}

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert called.isdisjoint(forbidden), f"{path} invokes {called & forbidden}"
