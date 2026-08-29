"""Command-line surfaces for validate, plan, apply, snapshot, diff, and campaign."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .driver import (
    PlanExecutor,
    PyFluentAdapter,
    RecordingAdapter,
    apply_campaign,
    capture_snapshot,
    compile_campaign,
    compile_plan,
    load_case,
    validate_case,
)
from .driver.campaign import materialize_campaign_plans, validate_campaign
from .driver.errors import DriverError
from .driver.evidence import diff_values, read_json_document, write_plan_lock
from .driver.types import CompiledPlan
from .driver.util import atomic_write_json, canonical_json


def _print(value: Any, *, stream: Any = None) -> None:
    target = stream or sys.stdout
    target.write(canonical_json(value, pretty=True) + "\n")


def _adapter(name: str, plan: CompiledPlan):
    if name == "recording":
        return RecordingAdapter()
    if name == "pyfluent":
        return PyFluentAdapter()
    raise DriverError(f"unknown adapter: {name}")


def _load_plan(case: str, platform: str | None) -> CompiledPlan:
    loaded = load_case(case, platform)
    return compile_plan(loaded.case, loaded.platform)


def _command_validate(args: argparse.Namespace) -> int:
    loaded = load_case(args.case, args.platform)
    report = validate_case(loaded.case, loaded.platform)
    _print(report.to_dict())
    return 0 if report.valid else 2


def _command_plan(args: argparse.Namespace) -> int:
    plan = _load_plan(args.case, args.platform)
    if args.output:
        write_plan_lock(Path(args.output), plan)
    _print(plan.to_dict())
    return 0


def _default_run_directory(plan: CompiledPlan) -> Path:
    return Path(".fluent-case") / "runs" / plan.case_id / plan.plan_hash[:12]


def _command_apply(args: argparse.Namespace) -> int:
    plan = _load_plan(args.case, args.platform)
    directory = Path(args.run_dir) if args.run_dir else _default_run_directory(plan)
    executor = PlanExecutor(plan, _adapter(args.adapter, plan), directory, run_id=args.run_id)
    summary = executor.apply(resume=args.resume)
    _print(summary.to_dict())
    return 0


def _command_snapshot(args: argparse.Namespace) -> int:
    plan = _load_plan(args.case, args.platform)
    adapter = _adapter(args.adapter, plan)
    try:
        if args.adapter == "pyfluent":
            launch = next(
                (action for action in plan.actions if action.kind.value == "launch_solver"),
                None,
            )
            if launch is None:
                raise DriverError("PyFluent snapshot requires a launch_solver stage")
            adapter.execute(launch)
        payload = capture_snapshot(adapter, Path(args.output), scope=args.scope)
    finally:
        adapter.close()
    _print(payload)
    return 0


def _command_diff(args: argparse.Namespace) -> int:
    before = read_json_document(Path(args.before))
    after = read_json_document(Path(args.after))
    if args.state_only and isinstance(before, dict) and isinstance(after, dict):
        before = before.get("state", before)
        after = after.get("state", after)
    changes = diff_values(before, after)
    result = {"changed": bool(changes), "change_count": len(changes), "changes": changes}
    _print(result)
    return 1 if args.fail_on_change and changes else 0


def _command_campaign(args: argparse.Namespace) -> int:
    campaign = compile_campaign(args.campaign)
    if args.mode == "validate":
        result = validate_campaign(campaign)
        _print(result)
        return 0 if result["valid"] else 2
    output = Path(args.output_root)
    if args.mode == "plan":
        materialize_campaign_plans(campaign, output)
        _print(campaign.to_dict())
        return 0
    result = apply_campaign(
        campaign,
        output,
        lambda item: _adapter(args.adapter, item.plan),
        max_workers=args.max_workers,
        resume=args.resume,
    )
    atomic_write_json(output / campaign.id / "campaign-summary.json", result)
    _print(result)
    return 0 if result["status"] == "succeeded" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fluent-case",
        description="Typed, staged, auditable Fluent case orchestration",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate and compile case intent")
    validate.add_argument("case")
    validate.add_argument("--platform")
    validate.set_defaults(handler=_command_validate)

    plan = subparsers.add_parser("plan", help="print a canonical dependency-ordered plan")
    plan.add_argument("case")
    plan.add_argument("--platform")
    plan.add_argument("--output", help="write an immutable plan.lock.json")
    plan.set_defaults(handler=_command_plan)

    apply = subparsers.add_parser("apply", help="execute or resume a compiled plan")
    apply.add_argument("case")
    apply.add_argument("--platform")
    apply.add_argument("--run-dir")
    apply.add_argument("--run-id")
    apply.add_argument("--adapter", choices=("recording", "pyfluent"), default="recording")
    apply.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    apply.set_defaults(handler=_command_apply)

    snapshot = subparsers.add_parser("snapshot", help="capture observed adapter state")
    snapshot.add_argument("case")
    snapshot.add_argument("--platform")
    snapshot.add_argument("--adapter", choices=("recording", "pyfluent"), default="recording")
    snapshot.add_argument("--scope", default="all")
    snapshot.add_argument("--output", required=True)
    snapshot.set_defaults(handler=_command_snapshot)

    difference = subparsers.add_parser("diff", help="structurally diff observed snapshots")
    difference.add_argument("before")
    difference.add_argument("after")
    difference.add_argument("--state-only", action=argparse.BooleanOptionalAction, default=True)
    difference.add_argument("--fail-on-change", action="store_true")
    difference.set_defaults(handler=_command_diff)

    campaign = subparsers.add_parser("campaign", help="validate, plan, or apply a case matrix")
    campaign.add_argument("campaign")
    campaign.add_argument("--mode", choices=("validate", "plan", "apply"), default="plan")
    campaign.add_argument("--output-root", default=".fluent-case/campaigns")
    campaign.add_argument("--adapter", choices=("recording", "pyfluent"), default="recording")
    campaign.add_argument("--max-workers", type=int, default=1)
    campaign.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    campaign.set_defaults(handler=_command_campaign)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (DriverError, OSError, ValueError, json.JSONDecodeError) as exc:
        _print({"error_type": type(exc).__name__, "error": str(exc)}, stream=sys.stderr)
        return 2


def app() -> int:
    """Console-script entry point kept callable for packaging tools."""

    return main()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
