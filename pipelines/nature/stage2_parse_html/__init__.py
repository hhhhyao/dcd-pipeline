"""Parse raw HTML into cleaned markdown or simplified HTML."""

from __future__ import annotations

import json
import re
import signal
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from lxml.html import HtmlElement, document_fromstring

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


@dataclass
class ExtractResult:
    """Cleaned text output from the HTML extraction pipeline."""

    markdown: str
    simple_html: str
    meta: dict[str, str]
    images: list[dict[str, str]]


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


def run_extract_pipeline(
    source_html: str,
    url: str = "",
    *,
    remove_ref: bool = False,
) -> ExtractResult:
    """Run the full extraction pipeline."""
    tree = document_fromstring(source_html)
    meta = PageMeta(tree, url=url, remove_ref=remove_ref)

    cleaner = make_cleaner(meta)
    meta, content = cleaner.clean(tree)

    html_output = make_html_converter(meta).convert(deepcopy(content))
    images = extract_image_captions(content)
    apply_image_ref_alt_text(content)
    md_output = make_md_converter(meta).convert(content)

    return ExtractResult(
        markdown=md_output,
        simple_html=html_output,
        meta=meta.to_dict(),
        images=images,
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
    timeout: int = 30,
) -> ExtractResult:
    """Run extraction with a SIGALRM timeout that kills stuck parsing."""
    old_handler = signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(timeout)
    try:
        return run_extract_pipeline(
            source_html, url, remove_ref=remove_ref,
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

        try:
            result = run_with_timeout(
                source_html, url,
                remove_ref=remove_ref, timeout=timeout,
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
            output = result.markdown

        data_out.append(restore_local_paths(output, url))

        info["format"] = out_format
        info_out.append(json.dumps(info))
        _set_progress(ctx, i + 1)

    text_out = {**text_batch, "data": data_out, "info": info_out}
    if not nested:
        return text_out  # type: ignore[return-value]
    return {
        "text": text_out,
        "image": _flatten_linked_image_batch(batch.get("image")),
    }
