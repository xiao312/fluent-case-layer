"""Canonical serialization, hashing, and small filesystem helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Project common typed values into deterministic JSON-compatible data."""

    if hasattr(value, "model_dump"):
        return to_jsonable(value.model_dump(mode="json", by_alias=True, exclude_none=True))
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "value") and isinstance(value.value, (str, int, float, bool)):
        return value.value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"cannot serialize {type(value).__name__} as canonical JSON")


def canonical_json(value: Any, *, pretty: bool = False) -> str:
    kwargs: dict[str, Any] = {
        "sort_keys": True,
        "ensure_ascii": False,
        "allow_nan": False,
    }
    if pretty:
        kwargs.update(indent=2)
    else:
        kwargs.update(separators=(",", ":"))
    return json.dumps(to_jsonable(value), **kwargs)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(value, pretty=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def dotted_get(value: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = value
    if not path:
        return True, current
    for component in path.split("."):
        if isinstance(current, Mapping) and component in current:
            current = current[component]
            continue
        if isinstance(current, (list, tuple)) and component.isdigit():
            index = int(component)
            if 0 <= index < len(current):
                current = current[index]
                continue
        return False, None
    return True, current


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = {str(key): to_jsonable(item) for key, item in base.items()}
    for key, value in overlay.items():
        key = str(key)
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = to_jsonable(value)
    return result


def dotted_set(target: dict[str, Any], path: str, value: Any) -> None:
    components = path.split(".")
    current = target
    for component in components[:-1]:
        child = current.get(component)
        if not isinstance(child, dict):
            child = {}
            current[component] = child
        current = child
    current[components[-1]] = to_jsonable(value)
