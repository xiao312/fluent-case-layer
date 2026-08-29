from __future__ import annotations

import unittest

from fluent_case_layer.driver.errors import CaseValidationError
from fluent_case_layer.driver.planner import compile_plan, validate_case


def explicit_case(stages):
    return {
        "schema_version": "1",
        "case_id": "test-case",
        "system": {"control": {"stages": stages}},
    }


class PlanCompilerTests(unittest.TestCase):
    def test_dependency_order_and_hash_are_stable(self) -> None:
        case = explicit_case(
            [
                {
                    "id": "run",
                    "action": "iterate",
                    "depends_on": ["setup"],
                    "parameters": {"iterations": 5},
                },
                {
                    "id": "launch",
                    "action": "launch_solver",
                    "parameters": {},
                },
                {
                    "id": "setup",
                    "action": "reconcile_settings",
                    "depends_on": ["launch"],
                    "parameters": {"operations": []},
                },
            ]
        )
        first = compile_plan(case, {"scheduler": {"ranks": 4}})
        second = compile_plan(case, {"scheduler": {"ranks": 4}})
        self.assertEqual([item.id for item in first.actions], ["launch", "setup", "run"])
        self.assertEqual(first.plan_hash, second.plan_hash)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_cycle_is_rejected(self) -> None:
        case = explicit_case(
            [
                {"id": "a", "action": "snapshot", "depends_on": ["b"]},
                {"id": "b", "action": "snapshot", "depends_on": ["a"]},
            ]
        )
        with self.assertRaisesRegex(CaseValidationError, "cycle"):
            compile_plan(case)

    def test_tui_escape_requires_full_audit_record(self) -> None:
        case = explicit_case(
            [{"id": "legacy", "action": "tui", "parameters": {"command": "/solve/x"}}]
        )
        report = validate_case(case)
        self.assertFalse(report.valid)
        self.assertIn("reason", report.issues[0].message)

    def test_inferred_plan_is_conservative_but_executable(self) -> None:
        case = {
            "case_id": "inferred",
            "constant": {"physics": {"solver": "pressure_based"}},
            "system": {
                "initialization": {"method": "hybrid"},
                "control": {"iterations": 3},
            },
        }
        plan = compile_plan(case)
        self.assertEqual(
            [item.kind.value for item in plan.actions],
            ["launch_solver", "reconcile_settings", "initialize", "iterate", "snapshot"],
        )


if __name__ == "__main__":
    unittest.main()
