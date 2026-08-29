"""Execution adapter protocol."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from ..types import ActionResult, CompiledPlan, SemanticAction


class ExecutionAdapter(Protocol):
    """Minimum solver boundary needed by the deterministic executor."""

    name: str

    def prepare(self, plan: CompiledPlan) -> None: ...

    def rehydrate(
        self,
        plan: CompiledPlan,
        completed_actions: frozenset[str],
        run_directory: Path,
    ) -> bool: ...

    def snapshot(self, *, scope: str = "all") -> Mapping[str, Any]: ...

    def execute(self, action: SemanticAction) -> ActionResult: ...

    def close(self) -> None: ...
