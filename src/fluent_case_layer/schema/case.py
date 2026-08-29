"""Aggregate case model and cross-document semantic validation."""

from __future__ import annotations

from pydantic import model_validator

from .assets import AssetsLock, LockedAsset
from .chemistry import (
    AssetMechanism,
    ChemistryDocument,
    FiniteRateChemistry,
    FlameletChemistry,
    NoChemistry,
)
from .common import (
    AssetAvailableCondition,
    AssetInput,
    Identifier,
    MetricCondition,
    ProfileValue,
    StrictModel,
)
from .control import (
    AdvanceTimeStage,
    CheckpointStage,
    ControlDocument,
    GatePromotion,
    GateStage,
    InitializeStage,
    LoadAssetStage,
    ReconcileStage,
    SampleStage,
)
from .fields import (
    BoundaryConditionsDocument,
    FieldsDocument,
    FixedHeatFluxWall,
    FixedTemperatureWall,
    MassFlowInlet,
    PressureOutlet,
    VelocityInlet,
    WallBoundary,
)
from .initialization import InitializationDocument, PatchAction, ReadCheckpointAction
from .materials import MaterialsDocument
from .monitors import ArtifactGate, MonitorsDocument
from .numerics import NumericsDocument
from .objectives import (
    DirectionalAspect,
    EngineeringObjectiveDocument,
    InvestigateAspect,
    MatchReferenceAspect,
    ObserveAspect,
    ReferenceAsset,
    SourceAssetProvenance,
)
from .physics import PhysicsDocument
from .platform import PlatformSpec
from .state import CaseDocumentStateSource, StateOwnershipDocument, resolve_json_pointer

RECONCILE_SECTION_DOCUMENTS = {
    "physics": "constant/physics.yaml",
    "materials": "constant/materials.yaml",
    "chemistry": "constant/chemistry.yaml",
    "fields": "0/fields.yaml",
    "boundary_conditions": "0/boundary-conditions.yaml",
    "numerics": "system/numerics.yaml",
}


