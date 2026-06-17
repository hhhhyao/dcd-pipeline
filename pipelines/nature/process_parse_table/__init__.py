"""Convert HTML table pages into markdown tables."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from lxml.html import HtmlElement, document_fromstring, fromstring

try:
    from dcd_cli.pipe import Batch, MultimodalBatch, PipeContext
except ImportError:  # pragma: no cover - local unit-test fallback
    Batch = dict[str, list[Any]]  # type: ignore[misc,assignment]
    MultimodalBatch = dict[str, Any]  # type: ignore[misc,assignment]
    PipeContext = Any  # type: ignore[misc,assignment]


NATURE_TABLE_CONTAINER_XPATH = (
    './/*[contains(concat(" ", normalize-space(@class), " "), '
    '" c-article-table-container ")]//table'
)
TITLE_XPATHS = (
    './/*[contains(concat(" ", normalize-space(@class), " "), '
    '" c-article-satellite-title ")]',
    './/*[contains(concat(" ", normalize-space(@class), " "), '
    '" c-article-section__title ")]',
    ".//h1",
)
META_COLUMNS_EXCLUDED_FROM_INFO = {"id", "data", "html", "info", "tags"}
TABLE_INDEX_ALL = -1


@dataclass
class MarkdownTable:
    """Markdown conversion result for one HTML table."""

    markdown: str
    rows: int
    columns: int


@dataclass
class ParseResult:
    """Result of converting one HTML document."""

    markdown: str
    table_count: int
    tables_converted: int
    row_counts: list[int]
    column_counts: list[int]
    title: str = ""


def _compact_text(text: str) -> str:
    return " ".join((text or "").split())


def _parse_html(source_html: str) -> HtmlElement:
    try:
        return document_fromstring(source_html)
    except Exception:
        return fromstring(source_html)


def _first_ancestor_table(el: HtmlElement) -> HtmlElement | None:
    parent = el.getparent()
    while parent is not None:
        if parent.tag == "table":
            return parent
        parent = parent.getparent()
    return None


def _is_row_owned_by_table(row: HtmlElement, table: HtmlElement) -> bool:
    parent = row.getparent()
    while parent is not None:
        if parent.tag == "table":
            return parent is table
        parent = parent.getparent()
    return False


def _direct_rows(table: HtmlElement) -> list[HtmlElement]:
    return [
        row for row in table.xpath(".//tr")
        if isinstance(row, HtmlElement) and _is_row_owned_by_table(row, table)
    ]


def _find_tables(root: HtmlElement) -> list[HtmlElement]:
    tables: list[HtmlElement] = []
    if root.tag == "table":
        tables.append(root)

    for table in root.xpath(NATURE_TABLE_CONTAINER_XPATH):
        if (
            isinstance(table, HtmlElement)
            and _first_ancestor_table(table) is None
            and table not in tables
        ):
            tables.append(table)

    if not tables:
        for table in root.xpath(".//table"):
            if (
                isinstance(table, HtmlElement)
                and _first_ancestor_table(table) is None
                and table not in tables
            ):
                tables.append(table)
    return tables


def _parse_positive_int(value: Any, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _cell_text(cell: HtmlElement) -> str:
    cell = deepcopy(cell)
    for br in cell.xpath(".//br"):
        br.tail = "\n" + (br.tail or "")
    return _compact_text(cell.text_content())


def _span_fill_value(text: str, span_fill: str) -> str:
    return text if span_fill == "repeat" else ""


def _expanded_rows(
    table: HtmlElement,
    *,
    span_fill: str,
) -> tuple[list[list[str]], list[bool]]:
    rows: list[list[str]] = []
    header_flags: list[bool] = []
    rowspans: dict[int, tuple[int, str]] = {}

    for row in _direct_rows(table):
        cells = [
            cell for cell in row.xpath("./th|./td")
            if isinstance(cell, HtmlElement)
        ]
        section = row.getparent().tag if row.getparent() is not None else ""
        is_header = section == "thead" or bool(cells and all(cell.tag == "th" for cell in cells))

        expanded: list[str] = []
        col_idx = 0

        def consume_pending() -> bool:
            nonlocal col_idx
            if col_idx not in rowspans:
                return False
            remaining, text = rowspans[col_idx]
            expanded.append(text)
            if remaining <= 1:
                del rowspans[col_idx]
            else:
                rowspans[col_idx] = (remaining - 1, text)
            col_idx += 1
            return True

        for cell in cells:
            while consume_pending():
                pass

            text = _cell_text(cell)
            colspan = _parse_positive_int(cell.get("colspan"))
            rowspan = _parse_positive_int(cell.get("rowspan"))

            for offset in range(colspan):
                display_text = text if offset == 0 else _span_fill_value(text, span_fill)
                expanded.append(display_text)
                if rowspan > 1:
                    rowspans[col_idx + offset] = (
                        rowspan - 1,
                        _span_fill_value(text, span_fill),
                    )
            col_idx += colspan

        while rowspans and col_idx <= max(rowspans):
            if not consume_pending():
                expanded.append("")
                col_idx += 1

        rows.append(expanded)
        header_flags.append(is_header)

    width = max((len(row) for row in rows), default=0)
    for row in rows:
        row.extend("" for _ in range(width - len(row)))
    return rows, header_flags


def _leading_header_count(header_flags: list[bool]) -> int:
    count = 0
    for is_header in header_flags:
        if not is_header:
            break
        count += 1
    return count


def _collapse_header_rows(header_rows: list[list[str]], width: int) -> list[str]:
    header: list[str] = []
    for col_idx in range(width):
        values: list[str] = []
        seen: set[str] = set()
        for row in header_rows:
            value = row[col_idx].strip() if col_idx < len(row) else ""
            if value and value not in seen:
                values.append(value)
                seen.add(value)
        header.append(" / ".join(values))
    return header


def _escape_markdown_cell(text: str) -> str:
    text = (text or "").replace("\\", "\\\\").replace("|", "\\|")
    return text.replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>").strip()


def _format_markdown_row(cells: list[str]) -> str:
    return "| " + " | ".join(_escape_markdown_cell(cell) for cell in cells) + " |"


def table_to_markdown(
    table: HtmlElement,
    *,
    span_fill: str = "repeat",
    collapse_headers: bool = True,
) -> MarkdownTable:
    """Convert one ``<table>`` element to a markdown table."""
    rows, header_flags = _expanded_rows(table, span_fill=span_fill)
    if not rows:
        return MarkdownTable(markdown="", rows=0, columns=0)

    width = max((len(row) for row in rows), default=0)
    if width <= 0:
        return MarkdownTable(markdown="", rows=0, columns=0)

    header_count = _leading_header_count(header_flags)
    if header_count <= 0:
        header_count = 1
    header_rows = rows[:header_count]
    body_rows = rows[header_count:]

    if collapse_headers and header_rows:
        header = _collapse_header_rows(header_rows, width)
    else:
        header = header_rows[0] if header_rows else ["" for _ in range(width)]
        body_rows = rows[1:]

    lines = [
        _format_markdown_row(header),
        _format_markdown_row(["---" for _ in range(width)]),
    ]
    lines.extend(_format_markdown_row(row) for row in body_rows)
    return MarkdownTable(
        markdown="\n".join(lines),
        rows=len(rows),
        columns=width,
    )


def _title_from_html(root: HtmlElement) -> str:
    for xpath in TITLE_XPATHS:
        matches = root.xpath(xpath)
        for match in matches:
            if isinstance(match, HtmlElement):
                title = _compact_text(match.text_content())
                if title:
                    return title
    title_el = root.find(".//title")
    if title_el is not None:
        title = _compact_text(title_el.text_content()).split("|", 1)[0].strip()
        if title:
            return title
    return ""


def _title_from_info(info: dict[str, Any], root: HtmlElement) -> str:
    for key in ("table_title", "html_title", "title"):
        value = info.get(key)
        if isinstance(value, str) and value.strip():
            return _compact_text(value.split("|", 1)[0])
    return _title_from_html(root)


def _select_tables(tables: list[HtmlElement], table_index: int) -> list[HtmlElement]:
    if table_index == TABLE_INDEX_ALL:
        return tables
    if table_index < 0 or table_index >= len(tables):
        return []
    return [tables[table_index]]


def html_tables_to_markdown(
    source_html: str,
    *,
    info: dict[str, Any] | None = None,
    table_index: int = TABLE_INDEX_ALL,
    include_title: bool = False,
    title_heading_level: int = 3,
    span_fill: str = "repeat",
    collapse_headers: bool = True,
) -> ParseResult:
    """Extract HTML table elements and convert them to markdown."""
    source_html = source_html or ""
    if not source_html.strip():
        return ParseResult("", 0, 0, [], [])

    root = _parse_html(source_html)
    tables = _find_tables(root)
    selected = _select_tables(tables, table_index)
    title = _title_from_info(info or {}, root)

    md_parts: list[str] = []
    row_counts: list[int] = []
    column_counts: list[int] = []
    if include_title and title:
        level = min(6, max(1, int(title_heading_level)))
        md_parts.append(f"{'#' * level} {title}")

    for table in selected:
        converted = table_to_markdown(
            table,
            span_fill=span_fill,
            collapse_headers=collapse_headers,
        )
        if not converted.markdown:
            continue
        md_parts.append(converted.markdown)
        row_counts.append(converted.rows)
        column_counts.append(converted.columns)

    return ParseResult(
        markdown="\n\n".join(md_parts).strip(),
        table_count=len(tables),
        tables_converted=len(row_counts),
        row_counts=row_counts,
        column_counts=column_counts,
        title=title,
    )


def _ctx_config(ctx: PipeContext) -> dict[str, Any]:
    config = getattr(ctx, "config", None)
    if config is None:
        inputs = getattr(ctx, "inputs", None)
        config = getattr(inputs, "config", None) if inputs is not None else None
    return config if isinstance(config, dict) else {}


def _set_progress(ctx: PipeContext, completed: int) -> None:
    reporter = getattr(ctx, "reporter", None)
    set_progress = getattr(reporter, "set_progress", None)
    if callable(set_progress):
        set_progress(completed, 0, "")
        return
    set_progress = getattr(ctx, "set_progress", None)
    if callable(set_progress):
        set_progress(completed)


def _report_error(ctx: PipeContext, item_id: str, message: str) -> None:
    reporter = getattr(ctx, "reporter", None)
    report_error = getattr(reporter, "report_error", None)
    if callable(report_error):
        report_error("text", item_id, message)
        return
    report_error = getattr(ctx, "report_error", None)
    if callable(report_error):
        report_error("text", item_id, message)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [] if value is None else [value]


def _text_batch_from_input(batch: dict[str, Any]) -> tuple[dict[str, list[Any]], bool]:
    text_batch = batch.get("text")
    nested = isinstance(text_batch, dict)
    source = text_batch if nested else batch
    if not isinstance(source, dict):
        return {"id": [], "data": [], "info": [], "tags": []}, nested

    out = {str(key): _as_list(value) for key, value in source.items()}
    if "data" not in out and "html" in out:
        out["data"] = list(out["html"])
    row_count = len(out.get("data", []))
    if "id" not in out:
        out["id"] = [str(i) for i in range(row_count)]
    if "info" not in out:
        out["info"] = ["{}" for _ in range(row_count)]
    if "tags" not in out:
        out["tags"] = [[] for _ in range(row_count)]
    return out, nested


def _parse_info(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _copy_scalar_metadata(
    info: dict[str, Any],
    text_batch: dict[str, list[Any]],
    row_idx: int,
) -> None:
    for key, values in text_batch.items():
        if key in META_COLUMNS_EXCLUDED_FROM_INFO or row_idx >= len(values):
            continue
        value = values[row_idx]
        if isinstance(value, (str, int, float, bool)) or value is None:
            info.setdefault(key, value)


def _config_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _config_int(config: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError):
        return default


def _normalize_span_fill(value: Any) -> str:
    value = str(value or "repeat").strip().lower()
    return value if value in {"repeat", "blank"} else "repeat"


def map(batch: MultimodalBatch, ctx: PipeContext) -> Batch:
    """Convert each input HTML table page into markdown table text."""
    config = _ctx_config(ctx)
    table_index = _config_int(config, "table_index", TABLE_INDEX_ALL)
    include_title = _config_bool(config, "include_title", False)
    title_heading_level = _config_int(config, "title_heading_level", 3)
    span_fill = _normalize_span_fill(config.get("span_fill", "repeat"))
    collapse_headers = _config_bool(config, "collapse_headers", True)

    text_batch, _nested = _text_batch_from_input(batch)
    row_count = len(text_batch.get("data", []))
    data_out: list[str] = []
    info_out: list[str] = []

    for i in range(row_count):
        item_id = str(text_batch.get("id", [""])[i])
        source_html = str(text_batch["data"][i] or "")
        info = _parse_info(text_batch.get("info", ["{}"])[i])
        _copy_scalar_metadata(info, text_batch, i)

        try:
            result = html_tables_to_markdown(
                source_html,
                info=info,
                table_index=table_index,
                include_title=include_title,
                title_heading_level=title_heading_level,
                span_fill=span_fill,
                collapse_headers=collapse_headers,
            )
        except Exception as exc:
            _report_error(ctx, item_id, f"Table parse failed: {exc}")
            data_out.append("")
            info["format"] = "md"
            info["table_parse_status"] = "error"
            info["table_parse_error"] = str(exc)
            info_out.append(json.dumps(info, ensure_ascii=False))
            _set_progress(ctx, i + 1)
            continue

        data_out.append(result.markdown)
        info["format"] = "md"
        info["table_parse_status"] = "ok" if result.tables_converted else "no_table"
        info["table_count"] = result.table_count
        info["tables_converted"] = result.tables_converted
        info["table_row_counts"] = result.row_counts
        info["table_column_counts"] = result.column_counts
        if result.title:
            info["table_title"] = result.title
        info.pop("table_parse_error", None)
        info_out.append(json.dumps(info, ensure_ascii=False))
        _set_progress(ctx, i + 1)

    output: Batch = {
        "id": list(text_batch.get("id", []))[:row_count],
        "data": data_out,
        "info": info_out,
        "tags": list(text_batch.get("tags", [[] for _ in range(row_count)]))[:row_count],
    }
    return output
