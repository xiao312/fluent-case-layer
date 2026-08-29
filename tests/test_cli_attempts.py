from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from fluent_case_layer.cli import main


class CandidateAttemptCliTests(unittest.TestCase):
    def test_candidate_plan_apply_show_list_and_agent_decide(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = root / "case.json"
            case.write_text(
                json.dumps(
                    {
                        "case_id": "cli-candidate",
                        "objectives": {
                            "revision": {
                                "id": "cli-r1",
                                "sequence": 1,
                                "recorded_at": "2026-08-29T12:00:00+08:00",
                                "recorded_by": "CLI test",
                            },
                            "provenance": {
                                "type": "engineer_statement",
                                "author": "CLI test",
                            },
                            "statement": "Exercise a candidate without mandatory gates.",
                            "enforcement": "none",
                            "aspects": [
                                {
                                    "id": "observe-run",
                                    "type": "observe",
                                    "description": "Retain orchestration evidence.",
                                    "monitors": ["iteration"],
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
                                        "parameters": {"iterations": 1},
                                    },
                                ]
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            overlay = root / "overlay.json"
            overlay.write_text(json.dumps({"experiment": {"iteration": 1}}), encoding="utf-8")
            store = root / "store"

            plan_output = io.StringIO()
            with contextlib.redirect_stdout(plan_output):
                self.assertEqual(
                    main(
                        [
                            "candidate",
                            "plan",
                            str(case),
                            "--overlay",
                            str(overlay),
                            "--rationale",
                            "Establish a first candidate.",
                            "--objective",
                            "observe-run",
                        ]
                    ),
                    0,
                )
            self.assertEqual(
                json.loads(plan_output.getvalue())["metadata"]["candidate"][
                    "selected_objective_ids"
                ],
                ["observe-run"],
            )

            apply_output = io.StringIO()
            with contextlib.redirect_stdout(apply_output):
                self.assertEqual(
                    main(
                        [
                            "candidate",
                            "apply",
                            str(case),
                            "--overlay",
                            str(overlay),
                            "--rationale",
                            "Establish a first candidate.",
                            "--objective",
                            "observe-run",
                            "--store-root",
                            str(store),
                            "--attempt-id",
                            "cli-attempt",
                        ]
                    ),
                    0,
                )
            attempt = json.loads(apply_output.getvalue())
            self.assertEqual(attempt["status"], "succeeded")
            self.assertEqual(attempt["numerical_status"], "not_evaluated")

            list_output = io.StringIO()
            with contextlib.redirect_stdout(list_output):
                self.assertEqual(main(["attempt", "list", "--store-root", str(store)]), 0)
            self.assertEqual(
                json.loads(list_output.getvalue())["attempts"][0]["attempt_id"],
                "cli-attempt",
            )

            show_output = io.StringIO()
            with contextlib.redirect_stdout(show_output):
                self.assertEqual(
                    main(
                        [
                            "attempt",
                            "show",
                            "cli-attempt",
                            "--store-root",
                            str(store),
                        ]
                    ),
                    0,
                )
            self.assertEqual(json.loads(show_output.getvalue())["decisions"], [])

            decision_output = io.StringIO()
            with contextlib.redirect_stdout(decision_output):
                self.assertEqual(
                    main(
                        [
                            "attempt",
                            "decide",
                            "cli-attempt",
                            "--store-root",
                            str(store),
                            "--actor",
                            "agent",
                            "--decision",
                            "promote",
                            "--reason",
                            "Useful orchestration baseline; no gate claim is implied.",
                            "--ref",
                            "working-best",
                        ]
                    ),
                    0,
                )
            decision = json.loads(decision_output.getvalue())
            self.assertEqual(decision["decision"]["actor"], "agent")
            self.assertEqual(decision["ref"]["name"], "working-best")

            (store / "refs" / "manifest.json").unlink()
            rebuild_output = io.StringIO()
            with contextlib.redirect_stdout(rebuild_output):
                self.assertEqual(
                    main(
                        [
                            "attempt",
                            "rebuild-refs",
                            "--store-root",
                            str(store),
                        ]
                    ),
                    0,
                )
            rebuilt = json.loads(rebuild_output.getvalue())
            self.assertEqual(
                rebuilt["refs"]["working-best"]["attempt_digest"],
                attempt["attempt_digest"],
            )

            reason_error = io.StringIO()
            with contextlib.redirect_stderr(reason_error):
                self.assertEqual(
                    main(
                        [
                            "attempt",
                            "decide",
                            "cli-attempt",
                            "--store-root",
                            str(store),
                            "--actor",
                            "engineer",
                            "--decision",
                            "reject",
                            "--reason",
                            "   ",
                        ]
                    ),
                    2,
                )
            self.assertEqual(
                json.loads(reason_error.getvalue())["error"],
                "decision reason must not be empty",
            )


if __name__ == "__main__":
    unittest.main()
