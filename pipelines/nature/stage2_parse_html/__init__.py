"""Parse raw HTML into cleaned markdown or simplified HTML."""

from __future__ import annotations

import json
import re
import signal
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from lxml.html import Element, HtmlElement, document_fromstring

from dcd_cli.pipe import Batch, MultimodalBatch, PipeContext

try:
    from .html_tool import (
        PageMeta,
        make_cleaner,
        make_html_converter,
        make_md_converter,
    )
except ImportError:  # pragma: no cover - local test/import fallback
    from html_tool import (  # type: ignore
        PageMeta,
        make_cleaner,
        make_html_converter,
        make_md_converter,
    )

LOCAL_MEDIA_PREFIXES = ("images/", "media/")
LOCAL_IMAGE_SRC_RE = re.compile(r"^(?:\./)?images/([^?#]+)")
IMAGE_REF_ATTRS = ("_image_ref_id", "image_ref_id", "data-image-ref-id")
TABLE_HREF_RE = re.compile(r"/articles/[^/?#]+/tables/(\d+)", re.I)


@dataclass
class ExtractResult:
    """Cleaned text output from the HTML extraction pipeline."""

    markdown: str
    simple_html: str
    meta: dict[str, str]
    images: list[dict[str, str]]
    tables_injected: int = 0


def _compact_text(text: str) -> str:
    return " ".join((text or "").split())


def extract_image_captions(tree: HtmlElement) -> list[dict[str, str]]:
    """Extract ``figure > img`` caption metadata from an HTML tree."""
    images: list[dict[str, str]] = []
    for figure in tree.xpath(".//figure"):
        captions = [
            _compact_text(caption.text_content())
            for caption in figure.xpath(".//figcaption")
        ]
        caption_text = next((caption for caption in captions if caption), "")
        if not caption_text:
            continue
        for img in figure.xpath(".//img"):
            src = (img.get("src") or "").strip()
            if not src:
                continue
            images.append({
                "url": src,
                "alt": img.get("alt") or "",
                "caption": caption_text,
            })
    return images


def _has_class(el: HtmlElement, class_name: str) -> bool:
    return class_name in (el.get("class") or "").split()


def _remove_element(el: HtmlElement) -> None:
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def _table_number_from_href(href: str) -> int | None:
    match = TABLE_HREF_RE.search(href or "")
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _table_number_from_record(record: dict[str, Any]) -> int | None:
    raw_number = record.get("table_number")
    if raw_number not in (None, ""):
        try:
            return int(raw_number)
        except (TypeError, ValueError):
            pass
    for key in ("table_url", "final_url"):
        value = record.get(key)
        if isinstance(value, str):
            number = _table_number_from_href(value)
            if number is not None:
                return number
    return None


