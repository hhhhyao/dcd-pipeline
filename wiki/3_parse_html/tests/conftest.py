"""Conftest for parse_html_repo pipe tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@dataclass
class HTMLFixtureCase:
    """A test case with separate files for each field.

    Layout::

        case_name/
          input.json       # non-content fields: id, url, ...
          input.html       # the ``data`` field
          expected.json    # non-content fields: id, ...
          expected.md      # the expected ``data`` field
    """

    name: str
    input_item: dict[str, Any] = field(default_factory=dict)
    expected_item: dict[str, Any] = field(default_factory=dict)


def load_case(case_dir: Path) -> HTMLFixtureCase:
    """Load a single fixture case from *case_dir*."""
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

    expected_md = (case_dir / "expected.md").read_text(encoding="utf-8")
    expected_item = {**expected_meta, "data": expected_md}
    expected_item.setdefault("id", input_item["id"])

    return HTMLFixtureCase(
        name=case_dir.name,
        input_item=input_item,
        expected_item=expected_item,
    )


def collect_html_cases() -> list[HTMLFixtureCase]:
    """Discover fixture cases under the fixtures directory."""
    cases: list[HTMLFixtureCase] = []
    for child in sorted(FIXTURES_DIR.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "input.html").exists():
            continue
        if not (child / "expected.md").exists():
            continue
        cases.append(load_case(child))
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
