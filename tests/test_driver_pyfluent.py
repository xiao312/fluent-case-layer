from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fluent_case_layer.driver.adapters.pyfluent import PyFluentAdapter
from fluent_case_layer.driver.errors import (
    AdapterMappingError,
    DriverError,
    ExecutionFailedError,
)
from fluent_case_layer.driver.executor import PlanExecutor
from fluent_case_layer.driver.types import (
    ActionKind,
    CheckpointSpec,
    CompiledPlan,
    SemanticAction,
)
from fluent_case_layer.driver.util import file_sha256


class CallRecorder:
    def __init__(self, result=None) -> None:
        self.calls = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class MaterializingWriter(CallRecorder):
    def __init__(self, payload: bytes) -> None:
        super().__init__()
        self.payload = payload

    def __call__(self, *args, **kwargs):
        result = super().__call__(*args, **kwargs)
        Path(kwargs["file_name"]).write_bytes(self.payload)
        return result


def fake_session():
    hybrid = CallRecorder()
    report = CallRecorder(0.004)
    enabled = SimpleNamespace(set_state=CallRecorder())
    session = SimpleNamespace(
        solution=SimpleNamespace(initialization=SimpleNamespace(hybrid_initialize=hybrid)),
        setup=SimpleNamespace(models=SimpleNamespace(energy=SimpleNamespace(enabled=enabled))),
        reports=SimpleNamespace(mass_closure=report),
    )
    return session, hybrid, report, enabled.set_state


