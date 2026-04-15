"""Workspace helpers for repeatable local pipe experiments."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_IGNORE_PATTERNS = (
    "__pycache__",
    ".pytest_cache",
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    "cache",
    "tmp",
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def create_run_dir(root: Path, *, group: str, run_name: str | None = None) -> Path:
    """Create a stable run directory with standard subfolders."""
    run_name = run_name or f"run_{utc_stamp()}"
    run_dir = root / "runs" / group / run_name
    for child in ("code", "output", "reports", "logs"):
        (run_dir / child).mkdir(parents=True, exist_ok=True)
    return run_dir


def copy_code_snapshot(source: Path, dest: Path, *, ignore_patterns: Iterable[str] = DEFAULT_IGNORE_PATTERNS) -> None:
    """Copy source code into ``dest`` while ignoring local caches and bytecode."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns(*ignore_patterns))


def write_manifest(path: Path, data: dict[str, Any]) -> None:
    """Write a JSON-compatible manifest.

    The file extension can be `.json` or `.yaml`; this helper intentionally uses
    simple JSON text so it has no optional YAML dependency.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
