"""Durable candidate attempts, append-only decisions, and recoverable named refs."""

from __future__ import annotations

import fcntl
import json
import os
import re
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .adapters.base import ExecutionAdapter
from .errors import DriverError, PlanConflictError
from .events import EventLog
from .executor import ExecutionSummary, PlanExecutor
from .types import CompiledPlan
from .util import atomic_write_json, canonical_json, file_sha256, stable_hash, to_jsonable

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_component(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized or normalized in {".", ".."} or not _SAFE_COMPONENT.fullmatch(normalized):
        raise DriverError(
            f"{label} must use only letters, numbers, dot, underscore, or hyphen and "
            "must not contain path separators"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    attempt_id: str
    case_id: str
    plan_hash: str
    status: str
    started_at: str
    completed_at: str | None
    candidate: Mapping[str, Any]
    evidence: Mapping[str, Any]
    orchestration_status: str
    numerical_status: str
    scientific_status: str
    objective_revision: Mapping[str, Any] = field(default_factory=dict)
    objective_content_digest: str | None = None
    state_ownership_mode: str | None = None
    state_ownership_digest: str | None = None
    summary: Mapping[str, Any] | None = None
    error: Mapping[str, Any] | None = None
    attempt_digest: str = ""

    def unsigned_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": "1",
            "attempt_id": self.attempt_id,
            "case_id": self.case_id,
            "plan_hash": self.plan_hash,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "candidate": dict(self.candidate),
            "evidence": dict(self.evidence),
            "orchestration_status": self.orchestration_status,
            "numerical_status": self.numerical_status,
            "scientific_status": self.scientific_status,
            "objective_revision": dict(self.objective_revision or {}),
            "objective_content_digest": self.objective_content_digest,
            "state_ownership_mode": self.state_ownership_mode,
            "state_ownership_digest": self.state_ownership_digest,
        }
        if self.summary is not None:
            result["summary"] = dict(self.summary)
        if self.error is not None:
            result["error"] = dict(self.error)
        return result

    def with_digest(self) -> AttemptRecord:
        return replace(self, attempt_digest=stable_hash(self.unsigned_dict()))

    def to_dict(self) -> dict[str, Any]:
        result = self.unsigned_dict()
        result["attempt_digest"] = self.attempt_digest or stable_hash(result)
        return result

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> AttemptRecord:
        record = cls(
            attempt_id=str(value["attempt_id"]),
            case_id=str(value["case_id"]),
            plan_hash=str(value["plan_hash"]),
            status=str(value["status"]),
            started_at=str(value["started_at"]),
            completed_at=(str(value["completed_at"]) if value.get("completed_at") else None),
            candidate=dict(value.get("candidate", {})),
            evidence=dict(value.get("evidence", {})),
            orchestration_status=str(value.get("orchestration_status", "not_started")),
            numerical_status=str(value.get("numerical_status", "not_evaluated")),
            scientific_status=str(value.get("scientific_status", "not_evaluated")),
            objective_revision=dict(value.get("objective_revision", {})),
            objective_content_digest=(
                str(value["objective_content_digest"])
                if value.get("objective_content_digest")
                else None
            ),
            state_ownership_mode=(
                str(value["state_ownership_mode"]) if value.get("state_ownership_mode") else None
            ),
            state_ownership_digest=(
                str(value["state_ownership_digest"])
                if value.get("state_ownership_digest")
                else None
            ),
            summary=dict(value["summary"]) if isinstance(value.get("summary"), Mapping) else None,
            error=dict(value["error"]) if isinstance(value.get("error"), Mapping) else None,
            attempt_digest=str(value.get("attempt_digest", "")),
        )
        if not record.attempt_digest or record.attempt_digest != stable_hash(
            record.unsigned_dict()
        ):
            raise DriverError(f"attempt record content hash is invalid: {record.attempt_id}")
        return record


class AttemptStore:
    """Filesystem-backed attempt and decision evidence below one explicit root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def new_attempt_id(self) -> str:
        return f"attempt-{uuid.uuid4()}"

    def run_directory(self, attempt_id: str) -> Path:
        identifier = _safe_component(attempt_id, "attempt id")
        return self.root / "runs" / identifier

    def _attempt_path(self, attempt_id: str) -> Path:
        identifier = _safe_component(attempt_id, "attempt id")
        return self.root / "attempts" / f"{identifier}.json"

    def _plan_path(self, plan_hash: str) -> Path:
        digest = _safe_component(plan_hash, "plan hash")
        return self.root / "plans" / f"{digest}.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.root / ".store.lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def begin(self, plan: CompiledPlan, attempt_id: str) -> AttemptRecord:
        identifier = _safe_component(attempt_id, "attempt id")
        candidate = plan.metadata.get("candidate")
        if not isinstance(candidate, Mapping):
            raise DriverError("attempt lifecycle requires a compiled candidate plan")
        expected_plan_hash = stable_hash(plan.unsigned_dict())
        if not plan.plan_hash or plan.plan_hash != expected_plan_hash:
            raise DriverError("candidate plan hash is missing or does not match its content")

        attempt_path = self._attempt_path(identifier)
        plan_path = self._plan_path(plan.plan_hash)
        objectives = plan.metadata.get("objectives", {})
        state_ownership = plan.metadata.get("state_ownership", {})
        state_policy = (
            state_ownership.get("policy", {}) if isinstance(state_ownership, Mapping) else {}
        )
        with self._locked():
            if attempt_path.exists():
                raise PlanConflictError(f"attempt id already exists: {identifier}")
            plan_document = plan.to_dict()
            if plan_path.exists():
                existing = json.loads(plan_path.read_text(encoding="utf-8"))
                if canonical_json(existing) != canonical_json(plan_document):
                    raise PlanConflictError(
                        f"content-addressed plan object conflicts with {plan.plan_hash}"
                    )
            else:
                atomic_write_json(plan_path, plan_document)
            relative_plan = plan_path.relative_to(self.root).as_posix()
            record = AttemptRecord(
                attempt_id=identifier,
                case_id=plan.case_id,
                plan_hash=plan.plan_hash,
                status="running",
                started_at=_timestamp(),
                completed_at=None,
                candidate=dict(candidate),
                evidence={
                    "run_directory": self.run_directory(identifier)
                    .relative_to(self.root)
                    .as_posix(),
                    "plan_object": {
                        "path": relative_plan,
                        "sha256": file_sha256(plan_path),
                    },
                },
                orchestration_status="running",
                numerical_status="not_evaluated",
                scientific_status="not_evaluated",
                objective_revision=(
                    dict(objectives.get("revision", {})) if isinstance(objectives, Mapping) else {}
                ),
                objective_content_digest=(
                    str(objectives["content_digest"])
                    if isinstance(objectives, Mapping) and objectives.get("content_digest")
                    else None
                ),
                state_ownership_mode=(
                    str(state_policy["mode"])
                    if isinstance(state_policy, Mapping) and state_policy.get("mode")
                    else None
                ),
                state_ownership_digest=(
                    str(state_ownership["content_digest"])
                    if isinstance(state_ownership, Mapping)
                    and state_ownership.get("content_digest")
                    else None
                ),
            ).with_digest()
            atomic_write_json(attempt_path, record.to_dict())
        return record

    def finish(
        self,
        started: AttemptRecord,
        *,
        summary: ExecutionSummary | Mapping[str, Any] | None,
        error: Exception | None,
    ) -> AttemptRecord:
        attempt_path = self._attempt_path(started.attempt_id)
        current = self.load(started.attempt_id, verify_run=False)
        if current.status != "running" or current.attempt_digest != started.attempt_digest:
            raise PlanConflictError(f"attempt record changed while running: {started.attempt_id}")

        run_directory = self.run_directory(started.attempt_id)
        summary_mapping: dict[str, Any] | None
        if isinstance(summary, ExecutionSummary):
            summary_mapping = summary.to_dict()
        elif isinstance(summary, Mapping):
            summary_mapping = dict(to_jsonable(summary))
        else:
            summary_path = run_directory / "run-summary.json"
            summary_mapping = (
                dict(json.loads(summary_path.read_text(encoding="utf-8")))
                if summary_path.is_file()
                else None
            )
        evidence = {**dict(started.evidence), **self._run_evidence(started, run_directory)}
        succeeded = error is None and summary_mapping is not None
        record = AttemptRecord(
            attempt_id=started.attempt_id,
            case_id=started.case_id,
            plan_hash=started.plan_hash,
            status="succeeded" if succeeded else "failed",
            started_at=started.started_at,
            completed_at=_timestamp(),
            candidate=dict(started.candidate),
            evidence=evidence,
            orchestration_status=(
                str(summary_mapping.get("orchestration_status", "succeeded"))
                if summary_mapping is not None
                else "failed"
            ),
            numerical_status=(
                str(summary_mapping.get("numerical_status", "not_evaluated"))
                if summary_mapping is not None
                else "not_evaluated"
            ),
            scientific_status=(
                str(summary_mapping.get("scientific_status", "not_evaluated"))
                if summary_mapping is not None
                else "not_evaluated"
            ),
            objective_revision=dict(started.objective_revision or {}),
            objective_content_digest=started.objective_content_digest,
            state_ownership_mode=started.state_ownership_mode,
            state_ownership_digest=started.state_ownership_digest,
            summary=summary_mapping,
            error=(
                {"error_type": type(error).__name__, "error": str(error)}
                if error is not None
                else None
            ),
        ).with_digest()
        atomic_write_json(attempt_path, record.to_dict())
        return record

    def _run_evidence(
        self, record: AttemptRecord, run_directory: Path
    ) -> dict[str, Mapping[str, Any]]:
        evidence: dict[str, Mapping[str, Any]] = {}
        names = {
            "plan_lock": "plan.lock.json",
            "events": "events.jsonl",
            "run_metadata": "run.meta.json",
            "run_summary": "run-summary.json",
            "artifacts_manifest": "artifacts.manifest.json",
            "checkpoints_manifest": "checkpoints.manifest.json",
        }
        for key, filename in names.items():
            path = run_directory / filename
            if not path.is_file():
                continue
            item: dict[str, Any] = {
                "path": path.relative_to(self.root).as_posix(),
                "sha256": file_sha256(path),
            }
            if key == "events":
                events = EventLog(
                    path,
                    run_id=record.attempt_id,
                    plan_hash=record.plan_hash,
                ).read()
                item["tail_event_hash"] = events[-1]["event_hash"] if events else None
            evidence[key] = item
        return evidence

    def load(self, attempt_id: str, *, verify_run: bool = True) -> AttemptRecord:
        path = self._attempt_path(attempt_id)
        if not path.is_file():
            raise DriverError(f"attempt does not exist: {attempt_id}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise DriverError(f"attempt record must be a mapping: {path}")
        record = AttemptRecord.from_mapping(value)
        if record.attempt_id != _safe_component(attempt_id, "attempt id"):
            raise DriverError(f"attempt record id does not match its path: {path}")
        self._verify_plan_object(record)
        if verify_run:
            self._verify_run_evidence(record)
        return record

    def list(self) -> tuple[AttemptRecord, ...]:
        directory = self.root / "attempts"
        if not directory.is_dir():
            return ()
        records = [self.load(path.stem) for path in sorted(directory.glob("*.json"))]
        return tuple(sorted(records, key=lambda item: (item.started_at, item.attempt_id)))

    def show(self, attempt_id: str) -> dict[str, Any]:
        record = self.load(attempt_id)
        decisions = [
            item for item in self._read_decisions() if item.get("attempt_id") == record.attempt_id
        ]
        if any(
            item.get("attempt_digest") != record.attempt_digest
            or item.get("plan_hash") != record.plan_hash
            for item in decisions
        ):
            raise DriverError(
                f"decision evidence does not match retained attempt {record.attempt_id}"
            )
        return {"attempt": record.to_dict(), "decisions": decisions}

    def _resolve_evidence_path(self, value: Any) -> Path:
        relative = Path(str(value))
        if relative.is_absolute():
            raise DriverError("attempt evidence paths must be relative to the attempt store")
        resolved = (self.root / relative).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise DriverError("attempt evidence path escapes the attempt store") from exc
        return resolved

    def _verify_plan_object(self, record: AttemptRecord) -> None:
        item = record.evidence.get("plan_object")
        if not isinstance(item, Mapping):
            raise DriverError(f"attempt {record.attempt_id} has no plan object evidence")
        path = self._resolve_evidence_path(item.get("path"))
        if not path.is_file() or file_sha256(path) != item.get("sha256"):
            raise DriverError(
                f"attempt {record.attempt_id} plan object evidence is missing or tampered"
            )
        plan = json.loads(path.read_text(encoding="utf-8"))
        supplied = plan.get("plan_hash") if isinstance(plan, Mapping) else None
        unsigned = dict(plan) if isinstance(plan, Mapping) else {}
        unsigned.pop("plan_hash", None)
        if supplied != record.plan_hash or stable_hash(unsigned) != record.plan_hash:
            raise DriverError(
                f"attempt {record.attempt_id} plan object does not match its plan hash"
            )

    def _verify_run_evidence(self, record: AttemptRecord) -> None:
        if record.status == "running":
            return
        for name, item in record.evidence.items():
            if name in {"run_directory", "plan_object"} or not isinstance(item, Mapping):
                continue
            path = self._resolve_evidence_path(item.get("path"))
            if not path.is_file() or file_sha256(path) != item.get("sha256"):
                raise DriverError(
                    f"attempt {record.attempt_id} {name} evidence is missing or tampered"
                )
        plan_lock = record.evidence.get("plan_lock")
        if isinstance(plan_lock, Mapping):
            path = self._resolve_evidence_path(plan_lock.get("path"))
            value = json.loads(path.read_text(encoding="utf-8"))
            supplied = value.get("plan_hash") if isinstance(value, Mapping) else None
            unsigned = dict(value) if isinstance(value, Mapping) else {}
            unsigned.pop("plan_hash", None)
            if supplied != record.plan_hash or stable_hash(unsigned) != record.plan_hash:
                raise DriverError(
                    f"attempt {record.attempt_id} run plan does not match its recorded plan hash"
                )
        events_item = record.evidence.get("events")
        if isinstance(events_item, Mapping):
            path = self._resolve_evidence_path(events_item.get("path"))
            events = EventLog(
                path,
                run_id=record.attempt_id,
                plan_hash=record.plan_hash,
            ).read()
            tail = events[-1]["event_hash"] if events else None
            if tail != events_item.get("tail_event_hash"):
                raise DriverError(f"attempt {record.attempt_id} event tail hash is invalid")
        if record.status == "succeeded":
            required = {"plan_lock", "events", "run_metadata", "run_summary"}
            missing = sorted(required - set(record.evidence))
            if missing:
                raise DriverError(
                    f"successful attempt {record.attempt_id} lacks run evidence: "
                    + ", ".join(missing)
                )

    def decide(
        self,
        attempt_id: str,
        *,
        actor: str,
        decision: str,
        reason: str,
        ref_name: str | None = None,
    ) -> dict[str, Any]:
        record = self.load(attempt_id)
        normalized_actor = actor.strip()
        normalized_decision = decision.strip()
        normalized_reason = reason.strip()
        if normalized_actor not in {"agent", "engineer"}:
            raise DriverError("decision actor must be 'agent' or 'engineer'")
        if normalized_decision not in {"promote", "reject"}:
            raise DriverError("decision must be 'promote' or 'reject'")
        if not normalized_reason:
            raise DriverError("decision reason must not be empty")
        if normalized_decision == "promote":
            if record.status != "succeeded" or record.orchestration_status != "succeeded":
                raise DriverError("only an orchestration-successful attempt can be promoted")
            if ref_name is None:
                raise DriverError("promotion requires a named ref")
            normalized_ref = _safe_component(ref_name, "ref name")
        else:
            if ref_name is not None:
                raise DriverError("rejection must not update a named ref")
            normalized_ref = None

        with self._locked():
            decisions = self._read_decisions()
            if normalized_ref is not None:
                self._assert_ref_manifest_consistent(decisions)
            predecessor = self._latest_ref_target(decisions, normalized_ref)
            # The hash-chained decision is authoritative and is appended first.
            # If the following atomic derived-manifest update is interrupted,
            # rebuild_refs() deterministically replays this decision ledger.
            event = self._append_decision(
                record,
                actor=normalized_actor,
                decision=normalized_decision,
                reason=normalized_reason,
                ref_name=normalized_ref,
                predecessor=predecessor,
                decisions=decisions,
            )
            ref = (
                self._update_ref(record, normalized_ref, event)
                if normalized_ref is not None
                else None
            )
        return {"decision": event, "ref": ref}

    def _read_decisions(self) -> list[dict[str, Any]]:
        path = self.root / "decisions.jsonl"
        if not path.is_file():
            return []
        decisions: list[dict[str, Any]] = []
        previous: str | None = None
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DriverError(f"invalid decision JSON at {path}:{line_number}") from exc
            if event.get("sequence") != len(decisions) + 1:
                raise DriverError(f"decision sequence is broken at {path}:{line_number}")
            if event.get("previous_decision_hash") != previous:
                raise DriverError(f"decision hash chain is broken at {path}:{line_number}")
            supplied = event.get("decision_hash")
            unsigned = dict(event)
            unsigned.pop("decision_hash", None)
            if supplied != stable_hash(unsigned):
                raise DriverError(f"decision content hash is invalid at {path}:{line_number}")
            previous = str(supplied)
            decisions.append(event)
        return decisions

    def _append_decision(
        self,
        record: AttemptRecord,
        *,
        actor: str,
        decision: str,
        reason: str,
        ref_name: str | None,
        predecessor: Mapping[str, Any] | None,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        event: dict[str, Any] = {
            "schema_version": "1",
            "sequence": len(decisions) + 1,
            "timestamp": _timestamp(),
            "attempt_id": record.attempt_id,
            "attempt_digest": record.attempt_digest,
            "plan_hash": record.plan_hash,
            "actor": actor,
            "decision": decision,
            "reason": reason,
            "ref_name": ref_name,
            "predecessor": dict(predecessor) if predecessor is not None else None,
            "previous_decision_hash": (decisions[-1]["decision_hash"] if decisions else None),
        }
        event["decision_hash"] = stable_hash(event)
        path = self.root / "decisions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (canonical_json(event) + "\n").encode("utf-8")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            written = os.write(descriptor, data)
            if written != len(data):
                raise DriverError(f"short append to decision log: {path}")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return event

    @staticmethod
    def _latest_ref_target(
        decisions: list[dict[str, Any]], ref_name: str | None
    ) -> dict[str, Any] | None:
        if ref_name is None:
            return None
        for event in reversed(decisions):
            if event.get("decision") == "promote" and event.get("ref_name") == ref_name:
                return {
                    "attempt_id": event["attempt_id"],
                    "attempt_digest": event["attempt_digest"],
                    "plan_hash": event["plan_hash"],
                    "decision_hash": event["decision_hash"],
                }
        return None

    def _update_ref(
        self,
        record: AttemptRecord,
        ref_name: str,
        decision: Mapping[str, Any],
    ) -> dict[str, Any]:
        object_path = self.root / "refs" / "objects" / f"{record.attempt_digest}.json"
        document = record.to_dict()
        if object_path.exists():
            existing = json.loads(object_path.read_text(encoding="utf-8"))
            if canonical_json(existing) != canonical_json(document):
                raise DriverError(
                    f"promoted attempt object conflicts with digest {record.attempt_digest}"
                )
        else:
            atomic_write_json(object_path, document)

        manifest_path = self.root / "refs" / "manifest.json"
        manifest = self._read_ref_manifest() or {"schema_version": "1", "refs": {}}
        refs = manifest.setdefault("refs", {})
        if not isinstance(refs, dict):
            raise DriverError(f"named ref manifest refs must be a mapping: {manifest_path}")
        entry = {
            "attempt_id": record.attempt_id,
            "attempt_digest": record.attempt_digest,
            "plan_hash": record.plan_hash,
            "object": object_path.relative_to(self.root).as_posix(),
            "decision_hash": decision["decision_hash"],
            "updated_at": decision["timestamp"],
            "predecessor": decision.get("predecessor"),
        }
        refs[ref_name] = entry
        unsigned = dict(manifest)
        unsigned.pop("manifest_hash", None)
        manifest["manifest_hash"] = stable_hash(unsigned)
        atomic_write_json(manifest_path, manifest)
        return {"name": ref_name, **entry, "manifest_hash": manifest["manifest_hash"]}

    def _read_ref_manifest(self) -> dict[str, Any] | None:
        manifest_path = self.root / "refs" / "manifest.json"
        if not manifest_path.is_file():
            return None
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise DriverError(f"named ref manifest must be a mapping: {manifest_path}")
        manifest = dict(value)
        supplied = manifest.get("manifest_hash")
        unsigned = dict(manifest)
        unsigned.pop("manifest_hash", None)
        if supplied != stable_hash(unsigned):
            raise DriverError(f"named ref manifest content hash is invalid: {manifest_path}")
        if not isinstance(manifest.get("refs"), Mapping):
            raise DriverError(f"named ref manifest refs must be a mapping: {manifest_path}")
        return manifest

    def _assert_ref_manifest_consistent(self, decisions: list[dict[str, Any]]) -> None:
        expected: dict[str, dict[str, Any]] = {}
        for event in decisions:
            if event.get("decision") != "promote" or not event.get("ref_name"):
                continue
            expected[str(event["ref_name"])] = {
                "attempt_id": event["attempt_id"],
                "attempt_digest": event["attempt_digest"],
                "plan_hash": event["plan_hash"],
                "decision_hash": event["decision_hash"],
                "predecessor": event.get("predecessor"),
            }
        manifest = self._read_ref_manifest()
        if manifest is None:
            if expected:
                raise DriverError(
                    "named ref manifest is missing after recorded promotions; call "
                    "AttemptStore.rebuild_refs() before another promotion"
                )
            return
        refs = manifest["refs"]
        if set(refs) != set(expected):
            raise DriverError(
                "named ref manifest does not match the decision ledger; call "
                "AttemptStore.rebuild_refs()"
            )
        for name, target in expected.items():
            current = refs[name]
            if not isinstance(current, Mapping) or any(
                current.get(key) != value for key, value in target.items()
            ):
                raise DriverError(
                    f"named ref {name!r} does not match the decision ledger; call "
                    "AttemptStore.rebuild_refs()"
                )

    def rebuild_refs(self) -> dict[str, Any]:
        """Recover the derived named-ref manifest from authoritative decisions."""

        with self._locked():
            decisions = self._read_decisions()
            refs: dict[str, Any] = {}
            for decision in decisions:
                if decision.get("decision") != "promote" or not decision.get("ref_name"):
                    continue
                record = self.load(str(decision["attempt_id"]))
                if record.attempt_digest != decision.get(
                    "attempt_digest"
                ) or record.plan_hash != decision.get("plan_hash"):
                    raise DriverError(
                        f"promotion decision does not match attempt {record.attempt_id}"
                    )
                object_path = self.root / "refs" / "objects" / f"{record.attempt_digest}.json"
                document = record.to_dict()
                if object_path.exists():
                    existing = json.loads(object_path.read_text(encoding="utf-8"))
                    if canonical_json(existing) != canonical_json(document):
                        raise DriverError(
                            f"promoted attempt object conflicts with digest {record.attempt_digest}"
                        )
                else:
                    atomic_write_json(object_path, document)
                refs[str(decision["ref_name"])] = {
                    "attempt_id": record.attempt_id,
                    "attempt_digest": record.attempt_digest,
                    "plan_hash": record.plan_hash,
                    "object": object_path.relative_to(self.root).as_posix(),
                    "decision_hash": decision["decision_hash"],
                    "updated_at": decision["timestamp"],
                    "predecessor": decision.get("predecessor"),
                }
            manifest: dict[str, Any] = {
                "schema_version": "1",
                "refs": refs,
                "recovered_from_decision_hash": (
                    decisions[-1]["decision_hash"] if decisions else None
                ),
            }
            manifest["manifest_hash"] = stable_hash(manifest)
            atomic_write_json(self.root / "refs" / "manifest.json", manifest)
        return manifest


def apply_candidate_attempt(
    plan: CompiledPlan,
    adapter: ExecutionAdapter,
    store: AttemptStore | Path,
    *,
    attempt_id: str | None = None,
) -> AttemptRecord:
    """Execute one candidate while retaining a compact record for either outcome."""

    attempt_store = store if isinstance(store, AttemptStore) else AttemptStore(store)
    identifier = attempt_id or attempt_store.new_attempt_id()
    started = attempt_store.begin(plan, identifier)
    summary: ExecutionSummary | None = None
    error: Exception | None = None
    try:
        summary = PlanExecutor(
            plan,
            adapter,
            attempt_store.run_directory(identifier),
            run_id=identifier,
        ).apply(resume=False)
    except Exception as exc:  # noqa: BLE001 - lifecycle retains all execution failures
        error = exc
        try:
            adapter.close()
        except Exception:  # noqa: BLE001, S110 - primary failure remains authoritative
            # The durable attempt error above remains the authoritative outcome.
            pass
    return attempt_store.finish(started, summary=summary, error=error)