class PyFluentFailClosedTests(unittest.TestCase):
    def test_prepare_verifies_all_referenced_local_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset_path = root / "checkpoint.cas.h5"
            asset_path.write_bytes(b"verified checkpoint")
            asset = {
                "id": "checkpoint",
                "kind": "case",
                "source": {
                    "type": "environment",
                    "root_variable": "FCL_TEST_ASSET_ROOT",
                    "relative_path": asset_path.name,
                },
                "sha256": file_sha256(asset_path),
            }
            action = SemanticAction(
                id="restore",
                kind=ActionKind.INITIALIZE,
                parameters={"referenced_assets": [asset]},
            )
            plan = CompiledPlan(
                schema_version="1",
                case_id="asset-verification",
                case_digest="test",
                actions=(action,),
            ).with_hash()
            with patch.dict(os.environ, {"FCL_TEST_ASSET_ROOT": str(root)}):
                adapter = PyFluentAdapter(session=fake_session()[0])
                adapter.prepare(plan)
            self.assertTrue(adapter.snapshot()["assets"]["checkpoint"]["content_verified"])

            bad_asset = {**asset, "sha256": "0" * 64}
            bad_action = SemanticAction(
                id="restore",
                kind=ActionKind.INITIALIZE,
                parameters={"referenced_assets": [bad_asset]},
            )
            bad_plan = CompiledPlan(
                schema_version="1",
                case_id="asset-verification",
                case_digest="bad-test",
                actions=(bad_action,),
            ).with_hash()
            with (
                patch.dict(os.environ, {"FCL_TEST_ASSET_ROOT": str(root)}),
                self.assertRaisesRegex(DriverError, "failed SHA-256 verification"),
            ):
                PyFluentAdapter(session=fake_session()[0]).prepare(bad_plan)

    def test_semantic_reconcile_without_compiled_operations_fails(self) -> None:
        session, hybrid, _, _ = fake_session()
        adapter = PyFluentAdapter(session=session)
        action = SemanticAction(
            id="configure",
            kind=ActionKind.RECONCILE_SETTINGS,
            parameters={"sections": ["physics"], "desired": {"physics": {"energy": True}}},
        )
        with self.assertRaisesRegex(AdapterMappingError, "mapping gap.*configure"):
            adapter.execute(action)
        self.assertEqual(hybrid.calls, [])

    def test_complex_resolved_initialization_fails_before_partial_hybrid(self) -> None:
        session, hybrid, _, _ = fake_session()
        adapter = PyFluentAdapter(session=session)
        action = SemanticAction(
            id="initialize-m2",
            kind=ActionKind.INITIALIZE,
            parameters={
                "resolved_actions": [
                    {"id": "restore", "type": "read_checkpoint"},
                    {"id": "hybrid", "type": "hybrid"},
                    {"id": "register", "type": "create_register"},
                    {"id": "patch", "type": "patch"},
                ]
            },
        )
        with self.assertRaisesRegex(
            AdapterMappingError, "mapping gap.*read_checkpoint, hybrid, create_register, patch"
        ):
            adapter.execute(action)
        self.assertEqual(hybrid.calls, [])

    def test_sample_without_collectors_fails_instead_of_claiming_evidence(self) -> None:
        session, _, _, _ = fake_session()
        adapter = PyFluentAdapter(session=session)
        action = SemanticAction(
            id="sample",
            kind=ActionKind.SAMPLE,
            parameters={"resolved_monitors": [{"id": "mass-closure", "type": "mass_balance"}]},
        )
        with self.assertRaisesRegex(AdapterMappingError, "mapping gap.*sample"):
            adapter.execute(action)

    def test_explicit_settings_operations_and_simple_hybrid_are_supported(self) -> None:
        session, hybrid, report, set_enabled = fake_session()
        adapter = PyFluentAdapter(session=session)
        reconcile = SemanticAction(
            id="energy",
            kind=ActionKind.RECONCILE_SETTINGS,
            parameters={
                "operations": [
                    {
                        "path": "setup.models.energy.enabled",
                        "mode": "set",
                        "value": True,
                    }
                ]
            },
        )
        adapter.execute(reconcile)
        self.assertEqual(set_enabled.calls, [((True,), {})])

        initialize = SemanticAction(
            id="hybrid",
            kind=ActionKind.INITIALIZE,
            parameters={"resolved_actions": [{"id": "hybrid", "type": "hybrid"}]},
        )
        adapter.execute(initialize)
        self.assertEqual(len(hybrid.calls), 1)

        sample = SemanticAction(
            id="sample",
            kind=ActionKind.SAMPLE,
            parameters={
                "resolved_monitors": [{"id": "mass-closure", "type": "mass_balance"}],
                "operations": [
                    {
                        "path": "reports.mass_closure",
                        "mode": "call",
                        "capture_as": "mass-closure",
                    }
                ],
            },
        )
        result = adapter.execute(sample)
        self.assertEqual(result.metrics, {"mass-closure": 0.004})
        self.assertEqual(len(report.calls), 1)

    def test_sample_state_feeds_later_gate_checkpoint_promotion_and_artifact_gate(
        self,
    ) -> None:
        report = CallRecorder(0.004)
        write_case = MaterializingWriter(b"case bytes")
        write_data = MaterializingWriter(b"data bytes")
        session = SimpleNamespace(
            reports=SimpleNamespace(mass_closure=report),
            file=SimpleNamespace(write_case=write_case, write_data=write_data),
        )
        closure_gate = {
            "id": "closure-ok",
            "type": "threshold",
            "category": "numerical",
            "severity": "required",
            "monitor": "mass-closure",
            "operator": "le",
            "limit": {"value": 0.01, "unit": "1"},
        }
        output_root = "outputs/{run_id}"
        outputs = [
            {
                "id": "case-file",
                "kind": "case",
                "path_template": f"{output_root}/accepted.cas.h5",
            },
            {
                "id": "data-file",
                "kind": "data",
                "path_template": f"{output_root}/accepted.dat.h5",
            },
        ]
        artifacts = [
            {
                "path": output["path_template"],
                "role": output["kind"],
                "metadata": {"output_id": output["id"]},
            }
            for output in outputs
        ]
        actions = (
            SemanticAction(
                id="sample",
                kind=ActionKind.SAMPLE,
                parameters={
                    "resolved_monitors": [{"id": "mass-closure", "type": "mass_balance"}],
                    "operations": [
                        {
                            "path": "reports.mass_closure",
                            "mode": "call",
                            "capture_as": "mass-closure",
                        }
                    ],
                },
            ),
            SemanticAction(
                id="accept",
                kind=ActionKind.GATE,
                depends_on=("sample",),
                parameters={"named_gates": [closure_gate]},
            ),
            SemanticAction(
                id="checkpoint",
                kind=ActionKind.WRITE_CHECKPOINT,
                depends_on=("accept",),
                parameters={
                    "write_case": True,
                    "write_data": True,
                    "declared_outputs": outputs,
                    "artifacts": artifacts,
                    "named_gates": [closure_gate],
                },
                checkpoint=CheckpointSpec(
                    name="accepted",
                    role="candidate",
                    promote_when_gates_pass=True,
                ),
            ),
            SemanticAction(
                id="verify-artifact",
                kind=ActionKind.GATE,
                depends_on=("checkpoint",),
                parameters={
                    "named_gates": [
                        {
                            "id": "data-written",
                            "type": "artifact_exists",
                            "category": "orchestration",
                            "severity": "required",
                            "stage": "checkpoint",
                            "output": "data-file",
                        }
                    ]
                },
            ),
        )
        plan = CompiledPlan(
            schema_version="1",
            case_id="real-evidence",
            case_digest="test",
            actions=actions,
        ).with_hash()

        with tempfile.TemporaryDirectory() as temporary:
            run_directory = Path(temporary) / "run"
            adapter = PyFluentAdapter(session=session)
            summary = PlanExecutor(
                plan,
                adapter,
                run_directory,
                run_id="real-evidence-001",
            ).apply()

            self.assertEqual(summary.orchestration_status, "succeeded")
            self.assertEqual(summary.numerical_status, "passed")
            self.assertEqual(adapter.snapshot()["metrics"], {"mass-closure": 0.004})
            self.assertEqual(adapter.snapshot()["metric_history"], {"mass-closure": [0.004]})
            expected_case = run_directory / "outputs/real-evidence-001/accepted.cas.h5"
            expected_data = run_directory / "outputs/real-evidence-001/accepted.dat.h5"
            self.assertEqual(write_case.calls[0][1]["file_name"], str(expected_case))
            self.assertEqual(write_data.calls[0][1]["file_name"], str(expected_data))
            self.assertNotIn("{", write_case.calls[0][1]["file_name"])
            self.assertTrue(expected_case.is_file())
            self.assertTrue(expected_data.is_file())

            manifest = json.loads(
                (run_directory / "artifacts.manifest.json").read_text(encoding="utf-8")
            )
            data_entry = next(
                entry
                for entry in manifest["entries"]
                if entry.get("metadata", {}).get("output_id") == "data-file"
            )
            self.assertEqual(data_entry["sha256"], file_sha256(expected_data))
            events = [
                json.loads(line)
                for line in (run_directory / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertTrue(any(event["event"] == "checkpoint_promoted" for event in events))

    def test_fresh_pyfluent_session_cannot_skip_actions_from_existing_ledger(self) -> None:
        first_iterate = CallRecorder()
        second_iterate = CallRecorder()
        action = SemanticAction(
            id="iterate",
            kind=ActionKind.ITERATE,
            parameters={"iterations": 2},
        )
        plan = CompiledPlan(
            schema_version="1",
            case_id="unsafe-resume",
            case_digest="test",
            actions=(action,),
        ).with_hash()
        first_session = SimpleNamespace(
            solution=SimpleNamespace(run_calculation=SimpleNamespace(iterate=first_iterate))
        )
        second_session = SimpleNamespace(
            solution=SimpleNamespace(run_calculation=SimpleNamespace(iterate=second_iterate))
        )

        with tempfile.TemporaryDirectory() as temporary:
            run_directory = Path(temporary) / "run"
            PlanExecutor(plan, PyFluentAdapter(session=first_session), run_directory).apply()
            with self.assertRaisesRegex(DriverError, "cannot safely resume completed actions"):
                PlanExecutor(plan, PyFluentAdapter(session=second_session), run_directory).apply()

            self.assertEqual(len(first_iterate.calls), 1)
            self.assertEqual(second_iterate.calls, [])
            events = [
                json.loads(line)
                for line in (run_directory / "events.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(events[-1]["event"], "run_resume_rejected")

    def test_output_path_escape_is_rejected_before_solver_write(self) -> None:
        write_case = CallRecorder()
        session = SimpleNamespace(file=SimpleNamespace(write_case=write_case))
        action = SemanticAction(
            id="checkpoint",
            kind=ActionKind.WRITE_CHECKPOINT,
            parameters={
                "declared_outputs": [
                    {
                        "id": "case-file",
                        "kind": "case",
                        "path_template": "../escaped.cas.h5",
                    }
                ]
            },
        )
        plan = CompiledPlan(
            schema_version="1",
            case_id="unsafe-output",
            case_digest="test",
            actions=(action,),
        ).with_hash()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ExecutionFailedError, "output path escapes the run root"):
                PlanExecutor(plan, PyFluentAdapter(session=session), root / "run").apply()
            self.assertEqual(write_case.calls, [])
            self.assertFalse((root / "escaped.cas.h5").exists())

    def test_real_artifact_gate_rejects_manifest_without_materialized_file(self) -> None:
        write_data = CallRecorder()
        session = SimpleNamespace(file=SimpleNamespace(write_data=write_data))
        path_template = "outputs/{run_id}/missing.dat.h5"
        checkpoint = SemanticAction(
            id="checkpoint",
            kind=ActionKind.WRITE_CHECKPOINT,
            parameters={
                "write_case": False,
                "write_data": True,
                "declared_outputs": [
                    {
                        "id": "data-file",
                        "kind": "data",
                        "path_template": path_template,
                    }
                ],
                "artifacts": [
                    {
                        "path": path_template,
                        "role": "data",
                        "metadata": {"output_id": "data-file"},
                    }
                ],
            },
        )
        verify = SemanticAction(
            id="verify-artifact",
            kind=ActionKind.GATE,
            depends_on=("checkpoint",),
            parameters={
                "named_gates": [
                    {
                        "id": "data-written",
                        "type": "artifact_exists",
                        "category": "orchestration",
                        "severity": "required",
                        "stage": "checkpoint",
                        "output": "data-file",
                    }
                ]
            },
        )
        plan = CompiledPlan(
            schema_version="1",
            case_id="missing-output",
            case_digest="test",
            actions=(checkpoint, verify),
        ).with_hash()

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                ExecutionFailedError, "local file matching its manifest SHA-256"
            ):
                PlanExecutor(
                    plan,
                    PyFluentAdapter(session=session),
                    Path(temporary) / "run",
                    run_id="missing-output-001",
                ).apply()
            self.assertEqual(len(write_data.calls), 1)
            self.assertFalse(Path(write_data.calls[0][1]["file_name"]).exists())


if __name__ == "__main__":
    unittest.main()
