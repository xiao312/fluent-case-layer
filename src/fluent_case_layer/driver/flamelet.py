"""Fail-closed Fluent diffusion-FGM setup and readback support.

The module deliberately stops before ``calc_fla`` or ``calc_pdf``.  It exists to
turn Fluent 2026 R1 runtime defaults into reviewable evidence for an exploratory
profile; it is not a historical-table reconstruction and cannot create a table.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fluent_case_layer.schema.assets import (
    EnvironmentAssetSource,
    RemoteAssetSource,
    RepositoryAssetSource,
)
from fluent_case_layer.schema.case import CaseSpec
from fluent_case_layer.schema.chemistry import AssetMechanism, FlameletChemistry
from fluent_case_layer.schema.control import LoadAssetStage

from .errors import DriverError
from .util import file_sha256, stable_hash, to_jsonable

_SPECIES_OPTION = "partially-premixed-combustion"
_SRK_OPTION = "real-gas-soave-redlich-kwong"
_PDF_OPTION = "beta"
_PDF_FLUENT_NAME = "probability-density-function"
_PDF_SETTINGS_PATH = (
    "setup/models/species/partially-premixed-combustion-parameters/probability-density-function"
)
_PDF_RAW_ATTRS = ("active?", "read-only?", "allowed-values")
_PDF_STATIC_ENUM = ["double-delta", "beta"]


class FlameletSetupError(DriverError):
    """Raised before an incomplete or ambiguous flamelet operation can proceed."""


class ProbabilityDensityFunctionProbeError(FlameletSetupError):
    """Raised with structured evidence when the PDF selection cannot be proven."""

    def __init__(self, message: str, evidence: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.probe_evidence = {
            "probability_density_function_evidence": dict(evidence),
        }


@dataclass(frozen=True, slots=True)
class FlameletTableReadiness:
    ready: bool
    mode: str
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ProbeAssets:
    paths: Mapping[str, Path]
    evidence: Mapping[str, Mapping[str, Any]]
    mesh_asset: str


def assess_flamelet_table_readiness(case: CaseSpec) -> FlameletTableReadiness:
    """Report whether a case has a table that may be used for a flow solve."""

    model = case.chemistry.model
    if not isinstance(model, FlameletChemistry):
        return FlameletTableReadiness(
            ready=False,
            mode="not_flamelet",
            blockers=("case chemistry is not a flamelet model",),
        )
    if model.table_mode == "read":
        if model.table_asset is None:  # protected by schema, retained as a safety boundary
            return FlameletTableReadiness(
                ready=False,
                mode="read",
                blockers=("no hash-locked PDF table asset is declared",),
            )
        asset = case.assets.by_id().get(model.table_asset)
        if asset is None or asset.kind != "table":
            return FlameletTableReadiness(
                ready=False,
                mode="read",
                blockers=("the declared flamelet table is absent or is not kind=table",),
            )
        return FlameletTableReadiness(ready=True, mode="read", blockers=())
    if model.generation is None:
        return FlameletTableReadiness(
            ready=False,
            mode="calculate",
            blockers=("table calculation has no typed generation definition",),
        )
    return FlameletTableReadiness(
        ready=False,
        mode=model.generation.execution_scope,
        blockers=(
            "the selected profile is setup_readback_only",
            "Fluent runtime defaults must be captured, reviewed, and frozen",
            "no hash-locked G2 JL-FGM PDF table exists",
        ),
    )


def require_flamelet_table_ready(case: CaseSpec) -> None:
    """Fail before launch when a solve would rely on an unavailable table."""

    readiness = assess_flamelet_table_readiness(case)
    if not readiness.ready:
        raise FlameletSetupError(
            "flamelet table is not execution-ready: " + "; ".join(readiness.blockers)
        )


def _required_probe_asset_ids(case: CaseSpec) -> tuple[list[str], str]:
    model = case.chemistry.model
    if not isinstance(model, FlameletChemistry) or model.generation is None:
        raise FlameletSetupError("case has no typed Fluent diffusion-FGM setup probe")
    mechanism = model.mechanism
    if not isinstance(mechanism, AssetMechanism):
        raise FlameletSetupError("setup probe requires an asset-backed mechanism")
    chemistry_ids = [
        mechanism.mechanism_asset,
        mechanism.thermodynamics_asset,
        mechanism.transport_asset,
    ]
    if any(identifier is None for identifier in chemistry_ids):
        raise FlameletSetupError("setup probe requires kinetics, thermodynamics, and transport")
    mesh_stages = [
        stage
        for stage in case.control.stages
        if isinstance(stage, LoadAssetStage) and stage.load_as == "mesh"
    ]
    if len(mesh_stages) != 1:
        raise FlameletSetupError("setup probe requires exactly one load_asset(mesh) stage")
    return [str(identifier) for identifier in chemistry_ids], mesh_stages[0].asset


def resolve_probe_assets(
    case: CaseSpec,
    *,
    repository_root: str | Path | None = None,
) -> ProbeAssets:
    """Resolve and hash-check every byte needed by the setup probe."""

    chemistry_ids, mesh_id = _required_probe_asset_ids(case)
    required_ids = [mesh_id, *chemistry_ids]
    by_id = case.assets.by_id()
    paths: dict[str, Path] = {}
    evidence: dict[str, Mapping[str, Any]] = {}
    for identifier in required_ids:
        asset = by_id[identifier]
        source = asset.source
        if isinstance(source, EnvironmentAssetSource):
            root = os.environ.get(source.root_variable)
            if not root:
                raise FlameletSetupError(
                    f"asset {identifier!r} requires environment variable {source.root_variable}"
                )
            path = Path(root) / source.relative_path
        elif isinstance(source, RepositoryAssetSource):
            if repository_root is None:
                raise FlameletSetupError(
                    f"asset {identifier!r} is repository-relative; repository_root is required"
                )
            path = Path(repository_root) / source.path
        elif isinstance(source, RemoteAssetSource):
            raise FlameletSetupError(
                f"asset {identifier!r} requires an external content-addressed materializer"
            )
        else:  # pragma: no cover - discriminated union exhaustiveness guard
            raise FlameletSetupError(f"unsupported source for asset {identifier!r}")
        if not path.is_file():
            raise FlameletSetupError(f"required asset is absent: {identifier} -> {path}")
        observed_size = path.stat().st_size
        if asset.size_bytes is not None and observed_size != asset.size_bytes:
            raise FlameletSetupError(
                f"asset size mismatch for {identifier}: expected {asset.size_bytes}, "
                f"got {observed_size}"
            )
        observed_hash = file_sha256(path)
        if observed_hash != asset.sha256:
            raise FlameletSetupError(
                f"asset SHA-256 mismatch for {identifier}: expected {asset.sha256}, "
                f"got {observed_hash}"
            )
        paths[identifier] = path.resolve()
        evidence[identifier] = {
            "kind": asset.kind,
            "sha256": observed_hash,
            "size_bytes": observed_size,
            "verified": True,
        }
    return ProbeAssets(paths=paths, evidence=evidence, mesh_asset=mesh_id)


def _state(node: Any) -> Any:
    getter = getattr(node, "get_state", None)
    value = getter() if callable(getter) else node
    try:
        return to_jsonable(value)
    except TypeError as exc:
        raise FlameletSetupError(f"Fluent state is not serializable: {exc}") from exc


def _allowed(node: Any) -> list[Any]:
    getter = getattr(node, "allowed_values", None)
    if not callable(getter):
        return []
    try:
        return list(getter())
    except Exception as exc:
        raise FlameletSetupError(f"cannot read Fluent allowed values: {exc}") from exc


def _capture_evidence(call: Any) -> dict[str, Any]:
    """Capture a read-only query without collapsing an exception into an empty value."""

    try:
        return {"status": "ok", "value": to_jsonable(call())}
    except Exception as exc:  # noqa: BLE001 - preserve arbitrary RPC failures as evidence.
        return {
            "status": "error",
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }


def _query_allowed_values(node: Any) -> list[Any] | None:
    getter = getattr(node, "allowed_values", None)
    if not callable(getter):
        raise TypeError("setting has no allowed_values query")
    values = getter()
    if values is None:
        return None
    if not isinstance(values, list):
        raise TypeError(
            f"Fluent allowed_values() must return a list or None, got {type(values).__name__}"
        )
    return values


def _query_raw_attrs(node: Any) -> Mapping[str, Any]:
    getter = getattr(node, "get_attrs", None)
    if not callable(getter):
        raise TypeError("setting has no get_attrs query")
    response = getter(list(_PDF_RAW_ATTRS))
    if not isinstance(response, Mapping):
        raise TypeError(f"Fluent get_attrs() must return an object, got {type(response).__name__}")
    attrs = response.get("attrs", response)
    if not isinstance(attrs, Mapping):
        raise TypeError("Fluent get_attrs() did not contain an attribute object")
    return {
        "requested": list(_PDF_RAW_ATTRS),
        "response": response,
        "attrs": attrs,
    }


def _enum_text(value: Any) -> str | None:
    if value is None:
        return None
    inner = getattr(value, "value", value)
    return str(inner)


def _generated_pdf_schema(node: Any) -> Mapping[str, Any]:
    cls = type(node)
    allowed = getattr(cls, "_allowed_values", None)
    if allowed is not None and not isinstance(allowed, list):
        raise TypeError("generated _allowed_values is not a list")
    return {
        "module": cls.__module__,
        "class": cls.__name__,
        "version": str(getattr(cls, "_version", "")),
        "exposure_level": _enum_text(getattr(cls, "exposure_level", None)),
        "fluent_name": getattr(cls, "fluent_name", None),
        "python_name": getattr(cls, "_python_name", None),
        "path": getattr(node, "path", None),
        "python_path": getattr(node, "python_path", None),
        "beta_constant": _enum_text(getattr(cls, "BETA", None)),
        "allowed_values": list(allowed or []),
    }


def _runtime_static_pdf_schema(node: Any) -> Mapping[str, Any]:
    proxy = getattr(node, "flproxy", None)
    getter = getattr(proxy, "get_static_info", None)
    if not callable(getter):
        raise TypeError("setting proxy has no get_static_info query")
    root = getter()
    if not isinstance(root, Mapping):
        raise TypeError("Fluent get_static_info() did not return an object")
    path = getattr(node, "path", None)
    if not isinstance(path, str) or not path:
        raise TypeError("setting has no Fluent path")
    components = [component for component in path.split("/") if component]
    if components and components[0] == "fluent":
        components.pop(0)
    current: Mapping[str, Any] = root
    for component in components:
        children = current.get("children")
        if not isinstance(children, Mapping) or component not in children:
            raise KeyError(f"runtime static info omits {component!r} in path {path!r}")
        child = children[component]
        if not isinstance(child, Mapping):
            raise TypeError(f"runtime static info node {component!r} is not an object")
        current = child
    return {"path": path, "node": current}


def _capture_value(capture: Mapping[str, Any]) -> Any:
    return capture.get("value") if capture.get("status") == "ok" else None


def _parent_pdf_value(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return None
    for key in ("probability_density_function", "probability-density-function"):
        if key in value:
            return value[key]
    return None


def _is_2026_r1(version: str) -> bool:
    normalized = re.sub(r"[^a-z0-9.]", "", version.casefold())
    return any(token in normalized for token in ("26.1", "2026r1", "v261"))


def _pdf_probe_failure(message: str, evidence: dict[str, Any]) -> None:
    evidence["decision"] = {
        **dict(evidence.get("decision", {})),
        "status": "blocked",
        "reason": message,
    }
    raise ProbabilityDensityFunctionProbeError(message, evidence)


def _select_probability_density_function(
    node: Any,
    parent: Any,
    expected: str,
    *,
    fluent_version: str,
) -> Mapping[str, Any]:
    """Select beta once using static v261 evidence, or accept an exact no-op.

    ``AllowedValuesMixin.allowed_values()`` in PyFluent 0.40.2 turns every
    exception into ``[]``.  This probe therefore records the helper result, raw
    dynamic attributes, generated v261 schema, and server static-info subtree as
    separate evidence channels before making a decision.
    """

    evidence: dict[str, Any] = {
        "schema_version": "1",
        "requested": expected,
        "runtime_version": fluent_version,
        "allowed_values_helper": _capture_evidence(lambda: _query_allowed_values(node)),
        "raw_attrs": _capture_evidence(lambda: _query_raw_attrs(node)),
        "current_state_before": _capture_evidence(lambda: _state(node)),
        "parent_state_before": _capture_evidence(lambda: _state(parent)),
        "generated_v261_schema": _capture_evidence(lambda: _generated_pdf_schema(node)),
        "runtime_static_info": _capture_evidence(lambda: _runtime_static_pdf_schema(node)),
    }
    if expected != _PDF_OPTION:
        _pdf_probe_failure(
            f"PDF metadata probe only permits {_PDF_OPTION!r}, got {expected!r}",
            evidence,
        )

    helper_values = _capture_value(evidence["allowed_values_helper"])
    raw_value = _capture_value(evidence["raw_attrs"])
    raw_attrs = raw_value.get("attrs", {}) if isinstance(raw_value, Mapping) else {}
    raw_allowed = raw_attrs.get("allowed-values")
    live_lists = [
        values for values in (helper_values, raw_allowed) if isinstance(values, list) and values
    ]
    live_enum_conflict = any(expected not in values for values in live_lists)

    generated = _capture_value(evidence["generated_v261_schema"])
    generated_path = generated.get("path") if isinstance(generated, Mapping) else None
    if isinstance(generated_path, str):
        generated_path = generated_path.removeprefix("fluent/")
    generated_valid = bool(
        isinstance(generated, Mapping)
        and generated.get("module") == "ansys.fluent.core.generated.solver.settings_261"
        and generated.get("class") == "probability_density_function"
        and generated.get("version") == "261"
        and generated.get("exposure_level") == "stable"
        and generated.get("fluent_name") == _PDF_FLUENT_NAME
        and generated.get("python_name") == "probability_density_function"
        and generated_path == _PDF_SETTINGS_PATH
        and generated.get("beta_constant") == expected
        and generated.get("allowed_values") == _PDF_STATIC_ENUM
    )

    runtime_static = _capture_value(evidence["runtime_static_info"])
    runtime_node = runtime_static.get("node") if isinstance(runtime_static, Mapping) else None
    runtime_path = runtime_static.get("path") if isinstance(runtime_static, Mapping) else None
    if isinstance(runtime_path, str):
        runtime_path = runtime_path.removeprefix("fluent/")
    runtime_allowed = None
    if isinstance(runtime_node, Mapping):
        runtime_allowed = runtime_node.get("allowed-values", runtime_node.get("allowed_values"))
    runtime_static_valid = bool(
        isinstance(runtime_node, Mapping)
        and runtime_path == _PDF_SETTINGS_PATH
        and runtime_node.get("type") == "string"
        and runtime_node.get("has-allowed-values") is True
        and runtime_allowed == _PDF_STATIC_ENUM
    )

    current_before = _capture_value(evidence["current_state_before"])
    parent_before = _capture_value(evidence["parent_state_before"])
    preconditions = {
        "current_state_captured": evidence["current_state_before"]["status"] == "ok",
        "parent_state_captured": evidence["parent_state_before"]["status"] == "ok",
        "raw_attrs_captured": evidence["raw_attrs"]["status"] == "ok",
        "raw_allowed_values_valid": raw_allowed is None or isinstance(raw_allowed, list),
        "runtime_2026_r1": _is_2026_r1(fluent_version),
        "active": raw_attrs.get("active?") is True,
        "writable": raw_attrs.get("read-only?") is False,
        "generated_v261_schema": generated_valid,
        "runtime_static_info": runtime_static_valid,
        "no_live_enum_conflict": not live_enum_conflict,
    }
    preconditions["setter_authorized"] = all(preconditions.values())
    evidence["preconditions"] = preconditions

    if live_enum_conflict:
        _pdf_probe_failure(
            "live Fluent metadata explicitly excludes probability density function='beta'",
            evidence,
        )

    if current_before == expected:
        if _parent_pdf_value(parent_before) != expected:
            _pdf_probe_failure(
                "PDF leaf is beta but parent-group readback does not confirm beta",
                evidence,
            )
        evidence["current_state_after"] = _capture_evidence(lambda: _state(node))
        evidence["parent_state_after"] = _capture_evidence(lambda: _state(parent))
        if (
            _capture_value(evidence["current_state_after"]) != expected
            or _parent_pdf_value(_capture_value(evidence["parent_state_after"])) != expected
        ):
            _pdf_probe_failure("exact beta no-op did not remain stable on readback", evidence)
        evidence["decision"] = {
            "status": "selected",
            "mode": "existing_state_noop",
            "setter_calls": 0,
        }
        return evidence

    if evidence["current_state_before"]["status"] != "ok":
        _pdf_probe_failure("cannot read current PDF state before selection", evidence)
    if not preconditions["setter_authorized"]:
        failed = sorted(
            name
            for name, passed in preconditions.items()
            if name != "setter_authorized" and not passed
        )
        _pdf_probe_failure(
            "PDF beta setter preconditions failed: " + ", ".join(failed),
            evidence,
        )

    setter = getattr(node, "set_state", None)
    if not callable(setter):
        _pdf_probe_failure("PDF setting has no set_state method", evidence)
    evidence["decision"] = {
        "status": "setting",
        "mode": "single_set_readback",
        "setter_calls": 1,
    }
    try:
        setter(expected)
    except Exception as exc:  # noqa: BLE001 - Fluent setters raise multiple RPC types.
        evidence["decision"]["setter_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        _pdf_probe_failure("single exact PDF beta setter call failed", evidence)

    evidence["current_state_after"] = _capture_evidence(lambda: _state(node))
    evidence["parent_state_after"] = _capture_evidence(lambda: _state(parent))
    if _capture_value(evidence["current_state_after"]) != expected:
        _pdf_probe_failure("PDF beta leaf readback differs after the setter", evidence)
    if _parent_pdf_value(_capture_value(evidence["parent_state_after"])) != expected:
        _pdf_probe_failure("PDF beta parent-group readback differs after the setter", evidence)
    evidence["decision"] = {
        "status": "selected",
        "mode": "single_set_readback",
        "setter_calls": 1,
    }
    return evidence


def _pdf_reported_allowed_values(evidence: Mapping[str, Any]) -> list[Any]:
    raw = _capture_value(evidence.get("raw_attrs", {}))
    raw_attrs = raw.get("attrs", {}) if isinstance(raw, Mapping) else {}
    raw_values = raw_attrs.get("allowed-values")
    helper_values = _capture_value(evidence.get("allowed_values_helper", {}))
    for values in (raw_values, helper_values):
        if isinstance(values, list) and values:
            return list(values)
    for values in (raw_values, helper_values):
        if isinstance(values, list):
            return list(values)
    return []


def _matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1.0e-10)
    return actual == expected


def _set_exact(node: Any, expected: Any, label: str, *, require_allowed: bool = False) -> Any:
    allowed = _allowed(node)
    if require_allowed and expected not in allowed:
        raise FlameletSetupError(
            f"Fluent does not expose exact {label}={expected!r}; allowed values are {allowed!r}"
        )
    setter = getattr(node, "set_state", None)
    try:
        if callable(setter):
            setter(expected)
        else:
            raise TypeError("setting has no set_state")
    except Exception as exc:
        raise FlameletSetupError(f"cannot set exact {label}={expected!r}: {exc}") from exc
    actual = _state(node)
    if not _matches(actual, expected):
        raise FlameletSetupError(
            f"Fluent readback differs for {label}: expected {expected!r}, got {actual!r}"
        )
    return actual


def _object_names(container: Any) -> list[str]:
    # In Fluent 2026 R1, ``NamedObject.list()`` is a print command routed through
    # the settings root and returns ``None``.  ``get_object_names()`` is the
    # programmatic readback API backed by ``flproxy.get_object_names(path)``.
    getter = getattr(container, "get_object_names", None)
    if callable(getter):
        try:
            values = getter()
        except Exception as exc:
            raise FlameletSetupError(f"cannot read Fluent named-object names: {exc}") from exc
        if not isinstance(values, list):
            raise FlameletSetupError("Fluent get_object_names() did not return the required list")
    elif isinstance(container, Mapping):
        values = list(container)
    else:
        raise FlameletSetupError("Fluent named-object container does not expose get_object_names()")

    if not values:
        raise FlameletSetupError("Fluent named-object container returned no object names")
    if not all(isinstance(value, str) and value for value in values):
        raise FlameletSetupError("Fluent named-object names must be non-empty strings")
    if len(values) != len(set(values)):
        raise FlameletSetupError("Fluent named-object names must be unique")
    return values


def _require_2026_r1(session: Any) -> str:
    getter = getattr(session, "get_fluent_version", None)
    if not callable(getter):
        raise FlameletSetupError("Fluent session does not expose get_fluent_version")
    version = str(getter())
    if not _is_2026_r1(version):
        raise FlameletSetupError(
            f"setup probe is locked to Fluent 2026 R1, but session reports {version!r}"
        )
    return version


def _set_stream_compositions(boundary: Any, case: CaseSpec) -> Mapping[str, Any]:
    model = case.chemistry.model
    assert isinstance(model, FlameletChemistry) and model.generation is not None
    generation = model.generation
    fuel = case.chemistry.streams[generation.fuel_stream]
    oxidizer = case.chemistry.streams[generation.oxidizer_stream]
    if fuel.composition.basis != oxidizer.composition.basis:
        raise FlameletSetupError("FGM fuel and oxidizer composition bases must match")
    basis = {
        "mass_fraction": "mass-fraction",
        "mole_fraction": "mole-fraction",
    }[fuel.composition.basis]
    _set_exact(boundary.fuel_temperature, fuel.temperature.value, "fuel temperature")
    _set_exact(
        boundary.oxidizer_temperature,
        oxidizer.temperature.value,
        "oxidizer temperature",
    )
    _set_exact(
        boundary.specify_species_in,
        basis,
        "flamelet composition basis",
        require_allowed=True,
    )
    species_boundary = boundary.species_boundary
    exposed = _object_names(species_boundary)
    by_fold = {name.casefold(): name for name in exposed}
    requested = set(fuel.composition.fractions) | set(oxidizer.composition.fractions)
    missing = sorted(name for name in requested if name.casefold() not in by_fold)
    if missing:
        raise FlameletSetupError(
            "Fluent flamelet boundary omits requested species: " + ", ".join(missing)
        )
    fuel_fractions = {name.casefold(): value for name, value in fuel.composition.fractions.items()}
    oxidizer_fractions = {
        name.casefold(): value for name, value in oxidizer.composition.fractions.items()
    }
    for exposed_name in exposed:
        key = exposed_name.casefold()
        _set_exact(
            species_boundary[exposed_name].fuel,
            fuel_fractions.get(key, 0.0),
            f"fuel fraction {exposed_name}",
        )
        _set_exact(
            species_boundary[exposed_name].oxidizer,
            oxidizer_fractions.get(key, 0.0),
            f"oxidizer fraction {exposed_name}",
        )
    return {
        "basis": basis,
        "fuel": dict(fuel.composition.fractions),
        "oxidizer": dict(oxidizer.composition.fractions),
        "exposed_species": exposed,
    }


def _run_diffusion_fgm_setup_probe(
    session: Any,
    case: CaseSpec,
    *,
    repository_root: str | Path | None = None,
    diagnostics: dict[str, Any],
) -> Mapping[str, Any]:
    """Configure and serialize an exploratory setup, without generating a table.

    All asset validation happens before the first Fluent mutation.  The function has
    no code path that invokes flamelet or PDF calculation commands.
    """

    model = case.chemistry.model
    if not isinstance(model, FlameletChemistry) or model.generation is None:
        raise FlameletSetupError("case does not select a typed diffusion-FGM setup probe")
    generation = model.generation
    if generation.execution_scope != "setup_readback_only":  # schema guard plus defense in depth
        raise FlameletSetupError("this runner permits setup_readback_only profiles")
    if generation.table_generation_permission != "prohibited":
        raise FlameletSetupError("this runner requires table_generation_permission=prohibited")
    assets = resolve_probe_assets(case, repository_root=repository_root)
    version = _require_2026_r1(session)

    settings = session.settings
    settings.file.read_mesh(file_name=str(assets.paths[assets.mesh_asset]))
    setup = settings.setup
    _set_exact(
        setup.general.solver.two_dim_space,
        "axisymmetric",
        "two-dimensional space",
        require_allowed=True,
    )
    _set_exact(
        setup.general.operating_conditions.operating_pressure,
        generation.equilibrium_operating_pressure.value,
        "operating pressure",
    )
    _set_exact(setup.models.energy.enabled, True, "energy model")

    species = setup.models.species
    _set_exact(
        species.model.option,
        _SPECIES_OPTION,
        "species model",
        require_allowed=True,
    )
    ppm = species.partially_premixed_model_options
    chemistry = ppm.chemistry
    chemistry_requests = {
        "state_relation": "fgm",
        "energy_treatment": "non-adia",
        "flamelet_options": "create-flamelet",
        "flamelet_type": "diffusion-flamelet",
    }
    for name, expected in chemistry_requests.items():
        _set_exact(
            getattr(chemistry, name),
            expected,
            f"chemistry {name}",
            require_allowed=True,
        )
    _set_exact(chemistry.options.compressibility, True, "PDF compressibility")
    _set_exact(
        chemistry.model_settings.equilibrium_operating_pressure,
        generation.equilibrium_operating_pressure.value,
        "FGM equilibrium operating pressure",
    )

    mechanism = model.mechanism
    assert isinstance(mechanism, AssetMechanism)
    species.import_chemkin(
        kinetics_input_file=str(assets.paths[mechanism.mechanism_asset]),
        thermodb_input_file=str(assets.paths[str(mechanism.thermodynamics_asset)]),
        trans_input_file=str(assets.paths[str(mechanism.transport_asset)]),
        surf_mech=False,
        trans_prop=True,
        surfchem_input_file="",
        name=generation.mixture_name,
    )

    # Mechanism import can recreate active settings nodes, so every node is acquired
    # again before the final exact setters and complete-group readback.
    species = setup.models.species
    _set_exact(
        species.model.option,
        _SPECIES_OPTION,
        "post-import species model",
        require_allowed=True,
    )
    ppm = species.partially_premixed_model_options
    chemistry = ppm.chemistry
    for name, expected in chemistry_requests.items():
        _set_exact(
            getattr(chemistry, name),
            expected,
            f"post-import chemistry {name}",
            require_allowed=True,
        )
    _set_exact(chemistry.options.compressibility, True, "post-import PDF compressibility")
    _set_exact(
        chemistry.model_settings.equilibrium_operating_pressure,
        generation.equilibrium_operating_pressure.value,
        "post-import FGM equilibrium operating pressure",
    )
    stream_readback = _set_stream_compositions(ppm.boundary, case)
    progress_definition = ppm.boundary.progress_variable_definition
    _set_exact(
        progress_definition.default_progress_variable,
        True,
        "default progress-variable definition",
    )

    # Grid, scalar-dissipation, integration, enthalpy, table-resolution, and
    # minimum-temperature controls are intentionally left at the active 2026 R1
    # runtime state and captured below.  The source paper does not identify an
    # unambiguous Fluent-node mapping for these values, so choosing numbers here
    # would turn a discovery smoke into an undocumented table recipe.
    _set_exact(
        ppm.premix.turbulence_chemistry_interaction.option,
        "fr",
        "FGM turbulence-chemistry interaction",
        require_allowed=True,
    )
    _set_exact(
        ppm.premix.variance_settings.variance_method,
        "solve",
        "progress-variable variance method",
        require_allowed=True,
    )
    combustion_parameters = species.partially_premixed_combustion_parameters
    pdf_evidence = _select_probability_density_function(
        combustion_parameters.probability_density_function,
        combustion_parameters,
        generation.probability_density_function,
        fluent_version=version,
    )
    diagnostics["probability_density_function_evidence"] = pdf_evidence

    mixtures = setup.materials.mixture
    mixture_names = _object_names(mixtures)
    if generation.mixture_name not in mixture_names:
        raise FlameletSetupError(
            f"CHEMKIN import did not create exact mixture {generation.mixture_name!r}; "
            f"available mixtures are {mixture_names!r}"
        )
    density = mixtures[generation.mixture_name].density
    density_option = getattr(density, "option", None)
    if density_option is None:
        density_option = getattr(density, "model", None)
    if density_option is None:
        raise FlameletSetupError("Fluent mixture density has no selectable EOS node")
    _set_exact(
        density_option,
        _SRK_OPTION,
        "mixture density EOS",
        require_allowed=True,
    )

    group_nodes = {
        "chemistry": chemistry,
        "boundary": ppm.boundary,
        "progress_variable_definition": progress_definition,
        "control": ppm.control,
        "flamelet": ppm.flamelet,
        "table": ppm.table,
        "premix": ppm.premix,
        "combustion_parameters": combustion_parameters,
        "material_density": density,
    }
    requested_groups = generation.runtime_defaults.groups
    readback = {name: _state(group_nodes[name]) for name in requested_groups}
    incomplete = sorted(
        name for name, value in readback.items() if not isinstance(value, Mapping) or not value
    )
    if incomplete:
        raise FlameletSetupError(
            "Fluent returned incomplete runtime-default group state: " + ", ".join(incomplete)
        )
    allowed_values = {
        "species_model": _allowed(species.model.option),
        "state_relation": _allowed(chemistry.state_relation),
        "energy_treatment": _allowed(chemistry.energy_treatment),
        "flamelet_options": _allowed(chemistry.flamelet_options),
        "flamelet_type": _allowed(chemistry.flamelet_type),
        "composition_basis": _allowed(ppm.boundary.specify_species_in),
        "turbulence_chemistry_interaction": _allowed(
            ppm.premix.turbulence_chemistry_interaction.option
        ),
        "variance_method": _allowed(ppm.premix.variance_settings.variance_method),
        "probability_density_function": _pdf_reported_allowed_values(pdf_evidence),
        "density_eos": _allowed(density_option),
    }
    empty_allowed_values = sorted(
        name
        for name, values in allowed_values.items()
        if name != "probability_density_function" and not values
    )
    if empty_allowed_values:
        raise FlameletSetupError(
            "Fluent returned no allowed-value evidence for: " + ", ".join(empty_allowed_values)
        )
    return {
        "schema_version": "1",
        "case_id": case.physics.case.id,
        "case_digest": stable_hash(case),
        "fluent_version": version,
        "classification": generation.classification,
        "execution_scope": generation.execution_scope,
        "table_generation_permission": generation.table_generation_permission,
        "status": "setup_readback_complete",
        "assets": dict(assets.evidence),
        "requested_generation": generation.model_dump(mode="json"),
        "stream_configuration": stream_readback,
        "probability_density_function_evidence": pdf_evidence,
        "readback": readback,
        "allowed_values": allowed_values,
        "flamelet_calculation_performed": False,
        "pdf_calculation_performed": False,
        "table_generation_eligible": False,
        "next_required_action": (
            "Review and freeze every captured runtime value in a new explicit "
            "table-generation revision before enabling calc_fla or calc_pdf."
        ),
    }


def run_diffusion_fgm_setup_probe(
    session: Any,
    case: CaseSpec,
    *,
    repository_root: str | Path | None = None,
) -> Mapping[str, Any]:
    """Configure and serialize an exploratory setup without generating a table.

    Structured PDF metadata survives later setup failures so a failed Wuzhen
    attempt does not lose the evidence needed to diagnose its exact boundary.
    """

    diagnostics: dict[str, Any] = {}
    try:
        return _run_diffusion_fgm_setup_probe(
            session,
            case,
            repository_root=repository_root,
            diagnostics=diagnostics,
        )
    except FlameletSetupError as exc:
        if diagnostics and not hasattr(exc, "probe_evidence"):
            exc.probe_evidence = dict(diagnostics)
        raise
