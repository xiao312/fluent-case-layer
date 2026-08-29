from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fluent_case_layer.driver.adapters.recording import RecordingAdapter
from fluent_case_layer.driver.errors import ExecutionFailedError, PlanConflictError
from fluent_case_layer.driver.events import EventLog
from fluent_case_layer.driver.evidence import write_plan_lock
from fluent_case_layer.driver.executor import PlanExecutor
from fluent_case_layer.driver.planner import compile_plan


class ExecutorTests(unittest.TestCase):
    def test_typed_asset_precondition_is_simulated_without_passing_scientific_gates(self) -> None:
        case = {
            "physics": {"case": {"id": "typed-dry-run"}},
            "assets": {
                "assets": [
                    {
                        "id": "mesh",
                        "kind": "mesh",
                        "source": {"type": "remote", "uri": "https://example.invalid/mesh"},
                        "sha256": "0" * 64,
                    }
                ]
            },
            "monitors": {
                "monitors": [{"id": "closure", "type": "mass_balance"}],
                "gates": [
                    {
                        "id": "closure-required",
                        "type": "threshold",
                        "category": "numerical",
                        "severity": "required",
                        "monitor": "closure",
                        "operator": "le",
                        "limit": {"value": 0.01, "unit": "1"},
                    }
                ],
            },
            "control": {
                "default_platform": "test",
                "stages": [
                    {
                        "id": "load",
                        "type": "load_asset",
                        "asset": "mesh",
                        "load_as": "mesh",
                        "preconditions": [{"type": "asset_available", "asset": "mesh"}],
                    },
                    {
                        "id": "sample",
                        "type": "sample",
                        "requires": ["load"],
                        "monitors": ["closure"],
                    },
                    {
                        "id": "accept",
                        "type": "gate",
                        "requires": ["sample"],
                        "gates": ["closure-required"],
                    },
                    {
                        "id": "save",
                        "type": "checkpoint",
                        "requires": ["accept"],
                        "label": "candidate",
                        "write_case": True,
                        "write_data": True,
                        "promotion": {
                            "type": "when_gates_pass",
                            "gates": ["closure-required"],
                            "role": "candidate",
                        },
                    },
                ],
            },
            "platforms": {"test": {"id": "test", "kind": "local", "resources": {}}},
        }
        plan = compile_plan(case)
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            summary = PlanExecutor(plan, RecordingAdapter(), run_dir).apply()
            self.assertEqual(summary.orchestration_status, "succeeded")
            self.assertEqual(summary.numerical_status, "not_evaluated")
            meta = json.loads((run_dir / "run.meta.json").read_text())
            events = EventLog(
                run_dir / "events.jsonl", run_id=meta["run_id"], plan_hash=plan.plan_hash
            ).read()
            gate_events = [event for event in events if event["event"] == "gate_evaluated"]
            self.assertTrue(gate_events)
            self.assertTrue(all(event["payload"]["passed"] is None for event in gate_events))
            self.assertFalse(any(event["event"] == "checkpoint_promoted" for event in events))
            load_before = json.loads(
                next((run_dir / "snapshots").glob("load.attempt-*.before.json")).read_text()
            )
            self.assertEqual(
                load_before["state"]["assets"]["mesh"]["availability_evidence"],
                "simulated_by_recording_adapter",
            )

    def test_evidence_snapshots_manifests_and_tui_audit(self) -> None:
        case = {
            "case_id": "evidence",
            "system": {
                "control": {
                    "stages": [
                        {"id": "launch", "action": "launch_solver", "parameters": {}},
                        {
                            "id": "legacy-dpm-update",
                            "action": "tui",
                            "depends_on": ["launch"],
                            "parameters": {
                                "command": "/solve/dpm-update",
                                "call_path": "tui.solve.dpm_update",
                                "reason": "no stable settings equivalent in supported release",
                                "fluent_version": "2026 R1",
                                "expected_postcondition": "DPM source epoch increments",
                            },
                        },
                        {
                            "id": "run",
                            "action": "iterate",
                            "depends_on": ["legacy-dpm-update"],
                            "parameters": {
                                "iterations": 4,
                                "metrics": {"mass_imbalance": 0.002},
                                "artifacts": [
                                    {"uri": "recording://reports/mass", "role": "report"}
                                ],
                            },
                            "gate": {
                                "category": "numerical",
                                "required": True,
                                "conditions": [
                                    {
                                        "path": "metrics.mass_imbalance",
                                        "operator": "less_than_or_equal",
                                        "expected": 0.01,
                                    }
                                ],
                            },
                            "checkpoint": {
                                "name": "qualified",
                                "role": "qualified",
                                "promote_when_gates_pass": True,
                            },
                        },
                    ]
                }
            },
        }
        plan = compile_plan(case)
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            summary = PlanExecutor(plan, RecordingAdapter(), run_dir).apply()
            self.assertEqual(summary.orchestration_status, "succeeded")
            self.assertEqual(summary.numerical_status, "passed")
            self.assertTrue((run_dir / "plan.lock.json").exists())
            self.assertGreaterEqual(len(list((run_dir / "snapshots").glob("*.json"))), 6)
            artifacts = json.loads((run_dir / "artifacts.manifest.json").read_text())
            checkpoints = json.loads((run_dir / "checkpoints.manifest.json").read_text())
            self.assertEqual(artifacts["entries"][0]["role"], "report")
            self.assertEqual(checkpoints["entries"][0]["role"], "qualified")

            meta = json.loads((run_dir / "run.meta.json").read_text())
            events = EventLog(
                run_dir / "events.jsonl",
                run_id=meta["run_id"],
                plan_hash=plan.plan_hash,
            ).read()
            kinds = [event["event"] for event in events]
            self.assertIn("tui_escape_requested", kinds)
            self.assertIn("tui_escape_executed", kinds)
            self.assertIn("checkpoint_promoted", kinds)

    def test_failed_action_resumes_without_repeating_successful_action(self) -> None:
        case = {
            "case_id": "resume",
            "system": {
                "control": {
                    "stages": [
                        {"id": "launch", "action": "launch_solver"},
                        {
                            "id": "run",
                            "action": "iterate",
                            "depends_on": ["launch"],
                            "parameters": {"iterations": 2},
                        },
                    ]
                }
            },
        }
        plan = compile_plan(case)
        adapter = RecordingAdapter(failures={"run": 1})
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            with self.assertRaises(ExecutionFailedError):
                PlanExecutor(plan, adapter, run_dir).apply()
            summary = PlanExecutor(plan, adapter, run_dir).apply(resume=True)
            self.assertEqual(summary.orchestration_status, "succeeded")
            self.assertEqual(adapter.executed.count("launch"), 1)
            self.assertEqual(adapter.executed.count("run"), 1)

            meta = json.loads((run_dir / "run.meta.json").read_text())
            events = EventLog(
                run_dir / "events.jsonl", run_id=meta["run_id"], plan_hash=plan.plan_hash
            ).read()
            self.assertTrue(
                any(
                    event["event"] == "action_skipped" and event["action_id"] == "launch"
                    for event in events
                )
            )

    def test_plan_lock_cannot_be_replaced(self) -> None:
        first = compile_plan({"case_id": "one", "system": {"control": {"iterations": 1}}})
        second = compile_plan({"case_id": "two", "system": {"control": {"iterations": 1}}})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "plan.lock.json"
            write_plan_lock(path, first)
            with self.assertRaises(PlanConflictError):
                write_plan_lock(path, second)


if __name__ == "__main__":
    unittest.main()
