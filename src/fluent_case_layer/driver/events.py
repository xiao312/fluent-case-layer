"""Append-only, hash-chained execution event ledger."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .errors import DriverError
from .util import canonical_json, stable_hash


class EventLog:
    """A small tamper-evident JSONL ledger.

    Each line includes the previous line's hash.  The ledger is append-only;
    derived summaries may be regenerated from it after interruption.
    """

    def __init__(self, path: Path, *, run_id: str, plan_hash: str) -> None:
        self.path = path
        self.run_id = run_id
        self.plan_hash = plan_hash

    def read(self, *, verify: bool = True) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        events: list[dict[str, Any]] = []
        previous: str | None = None
        for line_number, line in enumerate(self.path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DriverError(f"invalid event JSON at {self.path}:{line_number}") from exc
            if verify:
                if event.get("sequence") != len(events) + 1:
                    raise DriverError(f"event sequence is broken at {self.path}:{line_number}")
                if event.get("previous_event_hash") != previous:
                    raise DriverError(f"event hash chain is broken at {self.path}:{line_number}")
                supplied = event.get("event_hash")
                unsigned = dict(event)
                unsigned.pop("event_hash", None)
                if supplied != stable_hash(unsigned):
                    raise DriverError(f"event content hash is invalid at {self.path}:{line_number}")
                if event.get("run_id") != self.run_id or event.get("plan_hash") != self.plan_hash:
                    raise DriverError(
                        f"event belongs to a different run or plan at line {line_number}"
                    )
                previous = supplied
            events.append(event)
        return events

    def append(
        self,
        event_type: str,
        *,
        action_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        events = self.read()
        previous = events[-1]["event_hash"] if events else None
        event: dict[str, Any] = {
            "sequence": len(events) + 1,
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "run_id": self.run_id,
            "plan_hash": self.plan_hash,
            "event": event_type,
            "action_id": action_id,
            "payload": dict(payload or {}),
            "previous_event_hash": previous,
        }
        event["event_hash"] = stable_hash(event)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = (canonical_json(event) + "\n").encode("utf-8")
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            written = os.write(descriptor, data)
            if written != len(data):
                raise DriverError(f"short append to event log: {self.path}")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return event

    def successful_actions(self) -> set[str]:
        return {
            str(event["action_id"])
            for event in self.read()
            if event.get("event") == "action_succeeded" and event.get("action_id")
        }

    def attempts(self, action_id: str) -> int:
        return sum(
            1
            for event in self.read()
            if event.get("event") == "action_started" and event.get("action_id") == action_id
        )

    def events_of_type(self, *event_types: str) -> Iterable[dict[str, Any]]:
        accepted = set(event_types)
        return (event for event in self.read() if event.get("event") in accepted)