def _title_from_table_record(record: dict[str, Any], table_number: int) -> str:
    html_text = record.get("html")
    if isinstance(html_text, str) and html_text:
        try:
            tree = document_fromstring(html_text)
            for xpath in (
                f'.//*[@id="table-{table_number}-title"]',
                './/*[contains(concat(" ", normalize-space(@class), " "), " c-article-satellite-title ")]',
            ):
                matches = tree.xpath(xpath)
                if matches:
                    title = _compact_text(matches[0].text_content())
                    if title:
                        return title
        except Exception:
            pass
    for key in ("html_title", "link_text"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return _compact_text(value.split("|", 1)[0])
    return f"Table {table_number}"


def _extract_table_element(record: dict[str, Any]) -> HtmlElement | None:
    html_text = record.get("html")
    if not isinstance(html_text, str) or not html_text.strip():
        return None
    try:
        tree = document_fromstring(html_text)
    except Exception:
        return None
    matches = tree.xpath(
        './/*[contains(concat(" ", normalize-space(@class), " "), '
        '" c-article-table-container ")]//table',
    )
    if not matches:
        matches = tree.xpath(".//table")
    if not matches:
        return None
    table = deepcopy(matches[0])
    table.tail = None
    return table


def _coerce_table_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _table_number_from_container(container: HtmlElement) -> int | None:
    container_id = container.get("id") or ""
    match = re.fullmatch(r"table-(\d+)", container_id)
    if match is not None:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    for link in container.xpath('.//a[contains(@href, "/tables/")]'):
        number = _table_number_from_href(link.get("href") or "")
        if number is not None:
            return number
    for caption in container.xpath('.//*[@id]'):
        match = re.fullmatch(r"Tab(\d+)", caption.get("id") or "")
        if match is not None:
            try:
                return int(match.group(1))
            except ValueError:
                pass
    return None


def _remove_full_size_table_links(container: HtmlElement) -> None:
    for link in list(container.xpath('.//a[contains(@href, "/tables/")]')):
        parent = link.getparent()
        if (
            parent is not None
            and parent is not container
            and (_has_class(parent, "u-text-right") or _has_class(parent, "c-article__button"))
        ):
            _remove_element(parent)
        else:
            _remove_element(link)


def _append_table_to_container(container: HtmlElement, table: HtmlElement) -> None:
    _remove_full_size_table_links(container)
    target = container
    figures = container.xpath(".//figure")
    if figures:
        target = figures[0]
    if not target.xpath(".//table"):
        target.append(table)


def inject_table_records(content: HtmlElement, table_records: list[dict[str, Any]]) -> int:
    """Insert fetched Nature table HTML into article table placeholders.

    Nature article pages often keep only a table caption plus a
    ``/tables/<n>`` link in the main article HTML.  Stage0 can preserve the
    fetched table pages in ``info.tables``; this function extracts the real
    ``<table>`` element from those pages and inserts it back at the matching
    article placeholder before HTML-to-Markdown conversion.
    """
    prepared: dict[int, tuple[str, HtmlElement]] = {}
    for record in table_records:
        number = _table_number_from_record(record)
        if number is None:
            continue
        table = _extract_table_element(record)
        if table is None:
            continue
        prepared[number] = (_title_from_table_record(record, number), table)
    if not prepared:
        return 0

    injected: set[int] = set()
    containers = content.xpath(
        './/*[contains(concat(" ", normalize-space(@class), " "), " c-article-table ")]',
    )
    for container in containers:
        number = _table_number_from_container(container)
        if number is None or number in injected or number not in prepared:
            continue
        _title, table = prepared[number]
        _append_table_to_container(container, deepcopy(table))
        injected.add(number)

    for number, (title, table) in prepared.items():
        if number in injected:
            continue
        wrapper = Element("div")
        heading = Element("h3")
        heading.text = title
        wrapper.append(heading)
        wrapper.append(deepcopy(table))
        content.append(wrapper)
        injected.add(number)

    return len(injected)


def run_extract_pipeline(
    source_html: str,
    url: str = "",
    *,
    remove_ref: bool = False,
    table_records: list[dict[str, Any]] | None = None,
) -> ExtractResult:
    """Run the full extraction pipeline."""
    tree = document_fromstring(source_html)
    meta = PageMeta(tree, url=url, remove_ref=remove_ref)

    cleaner = make_cleaner(meta)
    meta, content = cleaner.clean(tree)
    tables_injected = inject_table_records(content, table_records or [])

    html_output = make_html_converter(meta).convert(deepcopy(content))
    images = extract_image_captions(content)
    apply_image_ref_alt_text(content)
    md_output = make_md_converter(meta).convert(content)

    return ExtractResult(
        markdown=md_output,
        simple_html=html_output,
        meta=meta.to_dict(),
        images=images,
        tables_injected=tables_injected,
    )


def _local_image_id_from_src(src: str) -> str | None:
    src = (src or "").strip()
    match = LOCAL_IMAGE_SRC_RE.match(src)
    if not match:
        return None
    image_id = match.group(1).strip("/")
    return image_id or None


def apply_image_ref_alt_text(tree: HtmlElement) -> None:
    """Use Stage1 ``image_ref_id`` as Markdown image alt text.

    Stage1 rewrites matched images to ``src="images/<image_id>"`` and keeps
    the article-local reference id in ``_image_ref_id``.  Setting ``alt`` here
    makes markdown conversion emit ``![<image_ref_id>](images/<image_id>)``:
    the brackets preserve the image reference id, while the URL remains the
    stable image id used by downstream Lance image APIs.
    """
    for img in tree.iter("img"):
        src = img.get("src") or ""
        if _local_image_id_from_src(src) is None:
            continue
        image_ref_id = ""
        for attr in IMAGE_REF_ATTRS:
            value = img.get(attr)
            if value:
                image_ref_id = value
                break
        if image_ref_id:
            img.set("alt", image_ref_id)


class AlarmTimeoutError(Exception):
    """Raised by SIGALRM handler when parse exceeds the time limit."""


def alarm_handler(signum: int, frame: Any) -> None:  # noqa: D103
    raise AlarmTimeoutError


def run_with_timeout(
    source_html: str,
    url: str,
    *,
    remove_ref: bool = False,
    table_records: list[dict[str, Any]] | None = None,
    timeout: int = 30,
) -> ExtractResult:
    """Run extraction with a SIGALRM timeout that kills stuck parsing."""
    old_handler = signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(timeout)
    try:
        return run_extract_pipeline(
            source_html, url, remove_ref=remove_ref, table_records=table_records,
        )
    except AlarmTimeoutError:
        raise TimeoutError from None
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def restore_local_paths(text: str, url: str) -> str:
    """Undo URL resolution for local dataset media paths.

    ``resolve_relative_urls`` turns ``images/id`` into
    ``https://example.com/page/images/id``.  This reverses that
    for known local prefixes so the output keeps relative paths.
    """
    if not url:
        return text
    for prefix in LOCAL_MEDIA_PREFIXES:
        resolved = urljoin(url, prefix)
        if resolved != prefix:
            text = text.replace(resolved, prefix)
    return text


FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n+)?")
DOWNLOAD_PDF_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:\[[ \t]*)?Download PDF(?:[ \t]*\]\([^)]+\))?[ \t]*$",
)
FULL_SIZE_IMAGE_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:\[[ \t]*)?Full size image(?:[ \t]*\]\([^)]+\))?[ \t]*$",
)
FULL_SIZE_TABLE_LINE_RE = re.compile(
    r"(?im)^[ \t]*(?:\[[ \t]*)?Full size table(?:[ \t]*\]\([^)]+\))?[ \t]*$",
)
SIMILAR_CONTENT_HEADING_RE = re.compile(
    r"(?im)^#{2,6}[ \t]+Similar content being viewed by others[ \t#]*$",
)
MAIN_HEADING_RE = re.compile(r"(?m)^#{1,2}[ \t]+\S")
REFERENCES_HEADING_RE = re.compile(r"(?im)^#{1,6}[ \t]+References[ \t#]*$")