class CaseSpec(StrictModel):
    """A fully assembled, cross-file-validated Fluent case intent."""

    physics: PhysicsDocument
    materials: MaterialsDocument
    chemistry: ChemistryDocument
    fields: FieldsDocument
    boundary_conditions: BoundaryConditionsDocument
    numerics: NumericsDocument
    initialization: InitializationDocument
    monitors: MonitorsDocument
    control: ControlDocument
    objectives: EngineeringObjectiveDocument
    state: StateOwnershipDocument
    platforms: dict[Identifier, PlatformSpec]
    assets: AssetsLock

    @model_validator(mode="after")
    def cross_document_references(self) -> CaseSpec:
        asset_by_id = self.assets.by_id()
        asset_references: list[tuple[str, str]] = []

        chemistry_model = self.chemistry.model
        if isinstance(chemistry_model, (FiniteRateChemistry, FlameletChemistry)):
            mechanism = chemistry_model.mechanism
            if isinstance(mechanism, AssetMechanism):
                asset_references.append(("chemistry mechanism", mechanism.mechanism_asset))
                if mechanism.thermodynamics_asset is not None:
                    asset_references.append(
                        ("chemistry thermodynamics", mechanism.thermodynamics_asset)
                    )
                if mechanism.transport_asset is not None:
                    asset_references.append(("chemistry transport", mechanism.transport_asset))
        if (
            isinstance(chemistry_model, FlameletChemistry)
            and chemistry_model.table_asset is not None
        ):
            asset_references.append(("flamelet table", chemistry_model.table_asset))

        for field in self.fields.fields:
            if isinstance(field.initial, ProfileValue):
                asset_references.append((f"initial field {field.id}", field.initial.asset))

        for boundary in self.boundary_conditions.boundaries:
            condition = boundary.condition
            compositions = []
            if isinstance(condition, (MassFlowInlet, VelocityInlet)):
                compositions.append(condition.species)
            elif isinstance(condition, PressureOutlet):
                compositions.append(condition.backflow_species)
            if self.physics.species.type == "none" and any(
                item is not None for item in compositions
            ):
                raise ValueError(
                    f"boundary {boundary.id!r} defines a composition while the species model is disabled"
                )

            if isinstance(condition, WallBoundary):
                thermal = condition.thermal
                value = None
                if isinstance(thermal, FixedTemperatureWall):
                    value = thermal.temperature
                elif isinstance(thermal, FixedHeatFluxWall):
                    value = thermal.heat_flux
                if isinstance(value, ProfileValue):
                    asset_references.append((f"wall profile {boundary.id}", value.asset))

        for action in self.initialization.actions:
            if isinstance(action, ReadCheckpointAction):
                asset_references.append((f"initialization action {action.id}", action.case_asset))
                if action.data_asset is not None:
                    asset_references.append(
                        (f"initialization action {action.id}", action.data_asset)
                    )
            elif isinstance(action, PatchAction) and isinstance(action.value, ProfileValue):
                asset_references.append((f"patch action {action.id}", action.value.asset))

        for stage in self.control.stages:
            if isinstance(stage, LoadAssetStage):
                asset_references.append((f"load stage {stage.id}", stage.asset))
                if stage.data_asset is not None:
                    asset_references.append((f"load stage {stage.id}", stage.data_asset))
            for stage_input in stage.inputs:
                if isinstance(stage_input, AssetInput):
                    asset_references.append(
                        (f"stage input {stage.id}.{stage_input.name}", stage_input.asset)
                    )
            for condition in [*stage.preconditions, *stage.postconditions]:
                if isinstance(condition, AssetAvailableCondition):
                    asset_references.append((f"stage condition {stage.id}", condition.asset))

        if isinstance(self.objectives.provenance, SourceAssetProvenance):
            asset_references.append(
                ("engineering objective provenance", self.objectives.provenance.asset)
            )
        for aspect in self.objectives.aspects:
            if isinstance(aspect, MatchReferenceAspect) and isinstance(
                aspect.reference, ReferenceAsset
            ):
                asset_references.append(
                    (f"engineering objective aspect {aspect.id}", aspect.reference.asset)
                )

        if self.state.baseline is not None:
            asset_references.append(("state baseline case", self.state.baseline.case.asset))
            if self.state.baseline.data is not None:
                asset_references.append(("state baseline data", self.state.baseline.data.asset))

        missing_assets = sorted(
            f"{context}: {asset_id}"
            for context, asset_id in asset_references
            if asset_id not in asset_by_id
        )
        if missing_assets:
            raise ValueError("unknown asset references: " + "; ".join(missing_assets))

        self._validate_physics_chemistry()
        self._validate_platforms()
        self._validate_stage_references()
        self._validate_load_asset_kinds(asset_by_id)
        self._validate_objectives(asset_by_id)
        self._validate_state_baseline(asset_by_id)
        self._validate_state_document_pointers()
        self._validate_overlay_reconcile_scope()
        return self

    def _validate_physics_chemistry(self) -> None:
        species_type = self.physics.species.type
        chemistry = self.chemistry.model
        if species_type == "none" and not isinstance(chemistry, NoChemistry):
            raise ValueError("active chemistry requires an active species model")
        if isinstance(chemistry, FiniteRateChemistry) and species_type != "species_transport":
            raise ValueError(
                "finite_rate chemistry requires physics.species.type=species_transport"
            )
        if isinstance(chemistry, FlameletChemistry) and species_type not in {
            "nonpremixed_pdf",
            "partially_premixed_pdf",
        }:
            raise ValueError("flamelet chemistry requires a PDF species model")

    def _validate_platforms(self) -> None:
        if not self.platforms:
            raise ValueError("at least one platform profile is required")
        for key, platform in self.platforms.items():
            if key != platform.id:
                raise ValueError(f"platform mapping key {key!r} does not match id {platform.id!r}")
        referenced = {self.control.default_platform}
        referenced.update(
            stage.platform for stage in self.control.stages if stage.platform is not None
        )
        missing = sorted(referenced - self.platforms.keys())
        if missing:
            raise ValueError(f"control references unknown platforms: {', '.join(missing)}")

    def _validate_stage_references(self) -> None:
        profile_ids = set(self.numerics.profiles)
        action_ids = {action.id for action in self.initialization.actions}
        monitor_ids = {monitor.id for monitor in self.monitors.monitors}
        gate_ids = {gate.id for gate in self.monitors.gates}
        stage_by_id = {stage.id: stage for stage in self.control.stages}

        for stage in self.control.stages:
            if (
                isinstance(stage, ReconcileStage)
                and stage.numerics_profile is not None
                and stage.numerics_profile not in profile_ids
            ):
                raise ValueError(
                    f"stage {stage.id!r} references unknown numerics profile "
                    f"{stage.numerics_profile!r}"
                )
            if isinstance(stage, InitializeStage):
                missing = sorted(set(stage.actions) - action_ids)
                if missing:
                    raise ValueError(
                        f"stage {stage.id!r} references unknown initialization actions: "
                        f"{', '.join(missing)}"
                    )
            if isinstance(stage, SampleStage):
                missing = sorted(set(stage.monitors) - monitor_ids)
                if missing:
                    raise ValueError(
                        f"stage {stage.id!r} references unknown monitors: {', '.join(missing)}"
                    )
            if isinstance(stage, GateStage):
                missing = sorted(set(stage.gates) - gate_ids)
                if missing:
                    raise ValueError(
                        f"stage {stage.id!r} references unknown gates: {', '.join(missing)}"
                    )
            if isinstance(stage, CheckpointStage) and isinstance(stage.promotion, GatePromotion):
                missing = sorted(set(stage.promotion.gates) - gate_ids)
                if missing:
                    raise ValueError(
                        f"checkpoint {stage.id!r} promotion references unknown gates: "
                        f"{', '.join(missing)}"
                    )
            if self.physics.solver.time == "steady" and isinstance(stage, AdvanceTimeStage):
                raise ValueError(f"steady case cannot contain advance_time stage {stage.id!r}")
            for condition in [*stage.preconditions, *stage.postconditions]:
                if isinstance(condition, MetricCondition) and condition.monitor not in monitor_ids:
                    raise ValueError(
                        f"stage {stage.id!r} condition references unknown monitor {condition.monitor!r}"
                    )

        for gate in self.monitors.gates:
            if not isinstance(gate, ArtifactGate):
                continue
            if gate.stage not in stage_by_id:
                raise ValueError(
                    f"artifact gate {gate.id!r} references unknown stage {gate.stage!r}"
                )
            output_ids = {output.id for output in stage_by_id[gate.stage].outputs}
            if gate.output not in output_ids:
                raise ValueError(
                    f"artifact gate {gate.id!r} references unknown output {gate.stage}.{gate.output}"
                )

    def _validate_load_asset_kinds(self, asset_by_id: dict[str, LockedAsset]) -> None:
        expected = {
            "mesh": {"mesh"},
            "case": {"case"},
            "case_data": {"case"},
            "chemistry_table": {"chemistry", "table"},
            "profile": {"profile"},
        }
        for stage in self.control.stages:
            if not isinstance(stage, LoadAssetStage) or stage.asset not in asset_by_id:
                continue
            asset = asset_by_id[stage.asset]
            if asset.kind not in expected[stage.load_as]:
                raise ValueError(
                    f"load stage {stage.id!r} expects {stage.load_as} asset, "
                    f"but {stage.asset!r} is {asset.kind!r}"
                )
            if stage.data_asset is not None and stage.data_asset in asset_by_id:
                data_asset = asset_by_id[stage.data_asset]
                if data_asset.kind != "data":
                    raise ValueError(f"load stage {stage.id!r} data_asset must have kind=data")

    def _validate_objectives(self, asset_by_id: dict[str, LockedAsset]) -> None:
        monitor_ids = {monitor.id for monitor in self.monitors.monitors}
        referenced_monitors: set[str] = set()
        for aspect in self.objectives.aspects:
            if isinstance(aspect, (ObserveAspect, InvestigateAspect)):
                referenced_monitors.update(aspect.monitors)
            elif isinstance(aspect, (DirectionalAspect, MatchReferenceAspect)):
                referenced_monitors.add(aspect.monitor)

            if isinstance(aspect, MatchReferenceAspect) and isinstance(
                aspect.reference, ReferenceAsset
            ):
                reference_asset = asset_by_id.get(aspect.reference.asset)
                if reference_asset is not None and reference_asset.kind != "reference_data":
                    raise ValueError(
                        f"objective aspect {aspect.id!r} reference asset must have "
                        "kind=reference_data"
                    )

        missing = sorted(referenced_monitors - monitor_ids)
        if missing:
            raise ValueError(
                f"engineering objectives reference unknown monitors: {', '.join(missing)}"
            )

    def _validate_state_baseline(self, asset_by_id: dict[str, LockedAsset]) -> None:
        if self.state.baseline is None:
            return
        references = [("case", self.state.baseline.case, "case")]
        if self.state.baseline.data is not None:
            references.append(("data", self.state.baseline.data, "data"))
        for role, reference, expected_kind in references:
            asset = asset_by_id.get(reference.asset)
            if asset is None:
                continue
            if asset.kind != expected_kind:
                raise ValueError(
                    f"state baseline {role} asset {reference.asset!r} must have kind={expected_kind}"
                )
            if asset.sha256 != reference.sha256:
                raise ValueError(
                    f"state baseline {role} digest does not match assets.lock for "
                    f"{reference.asset!r}"
                )

    def _validate_overlay_reconcile_scope(self) -> None:
        if self.state.mode != "checkpoint_overlay":
            return
        fully_owned_documents = {
            entry.source.document
            for entry in self.state.declared_paths
            if isinstance(entry.source, CaseDocumentStateSource) and entry.source.pointer == ""
        }
        for stage in self.control.stages:
            if not isinstance(stage, ReconcileStage):
                continue
            required_documents = {
                RECONCILE_SECTION_DOCUMENTS[section] for section in stage.sections
            }
            missing = sorted(required_documents - fully_owned_documents)
            if missing:
                raise ValueError(
                    f"checkpoint overlay stage {stage.id!r} cannot reconcile whole sections "
                    "without whole-document state ownership; declare an empty JSON pointer for: "
                    f"{', '.join(missing)}"
                )

    def _validate_state_document_pointers(self) -> None:
        documents = {
            "constant/physics.yaml": self.physics,
            "constant/materials.yaml": self.materials,
            "constant/chemistry.yaml": self.chemistry,
            "0/fields.yaml": self.fields,
            "0/boundary-conditions.yaml": self.boundary_conditions,
            "system/numerics.yaml": self.numerics,
            "system/initialization.yaml": self.initialization,
            "system/monitors.yaml": self.monitors,
            "system/control.yaml": self.control,
        }
        payloads = {
            name: document.model_dump(mode="python", by_alias=True)
            for name, document in documents.items()
        }
        for entry in self.state.declared_paths:
            if not isinstance(entry.source, CaseDocumentStateSource):
                continue
            try:
                resolve_json_pointer(
                    payloads[entry.source.document],
                    entry.source.pointer,
                )
            except ValueError as exc:
                raise ValueError(
                    f"declared state path {entry.path!r} source pointer "
                    f"{entry.source.document}#{entry.source.pointer} does not resolve: {exc}"
                ) from exc
