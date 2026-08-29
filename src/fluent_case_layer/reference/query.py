"""Stable query helpers for agents and CLI callers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .catalog import load_catalog


def get_entry(entry_id: str, catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return one reference entry by its canonical ``file#/pointer`` id."""

    source = dict(catalog) if catalog is not None else load_catalog()
    for entry in source.get("entries", []):
        if entry.get("id") == entry_id:
            return dict(entry)
    raise KeyError(f"unknown dictionary entry: {entry_id}")


def find_entries(
    query: str = "",
    *,
    document: str | None = None,
    status: str | None = None,
    limit: int | None = None,
    catalog: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search catalog text with optional document and adapter-status filters."""

    source = dict(catalog) if catalog is not None else load_catalog()
    needle = query.casefold().strip()
    matches = []
    for raw_entry in source.get("entries", []):
        entry = dict(raw_entry)
        if document and entry.get("document") != document:
            continue
        if status and entry.get("coupling", {}).get("adapter", {}).get("status") != status:
            continue
        searchable = " ".join(
            str(value)
            for value in (
                entry.get("id", ""),
                entry.get("title", ""),
                entry.get("description", ""),
                entry.get("coupling", {}).get("fluent", {}).get("concept", ""),
                entry.get("coupling", {}).get("pyfluent", {}).get("path", ""),
                entry.get("coupling", {}).get("adapter", {}).get("note", ""),
            )
        ).casefold()
        if needle and needle not in searchable:
            continue
        matches.append(entry)
        if limit is not None and len(matches) >= limit:
            break
    return matches
