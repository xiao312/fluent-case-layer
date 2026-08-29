"""Public driver API for compilation, execution, and evidence."""

from .adapters import ExecutionAdapter, PyFluentAdapter, RecordingAdapter
from .campaign import CompiledCampaign, apply_campaign, compile_campaign
from .errors import AdapterMappingError
from .executor import ExecutionSummary, PlanExecutor, capture_snapshot
from .loading import AutoCaseLoader, CaseLoader, DirectoryCaseLoader, LoadedCase, load_case
from .planner import ValidationReport, compile_plan, dependency_order, validate_case
from .types import ActionKind, CompiledPlan, SemanticAction

__all__ = [
    "ActionKind",
    "AdapterMappingError",
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
    "capture_snapshot",
    "compile_campaign",
    "compile_plan",
    "dependency_order",
    "load_case",
    "validate_case",
]
