from __future__ import annotations

import json
from types import SimpleNamespace

import process_parse_table as pipe


def _ctx(config: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        config=config or {},
        set_progress=lambda *args, **kwargs: None,
        report_error=lambda *args, **kwargs: None,
    )


def test_table_to_markdown_converts_basic_table() -> None:
    html = (
        "<table>"
        "<thead><tr><th>Name</th><th>Value</th></tr></thead>"
        "<tbody><tr><td>Alpha</td><td>1</td></tr></tbody>"
        "</table>"
    )

    result = pipe.html_tables_to_markdown(html)

    assert result.markdown == (
        "| Name | Value |\n"
        "| --- | --- |\n"
        "| Alpha | 1 |"
    )
    assert result.table_count == 1
    assert result.tables_converted == 1


def test_colspan_header_is_expanded_and_collapsed() -> None:
    html = (
        "<table><thead>"
        '<tr><th></th><th colspan="3">EGFR overexpression</th></tr>'
        "<tr><th>Her-2 overexpression</th><th>No</th><th>Yes</th><th>Total</th></tr>"
        "</thead><tbody>"
        "<tr><td>No</td><td>17</td><td>18</td><td>35</td></tr>"
        "</tbody></table>"
    )

    result = pipe.html_tables_to_markdown(html)

    assert result.markdown.splitlines()[0] == (
        "| Her-2 overexpression | EGFR overexpression / No | "
        "EGFR overexpression / Yes | EGFR overexpression / Total |"
    )
    assert "| No | 17 | 18 | 35 |" in result.markdown


def test_nature_table_container_is_selected() -> None:
    html = (
        "<html><head><title>Table 1 Demo | Nature</title></head><body>"
        '<div class="c-article-table-container">'
        '<table class="data last-table">'
        "<thead><tr><th><p><b>Characteristic</b></p></th>"
        "<th><p><b>Number</b></p></th></tr></thead>"
        "<tbody><tr><td><p>Total</p></td><td><p>59</p></td></tr></tbody>"
        "</table>"
        "</div>"
        "</body></html>"
    )

    result = pipe.html_tables_to_markdown(html)

    assert result.title == "Table 1 Demo"
    assert result.markdown == (
        "| Characteristic | Number |\n"
        "| --- | --- |\n"
        "| Total | 59 |"
    )


def test_map_accepts_raw_html_column_and_writes_info() -> None:
    batch = {
        "id": ["table-1"],
        "html": [
            "<table><tr><th>A</th><th>B</th></tr>"
            "<tr><td>x</td><td>y</td></tr></table>",
        ],
        "html_title": ["Table 1 Demo | Nature"],
        "table_number": [1],
    }

    out = pipe.map(batch, _ctx())
    info = json.loads(out["info"][0])

    assert out["id"] == ["table-1"]
    assert "| A | B |" in out["data"][0]
    assert info["format"] == "md"
    assert info["table_parse_status"] == "ok"
    assert info["tables_converted"] == 1
    assert info["table_title"] == "Table 1 Demo"
    assert info["table_number"] == 1


def test_map_marks_missing_table_without_raising() -> None:
    batch = {
        "id": ["empty"],
        "data": ["<html><body><p>No table here</p></body></html>"],
        "info": ["{}"],
    }

    out = pipe.map(batch, _ctx())
    info = json.loads(out["info"][0])

    assert out["data"] == [""]
    assert info["table_parse_status"] == "no_table"
    assert info["table_count"] == 0
