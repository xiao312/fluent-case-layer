from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fluent_case_layer.driver import (
    AttemptStore,
    RecordingAdapter,
    apply_candidate_attempt,
    compile_candidate_plan,
    compile_plan,
    load_case,
)
from fluent_case_layer.driver.errors import CaseValidationError, DriverError
from fluent_case_layer.driver.loading import LoadedCase
from fluent_case_layer.driver.util import deep_merge, file_sha256, stable_hash

CASE_TEMPLATE = Path(__file__).resolve().parents[1] / "case"


def lightweight_loaded_case() -> LoadedCase:
    case = {
        "schema_version": "1",
        "case_id": "candidate-fixture",
        "objectives": {
            "revision": {
                "id": "objective-r1",
                "sequence": 1,
                "recorded_at": "2026-08-29T12:00:00+08:00",
                "recorded_by": "test engineer",
            },
            "provenance": {"type": "engineer_statement", "author": "test engineer"},
            "statement": "Reduce loss while retaining an inspectable baseline.",
            "enforcement": "none",
            "aspects": [
                {
                    "id": "reduce-loss",
                    "type": "directional",
                    "description": "Explore lower loss.",
                    "monitor": "loss",
                    "direction": "minimize",
                    "priority": "primary",
                }
            ],
        },
        "state": {
            "schema_version": "1",
            "mode": "full_definition",
            "declared_paths": [],
            "observed_paths": [],
        },
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
    return LoadedCase(case=case, platform={}, root=Path("."), schema_model=None)


def candidate_plan(value: int = 1):
    return compile_candidate_plan(
        lightweight_loaded_case(),
        overlay={"experiment": {"candidate": value}},
        rationale=f"Evaluate candidate {value} against the selected objective.",
        objective_ids=["reduce-loss"],
    )


class CandidateCompilationTests(unittest.TestCase):
    def test_canonical_overlay_is_revalidated_and_records_exact_intent(self) -> None:
        loaded = load_case(CASE_TEMPLATE)
        authored = (CASE_TEMPLATE / "constant" / "physics.yaml").read_text(encoding="utf-8")
        base = compile_plan(loaded.case, loaded.platform)
        overlay = {"physics": {"solver": {"operating_pressure": {"value": 2.5, "unit": "MPa"}}}}
        plan = compile_candidate_plan(
            loaded,
            overlay=overlay,
            rationale="Inspect pressure sensitivity without changing the authored baseline.",
            objective_ids=["numerical-health"],
        )

        self.assertEqual(plan.metadata["candidate"]["overlay"], overlay)
        self.assertEqual(plan.metadata["candidate"]["overlay_sha256"], stable_hash(overlay))
        self.assertEqual(plan.metadata["candidate"]["selected_objective_ids"], ["numerical-health"])
        self.assertEqual(
            plan.metadata["candidate"]["objective_context"]["selected_aspects"][0]["id"],
            "numerical-health",
        )
        self.assertNotEqual(base.plan_hash, plan.plan_hash)
        self.assertEqual(
            (CASE_TEMPLATE / "constant" / "physics.yaml").read_text(encoding="utf-8"),
            authored,
        )

        with self.assertRaisesRegex(
            CaseValidationError, "canonical candidate is invalid after overlay"
        ):
            compile_candidate_plan(
                loaded,
                overlay={"control": {"default_platform": "missing-platform"}},
                rationale="Exercise canonical cross-document validation.",
            )
        with self.assertRaisesRegex(CaseValidationError, "cannot rewrite.*state-ownership"):
            compile_candidate_plan(
                loaded,
                overlay={"state": {"mode": "full_definition"}},
                rationale="This attempted policy escalation must fail.",
            )

    def test_plan_metadata_embeds_objective_and_state_policy_with_digests(self) -> None:
        loaded = load_case(CASE_TEMPLATE)
        plan = compile_plan(loaded.case, loaded.platform)
        objectives = plan.metadata["objectives"]
        state = plan.metadata["state_ownership"]

        self.assertEqual(objectives["revision"], loaded.case["objectives"]["revision"])
        self.assertEqual(objectives["document"], loaded.case["objectives"])
        self.assertEqual(objectives["content_digest"], stable_hash(loaded.case["objectives"]))
        self.assertEqual(state["policy"], loaded.case["state"])
        self.assertEqual(state["content_digest"], stable_hash(loaded.case["state"]))

        changed = deep_merge(
            loaded.case,
            {"objectives": {"statement": "A revised, still non-enforcing objective."}},
        )
        self.assertNotEqual(plan.plan_hash, compile_plan(changed, loaded.platform).plan_hash)

    def test_checkpoint_overlay_reconcile_requires_whole_document_ownership(self) -> None:
        case = {
            "case_id": "partial-state",
            "physics": {"solver": {"time_mode": "steady"}},
            "state": {
                "mode": "checkpoint_overlay",
                "declared_paths": [
                    {
                        "path": "setup.solver",
                        "source": {
                            "type": "case_document",
                            "document": "constant/physics.yaml",
                            "pointer": "/solver",
                        },
                    }
                ],
            },
            "control": {
                "stages": [{"id": "configure", "type": "reconcile", "sections": ["physics"]}]
            },
        }
        with self.assertRaisesRegex(
            CaseValidationError, "not authorized for whole-section mutation.*physics"
        ):
            compile_plan(case)

        case["state"]["declared_paths"][0]["source"]["pointer"] = ""
        plan = compile_plan(case)
        configure = next(action for action in plan.actions if action.id == "configure")
        self.assertEqual(
            configure.parameters["state_scope"]["whole_document_authorizations"],
            ["constant/physics.yaml"],
        )


class AttemptLifecycleTests(unittest.TestCase):
    def test_failure_is_retained_and_can_be_rejected(self) -> None:
        plan = candidate_plan()
        with tempfile.TemporaryDirectory() as temporary:
            store = AttemptStore(Path(temporary))
            record = apply_candidate_attempt(
                plan,
                RecordingAdapter(failures={"run": 1}),
                store,
                attempt_id="failed-candidate",
            )

            self.assertEqual(record.status, "failed")
            self.assertEqual(record.orchestration_status, "failed")
            self.assertEqual(record.numerical_status, "not_evaluated")
            self.assertEqual(record.error["error_type"], "ExecutionFailedError")
            self.assertIn("events", record.evidence)
            self.assertEqual(store.load("failed-candidate").attempt_digest, record.attempt_digest)

            rejected = store.decide(
                "failed-candidate",
                actor="engineer",
                decision="reject",
                reason="The solver action failed; retain it as negative evidence.",
            )
            self.assertEqual(rejected["decision"]["decision"], "reject")
            self.assertIsNone(rejected["ref"])
            with self.assertRaisesRegex(DriverError, "orchestration-successful"):
                store.decide(
                    "failed-candidate",
                    actor="agent",
                    decision="promote",
                    reason="This must not be allowed.",
                    ref_name="best",
                )

    def test_agent_promotion_needs_no_gate_and_retains_ref_predecessor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AttemptStore(root)
            first = apply_candidate_attempt(
                candidate_plan(1), RecordingAdapter(), store, attempt_id="candidate-one"
            )
            second = apply_candidate_attempt(
                candidate_plan(2), RecordingAdapter(), store, attempt_id="candidate-two"
            )
            self.assertEqual(first.numerical_status, "not_evaluated")
            self.assertEqual(second.scientific_status, "not_evaluated")
            self.assertEqual(first.objective_revision["id"], "objective-r1")
            self.assertEqual(
                first.objective_content_digest,
                stable_hash(lightweight_loaded_case().case["objectives"]),
            )
            self.assertEqual(first.state_ownership_mode, "full_definition")
            self.assertEqual(
                first.state_ownership_digest,
                stable_hash(lightweight_loaded_case().case["state"]),
            )

            first_decision = store.decide(
                "candidate-one",
                actor="agent",
                decision="promote",
                reason="Best inspected candidate so far; formal gates are intentionally absent.",
                ref_name="working-best",
            )
            self.assertIsNone(first_decision["ref"]["predecessor"])
            second_decision = store.decide(
                "candidate-two",
                actor="agent",
                decision="promote",
                reason="New candidate improves the exploratory objective.",
                ref_name="working-best",
            )
            predecessor = second_decision["ref"]["predecessor"]
            self.assertEqual(predecessor["attempt_id"], "candidate-one")
            self.assertEqual(predecessor["attempt_digest"], first.attempt_digest)
            self.assertTrue((root / "refs" / "objects" / f"{first.attempt_digest}.json").is_file())
            self.assertTrue((root / "refs" / "objects" / f"{second.attempt_digest}.json").is_file())

            (root / "refs" / "manifest.json").unlink()
            recovered = store.rebuild_refs()
            self.assertEqual(
                recovered["refs"]["working-best"]["attempt_digest"], second.attempt_digest
            )
            self.assertEqual(
                recovered["refs"]["working-best"]["predecessor"]["attempt_digest"],
                first.attempt_digest,
            )

    def test_plan_mismatch_tamper_and_path_escape_fail_closed(self) -> None:
        plan = candidate_plan()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AttemptStore(root)
            record = apply_candidate_attempt(
                plan, RecordingAdapter(), store, attempt_id="tamper-target"
            )
            plan_lock = root / record.evidence["plan_lock"]["path"]
            lock_value = json.loads(plan_lock.read_text(encoding="utf-8"))
            lock_value["case_id"] = "tampered-case"
            plan_lock.write_text(json.dumps(lock_value), encoding="utf-8")

            record_path = root / "attempts" / "tamper-target.json"
            record_value = json.loads(record_path.read_text(encoding="utf-8"))
            record_value["evidence"]["plan_lock"]["sha256"] = file_sha256(plan_lock)
            unsigned = dict(record_value)
            unsigned.pop("attempt_digest")
            record_value["attempt_digest"] = stable_hash(unsigned)
            record_path.write_text(json.dumps(record_value), encoding="utf-8")
            with self.assertRaisesRegex(DriverError, "run plan does not match"):
                store.load("tamper-target")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = AttemptStore(root / "store")
            with self.assertRaisesRegex(DriverError, "must not contain path separators"):
                apply_candidate_attempt(
                    plan,
                    RecordingAdapter(),
                    store,
                    attempt_id="../outside",
                )
            self.assertFalse((root / "outside.json").exists())

            safe = apply_candidate_attempt(
                plan, RecordingAdapter(), store, attempt_id="safe-candidate"
            )
            with self.assertRaisesRegex(DriverError, "must not contain path separators"):
                store.decide(
                    safe.attempt_id,
                    actor="agent",
                    decision="promote",
                    reason="Invalid path probe.",
                    ref_name="../outside",
                )

    def test_invalid_plan_hash_is_rejected_before_attempt_creation(self) -> None:
        plan = replace(candidate_plan(), plan_hash="0" * 64)
        with tempfile.TemporaryDirectory() as temporary:
            store = AttemptStore(Path(temporary))
            with self.assertRaisesRegex(DriverError, "plan hash.*does not match"):
                apply_candidate_attempt(plan, RecordingAdapter(), store, attempt_id="bad-plan")
            self.assertEqual(store.list(), ())


if __name__ == "__main__":
    unittest.main()
