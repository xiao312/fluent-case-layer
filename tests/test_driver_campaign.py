from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fluent_case_layer.driver.adapters.recording import RecordingAdapter
from fluent_case_layer.driver.campaign import apply_campaign, compile_campaign
from fluent_case_layer.driver.errors import CaseValidationError


class CampaignTests(unittest.TestCase):
    def test_matrix_expands_and_runs_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            case = root / "case"
            (case / "constant").mkdir(parents=True)
            (case / "system").mkdir()
            (case / "constant" / "physics.yaml").write_text(
                json.dumps({"case_id": "matrix-case", "variant": "base"}), encoding="utf-8"
            )
            (case / "system" / "control.yaml").write_text(
                json.dumps(
                    {
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
                ),
                encoding="utf-8",
            )
            campaign_path = root / "campaign.json"
            campaign_path.write_text(
                json.dumps(
                    {
                        "campaign_id": "matrix",
                        "cases": [
                            {
                                "id": "flame",
                                "path": "case",
                                "matrix": {"constant.physics.variant": ["a", "b"]},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            campaign = compile_campaign(campaign_path)
            self.assertEqual(len(campaign.cases), 2)
            self.assertEqual(campaign.cases[0].source, "case")
            self.assertNotEqual(campaign.cases[0].plan.plan_hash, campaign.cases[1].plan.plan_hash)
            result = apply_campaign(
                campaign,
                root / "runs",
                lambda item: RecordingAdapter(),
                max_workers=2,
            )
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(len(result["cases"]), 2)

    def test_canonical_overlays_are_revalidated_and_identity_is_portable(self) -> None:
        template = Path(__file__).resolve().parents[1] / "case"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign_hashes = []
            for checkout in (root / "checkout-a", root / "checkout-b"):
                shutil.copytree(template, checkout / "case")
                campaign_path = checkout / "campaign.json"
                campaign_path.write_text(
                    json.dumps(
                        {
                            "campaign_id": "canonical-pressure-variant",
                            "cases": [
                                {
                                    "id": "reacting",
                                    "path": "case",
                                    "overlay": {
                                        "physics": {
                                            "solver": {
                                                "operating_pressure": {
                                                    "value": 2.5,
                                                    "unit": "MPa",
                                                }
                                            }
                                        }
                                    },
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                campaign = compile_campaign(campaign_path)
                campaign_hashes.append(campaign.campaign_hash)
                self.assertEqual(campaign.cases[0].source, "case")
                configure = next(
                    action for action in campaign.cases[0].plan.actions if action.id == "configure"
                )
                pressure = configure.parameters["desired"]["physics"]["solver"][
                    "operating_pressure"
                ]
                self.assertEqual(pressure, {"value": 2.5, "unit": "MPa"})
            self.assertEqual(campaign_hashes[0], campaign_hashes[1])

            invalid_path = root / "invalid-campaign.json"
            invalid_path.write_text(
                json.dumps(
                    {
                        "campaign_id": "invalid-platform-reference",
                        "cases": [
                            {
                                "id": "broken",
                                "path": str(root / "checkout-a" / "case"),
                                "overlay": {"control": {"default_platform": "missing-platform"}},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CaseValidationError, "invalid after overlay.*unknown platforms"
            ):
                compile_campaign(invalid_path)

    def test_representative_recording_campaign_prepares_every_referenced_asset(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        campaign = compile_campaign(repository / "examples" / "campaign.yaml")
        plans = {item.id: item.plan for item in campaign.cases}

        def references(case_id: str, action_id: str) -> set[str]:
            action = next(action for action in plans[case_id].actions if action.id == action_id)
            return {asset["id"] for asset in action.parameters.get("referenced_assets", ())}

        self.assertEqual(
            references("m2-torch-igniter", "restore-checkpoint"),
            {"m2-checkpoint-case", "m2-checkpoint-data"},
        )
        self.assertEqual(
            references("effusion-drm19-fgm", "declare-meshing-intent"),
            {"combustor-effusion-pmdb"},
        )
        self.assertEqual(
            references("effusion-drm19-fgm", "build-fgm"),
            {"drm19-chemkin", "drm19-thermo"},
        )
        self.assertEqual(
            references("transient-1d-h2-air", "configure"),
            {"chemistry-udf", "h2o2-chemkin", "h2o2-thermo", "h2o2-transport"},
        )
        all_references = {
            asset["id"]
            for plan in plans.values()
            for action in plan.actions
            for asset in action.parameters.get("referenced_assets", ())
        }
        self.assertNotIn("m2-checkpoint-mesh", all_references)
        self.assertNotIn("tutorial-source-archive", all_references)

        with tempfile.TemporaryDirectory() as temporary:
            result = apply_campaign(
                campaign,
                Path(temporary),
                lambda item: RecordingAdapter(),
                max_workers=3,
            )
        self.assertEqual(result["status"], "succeeded")
        for item in result["cases"].values():
            self.assertEqual(item["orchestration_status"], "succeeded")
            self.assertEqual(item["numerical_status"], "not_evaluated")
            self.assertEqual(item["scientific_status"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()
