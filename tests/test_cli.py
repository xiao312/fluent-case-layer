from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from fluent_case_layer.cli import main


class CliTests(unittest.TestCase):
    def make_case(self, root: Path) -> Path:
        case = root / "case.json"
        case.write_text(
            json.dumps(
                {
                    "case_id": "cli-case",
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
            ),
            encoding="utf-8",
        )
        return case

    def test_validate_plan_apply_snapshot_and_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = self.make_case(root)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["validate", str(case)]), 0)
            self.assertTrue(json.loads(output.getvalue())["valid"])

            plan_lock = root / "standalone-plan.lock.json"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["plan", str(case), "--output", str(plan_lock)]), 0)
            self.assertTrue(plan_lock.exists())

            run_dir = root / "run"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["apply", str(case), "--run-dir", str(run_dir)]),
                    0,
                )
            self.assertTrue((run_dir / "events.jsonl").exists())

            before = root / "before.json"
            after = root / "after.json"
            before.write_text(json.dumps({"state": {"iteration": 1}}), encoding="utf-8")
            after.write_text(json.dumps({"state": {"iteration": 2}}), encoding="utf-8")
            diff_output = io.StringIO()
            with contextlib.redirect_stdout(diff_output):
                self.assertEqual(main(["diff", str(before), str(after)]), 0)
            self.assertEqual(json.loads(diff_output.getvalue())["change_count"], 1)


if __name__ == "__main__":
    unittest.main()
