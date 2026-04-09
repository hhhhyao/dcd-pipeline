"""Conftest for parse_html pipe tests."""

from __future__ import annotations

import importlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

PIPE_PARENT = Path(__file__).resolve().parents[2]
PIPE_PARENT_REL = os.path.relpath(PIPE_PARENT, Path.cwd())
if PIPE_PARENT_REL not in sys.path:
    sys.path.insert(0, PIPE_PARENT_REL)

if "parse_html" not in sys.modules:
    sys.modules["parse_html"] = importlib.import_module("stage2_parse_html")

FIXTURES_DIR = Path(__file__).parent / "fixtures"

EXPECTED_VARIANTS: list[tuple[str, dict[str, Any]]] = [
    ("expected.md", {}),
    ("expected.html", {"out_format": "html"}),
    ("expected-noref.md", {"remove_ref": True}),
    ("expected-noref.html", {"remove_ref": True, "out_format": "html"}),
]


@dataclass
class HTMLFixtureCase:
    """A single test variant loaded from a fixture directory.

    Layout::

        case_name/
          input.html           # the ``data`` field (required)
          input.json           # non-content fields: id, url, … (optional)
          expected.json        # assertions on non-content output (optional)
          expected.md          # expected md output
          expected.html        # expected simple-html output
          expected-noref.md    # expected md output with remove_ref
          expected-noref.html  # expected simple-html output with remove_ref

    Each ``expected*`` file that exists produces a separate test case.
    """

    name: str
    input_item: dict[str, Any] = field(default_factory=dict)
    expected_item: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)


def load_variants(case_dir: Path, prefix: str = "") -> list[HTMLFixtureCase]:
    """Load all test variants from *case_dir*."""
    input_meta: dict[str, Any] = {}
    meta_path = case_dir / "input.json"
    if meta_path.exists():
        input_meta = json.loads(meta_path.read_text(encoding="utf-8"))

    input_html = (case_dir / "input.html").read_text(encoding="utf-8")
    input_item = {**input_meta, "data": input_html}
    input_item.setdefault("id", case_dir.name)

    expected_meta: dict[str, Any] = {}
    exp_meta_path = case_dir / "expected.json"
    if exp_meta_path.exists():
        expected_meta = json.loads(
            exp_meta_path.read_text(encoding="utf-8"),
        )

    cases: list[HTMLFixtureCase] = []
    for filename, config in EXPECTED_VARIANTS:
        expected_path = case_dir / filename
        if not expected_path.exists():
            continue

        expected_data = expected_path.read_text(encoding="utf-8")
        expected_item = {**expected_meta, "data": expected_data}
        expected_item.setdefault("id", input_item["id"])

        tag = filename.replace("expected", "").replace(".", "")
        label = f"{prefix}{case_dir.name}" if not tag else (
            f"{prefix}{case_dir.name}[{tag}]"
        )
        cases.append(HTMLFixtureCase(
            name=label,
            input_item=input_item,
            expected_item=expected_item,
            config=config,
        ))
    return cases


def collect_html_cases(
    root: Path | None = None,
    prefix: str = "",
) -> list[HTMLFixtureCase]:
    """Recursively discover fixture cases under *root*."""
    if root is None:
        root = FIXTURES_DIR
    cases: list[HTMLFixtureCase] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "input.html").exists():
            cases.extend(load_variants(child, prefix))
        else:
            cases.extend(
                collect_html_cases(child, f"{prefix}{child.name}/"),
            )
    return cases


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Auto-parametrize tests that use html_fixture_case."""
    if "html_fixture_case" not in metafunc.fixturenames:
        return
    cases = collect_html_cases()
    metafunc.parametrize(
        "html_fixture_case",
        cases,
        ids=[c.name for c in cases],
    )