def _split_front_matter(markdown: str) -> tuple[str, str]:
    match = FRONT_MATTER_RE.match(markdown)
    if match is None:
        return "", markdown
    return markdown[:match.end()], markdown[match.end():]


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n") + ("\n" if text.endswith("\n") else "")


def _remove_standalone_lines(text: str) -> str:
    text = DOWNLOAD_PDF_LINE_RE.sub("", text)
    text = FULL_SIZE_IMAGE_LINE_RE.sub("", text)
    text = FULL_SIZE_TABLE_LINE_RE.sub("", text)
    return text


def _remove_similar_content_blocks(text: str) -> str:
    while True:
        match = SIMILAR_CONTENT_HEADING_RE.search(text)
        if match is None:
            return text
        next_main = MAIN_HEADING_RE.search(text, match.end())
        end = next_main.start() if next_main is not None else len(text)
        text = text[:match.start()] + text[end:]


def _first_h1_index(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        if re.match(r"^#[ \t]+", line):
            return idx
    return None


def _next_heading_index(lines: list[str], start: int, title: str) -> int | None:
    title_lower = title.casefold()
    for idx in range(start, len(lines)):
        stripped = lines[idx].strip().rstrip("#").strip()
        match = re.match(r"^#{1,6}[ \t]+(.+)$", stripped)
        if match and match.group(1).strip().casefold() == title_lower:
            return idx
    return None


def _remove_post_title_boilerplate(text: str) -> str:
    lines = text.split("\n")
    h1_idx = _first_h1_index(lines)
    if h1_idx is None:
        return text

    abstract_idx = _next_heading_index(lines, h1_idx + 1, "Abstract")
    if abstract_idx is not None:
        kept = lines[:h1_idx + 1] + [""] + lines[abstract_idx:]
        return "\n".join(kept)

    # Fallback for unusual pages without an Abstract heading: remove the
    # immediate author bullet list and common citation/metrics blocks only.
    out = lines[:h1_idx + 1]
    idx = h1_idx + 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    while idx < len(lines) and lines[idx].lstrip().startswith("- "):
        idx += 1
        while idx < len(lines) and not lines[idx].strip():
            idx += 1

    skip_subjects = False
    while idx < len(lines):
        stripped = lines[idx].strip()
        lower = stripped.casefold()
        if re.match(r"^#{1,6}[ \t]+subjects[ \t#]*$", stripped, re.IGNORECASE):
            skip_subjects = True
            idx += 1
            continue
        if skip_subjects:
            if re.match(r"^#{1,6}[ \t]+", stripped):
                skip_subjects = False
            elif not stripped or stripped.startswith("- "):
                idx += 1
                continue
            else:
                skip_subjects = False
        if (
            "cite this article" in lower
            or "metrics details" in lower
            or re.search(r"\b(accesses|citations?|altmetric)\b", lower)
            or ("volume" in lower and "article number" in lower)
        ):
            idx += 1
            continue
        out.append(lines[idx])
        idx += 1
    return "\n".join(out)


def _trim_references(text: str) -> str:
    match = REFERENCES_HEADING_RE.search(text)
    if match is None:
        return text
    return text[:match.start()].rstrip() + "\n"


def postprocess_nature_markdown(markdown: str, *, remove_ref: bool) -> str:
    """Apply Nature article-specific Markdown cleanup rules.

    These rules remove article-page chrome that survives the generic HTML
    cleaner: PDF download links, recommendation blocks, image download
    prompts, author/metrics metadata after the title, and optionally the
    References tail.
    """
    front_matter, body = _split_front_matter(markdown)
    body = _remove_standalone_lines(body)
    body = _remove_similar_content_blocks(body)
    body = _remove_post_title_boilerplate(body)
    if remove_ref:
        body = _trim_references(body)
    body = _collapse_blank_lines(body)
    return front_matter + body


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


def _text_batch_from_input(batch: dict[str, Any]) -> tuple[dict[str, list[Any]], bool]:
    text_batch = batch.get("text")
    if isinstance(text_batch, dict):
        return {str(key): list(value) for key, value in text_batch.items()}, True
    return {str(key): list(value) for key, value in batch.items()}, False


def _values_for_row(column: list[Any], row_idx: int) -> list[Any]:
    if row_idx >= len(column):
        return []
    value = column[row_idx]
    if isinstance(value, list):
        return value
    return [value]


def _label_values_for_row(
    column: list[Any],
    row_idx: int,
    *,
    linked_count: int,
    default: Any,
) -> list[Any]:
    if row_idx >= len(column):
        return [default for _ in range(linked_count)]
    value = column[row_idx]
    if not isinstance(value, list):
        return [value for _ in range(linked_count)]
    if linked_count == 1:
        if value and not all(isinstance(item, str) for item in value):
            return value
        return [value]
    if len(value) == linked_count:
        return value
    return [value for _ in range(linked_count)]


def _value_at(values: list[Any], idx: int, default: Any) -> Any:
    return values[idx] if idx < len(values) else default


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value in (None, ""):
        return []
    return [str(value)]


def _flatten_linked_image_batch(image_batch: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {
        "id": [],
        "image_bytes": [],
        "info": [],
        "data": [],
        "tags": [],
    }
    if not isinstance(image_batch, dict):
        return out

    ids_col = list(image_batch.get("id") or [])
    bytes_col = list(image_batch.get("image_bytes") or [])
    info_col = list(image_batch.get("info") or [])
    data_col = list(image_batch.get("data") or [])
    tags_col = list(image_batch.get("tags") or [])

    for row_idx in range(len(ids_col)):
        ids = _values_for_row(ids_col, row_idx)
        blobs = _values_for_row(bytes_col, row_idx)
        linked_count = len(ids)
        infos = _label_values_for_row(info_col, row_idx, linked_count=linked_count, default={})
        data_values = _label_values_for_row(data_col, row_idx, linked_count=linked_count, default={})
        tag_values = _label_values_for_row(tags_col, row_idx, linked_count=linked_count, default=[])

        for item_idx, item_id in enumerate(ids):
            blob = _value_at(blobs, item_idx, None)
            if not item_id or not isinstance(blob, (bytes, bytearray)) or not blob:
                continue
            out["id"].append(str(item_id))
            out["image_bytes"].append(bytes(blob))
            out["info"].append(_value_at(infos, item_idx, {}))
            out["data"].append(_value_at(data_values, item_idx, {}))
            out["tags"].append(_normalize_tags(_value_at(tag_values, item_idx, [])))

    return out


def map(
    batch: MultimodalBatch, ctx: PipeContext,
) -> MultimodalBatch:
    """Convert source HTML in *data* to cleaned markdown or HTML."""
    config = _ctx_config(ctx)
    remove_ref: bool = config.get("remove_ref", True)
    out_format: str = config.get("out_format", "md")
    timeout: int = int(config.get("timeout", 30))
    text_batch, nested = _text_batch_from_input(batch)

    data_out: list[str] = []
    info_out: list[str] = []
    for i, (item_id, source_html, info_raw) in enumerate(
        zip(text_batch["id"], text_batch["data"], text_batch["info"], strict=True),
    ):
        source_html = source_html or ""
        info_raw = info_raw or "{}"
        info: dict = (
            json.loads(info_raw)
            if isinstance(info_raw, str)
            else info_raw
        )

        if not source_html:
            data_out.append(source_html)
            info_out.append(json.dumps(info))
            _set_progress(ctx, i + 1)
            continue

        url: str = info.get("url", "")
        table_records = _coerce_table_records(info.get("tables"))

        try:
            result = run_with_timeout(
                source_html, url,
                remove_ref=remove_ref, table_records=table_records, timeout=timeout,
            )
        except TimeoutError:
            _report_error(ctx, str(item_id), f"Parse timed out after {timeout}s")
            data_out.append("")
            info_out.append(json.dumps(info))
            _set_progress(ctx, i + 1)
            continue
        except Exception as exc:
            _report_error(ctx, str(item_id), f"Parse failed: {exc}")
            data_out.append("")
            info_out.append(json.dumps(info))
            _set_progress(ctx, i + 1)
            continue

        if out_format == "html":
            output = result.simple_html
        else:
            output = postprocess_nature_markdown(
                result.markdown,
                remove_ref=remove_ref,
            )

        data_out.append(restore_local_paths(output, url))

        info["format"] = out_format
        if table_records:
            info["table_count"] = len(table_records)
            info["tables_injected"] = result.tables_injected
            info.pop("tables", None)
        info_out.append(json.dumps(info))
        _set_progress(ctx, i + 1)

    text_out = {**text_batch, "data": data_out, "info": info_out}
    if not nested:
        return text_out  # type: ignore[return-value]
    return {
        "text": text_out,
        "image": _flatten_linked_image_batch(batch.get("image")),
    }
