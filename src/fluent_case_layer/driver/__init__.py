"""Public driver API for compilation, execution, and evidence."""

from .adapters import ExecutionAdapter, PyFluentAdapter, RecordingAdapter
from .attempts import AttemptRecord, AttemptStore, apply_candidate_attempt
from .campaign import CompiledCampaign, apply_campaign, compile_campaign
from .candidate import compile_candidate_plan
from .errors import AdapterMappingError
from .executor import ExecutionSummary, PlanExecutor, capture_snapshot
from .loading import AutoCaseLoader, CaseLoader, DirectoryCaseLoader, LoadedCase, load_case
from .planner import ValidationReport, compile_plan, dependency_order, validate_case
from .types import ActionKind, CompiledPlan, SemanticAction

__all__ = [
    "ActionKind",
    "AdapterMappingError",
    "AttemptRecord",
    "AttemptStore",
    "AutoCaseLoader",
    "CaseLoader",
    "CompiledCampaign",
    "CompiledPlan",
    "DirectoryCaseLoader",
    "ExecutionAdapter",
    "ExecutionSummary",
    "LoadedCase",
    "PlanExecutor",
    "PyFluentAdapter",
    "RecordingAdapter",
    "SemanticAction",
    "ValidationReport",
    "apply_campaign",
    "apply_candidate_attempt",
    "capture_snapshot",
    "compile_campaign",
    "compile_candidate_plan",
    "compile_plan",
    "dependency_order",
    "load_case",
    "validate_case",
]
