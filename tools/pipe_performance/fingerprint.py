"""Logical fingerprints for comparing pipe outputs across physical layouts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import lance


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_records(records: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(_stable_json(record).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def lance_table_fingerprint(
    dataset_path: Path,
    *,
    columns: Sequence[str],
    sort_by: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Fingerprint selected logical columns from a Lance dataset."""
    table = lance.dataset(str(dataset_path)).to_table(columns=list(columns))
    rows = table.to_pylist()
    if sort_by:
        rows.sort(key=lambda row: tuple(str(row.get(key, "")) for key in sort_by))
    return {
        "rows": len(rows),
        "columns": list(columns),
        "hash": hash_records(rows),
    }


def jsonl_fingerprint(path: Path, *, sort_lines: bool = False) -> dict[str, Any]:
    """Fingerprint a JSONL/text sidecar file."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    normalized = [line.strip() for line in lines if line.strip()]
    if sort_lines:
        normalized.sort()
    digest = hashlib.sha256()
    for line in normalized:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return {
        "rows": len(normalized),
        "hash": digest.hexdigest(),
    }


def compare_fingerprints(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Return a tiny comparison payload for two fingerprint dictionaries."""
    return {
        "match": left == right,
        "left": left,
        "right": right,
    }
