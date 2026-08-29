"""Immutable plan locks, snapshots, manifests, and structural state diffs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .errors import PlanConflictError
from .types import ArtifactRecord, CompiledPlan
from .util import atomic_write_json, canonical_json, file_sha256, stable_hash, to_jsonable


def write_plan_lock(path: Path, plan: CompiledPlan) -> None:
    """Write once, or prove that an existing lock is byte-equivalent."""

    desired = plan.to_dict()
    if path.exists():
        current = json.loads(path.read_text(encoding="utf-8"))
        if canonical_json(current) != canonical_json(desired):
            raise PlanConflictError(f"run directory already contains a different plan lock: {path}")
        return
    atomic_write_json(path, desired)


class SnapshotStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def write(
        self, action_id: str, attempt: int, phase: str, state: Mapping[str, Any]
    ) -> dict[str, Any]:
        safe_id = action_id.replace("/", "_").replace("..", "_")
        path = self.directory / f"{safe_id}.attempt-{attempt:03d}.{phase}.json"
        payload = {
            "action_id": action_id,
            "attempt": attempt,
            "phase": phase,
            "state": to_jsonable(state),
        }
        payload["snapshot_hash"] = stable_hash(payload)
        atomic_write_json(path, payload)
        return {
            "path": str(path),
            "sha256": file_sha256(path),
            "snapshot_hash": payload["snapshot_hash"],
        }


class ManifestStore:
    """Maintain a compact derived manifest; the event log remains authoritative."""

    def __init__(self, path: Path, *, manifest_type: str, plan_hash: str) -> None:
        self.path = path
        self.manifest_type = manifest_type
        self.plan_hash = plan_hash

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": "1",
                "manifest_type": self.manifest_type,
                "plan_hash": self.plan_hash,
                "entries": [],
            }
        return json.loads(self.path.read_text(encoding="utf-8"))

    def add(self, record: ArtifactRecord, *, action_id: str, attempt: int) -> dict[str, Any]:
        manifest = self._read()
        entry = record.to_dict()
        entry.update({"action_id": action_id, "attempt": attempt})
        entry = _fill_local_file_metadata(entry)
        identity = (entry.get("uri"), entry.get("role"), action_id, attempt)
        entries = manifest.setdefault("entries", [])
        if not any(
            (item.get("uri"), item.get("role"), item.get("action_id"), item.get("attempt"))
            == identity
            for item in entries
        ):
            entries.append(entry)
        entries.sort(
            key=lambda item: (item.get("action_id", ""), item.get("role", ""), item.get("uri", ""))
        )
        unsigned = dict(manifest)
        unsigned.pop("manifest_hash", None)
        manifest["manifest_hash"] = stable_hash(unsigned)
        atomic_write_json(self.path, manifest)
        return entry


def _fill_local_file_metadata(entry: dict[str, Any]) -> dict[str, Any]:
    uri = str(entry.get("uri", ""))
    parsed = urlparse(uri)
    if parsed.scheme == "file":
        path = Path(unquote(parsed.path))
    elif not parsed.scheme:
        path = Path(uri)
    else:
        return entry
    if path.is_file():
        entry.setdefault("sha256", file_sha256(path))
        entry.setdefault("size_bytes", path.stat().st_size)
    return entry


def read_json_document(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_values(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Return a deterministic RFC-6901-like structural diff."""

    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes: list[dict[str, Any]] = []
        keys = sorted(set(before) | set(after), key=str)
        for key in keys:
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            child = f"{path}/{escaped}"
            if key not in before:
                changes.append({"op": "add", "path": child, "after": to_jsonable(after[key])})
            elif key not in after:
                changes.append({"op": "remove", "path": child, "before": to_jsonable(before[key])})
            else:
                changes.extend(diff_values(before[key], after[key], child))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for index in range(max(len(before), len(after))):
            child = f"{path}/{index}"
            if index >= len(before):
                changes.append({"op": "add", "path": child, "after": to_jsonable(after[index])})
            elif index >= len(after):
                changes.append(
                    {"op": "remove", "path": child, "before": to_jsonable(before[index])}
                )
            else:
                changes.extend(diff_values(before[index], after[index], child))
        return changes
    if before != after:
        return [
            {
                "op": "replace",
                "path": path or "/",
                "before": to_jsonable(before),
                "after": to_jsonable(after),
            }
        ]
    return []
