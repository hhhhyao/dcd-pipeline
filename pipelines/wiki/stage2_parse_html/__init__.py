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

from dcd_cli.pipe import PipeContext

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
    apply_image_ref_alt_text(content)
    md_output = make_md_converter(meta).convert(content)

    return ExtractResult(
        markdown=md_output,
        simple_html=html_output,
        meta=meta.to_dict(),
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


def map(
    batch: dict[str, list[Any]], ctx: PipeContext,
) -> dict[str, list[Any]]:
    """Convert source HTML in *data* to cleaned markdown or HTML."""
    config = ctx.config or {}
    remove_ref: bool = config.get("remove_ref", False)
    out_format: str = config.get("out_format", "md")
    timeout: int = int(config.get("timeout", 30))

    data_out: list[str] = []
    info_out: list[str] = []
    for i, (item_id, source_html, info_raw) in enumerate(
        zip(batch["id"], batch["data"], batch["info"], strict=True),
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
            ctx.set_progress(i + 1)
            continue

        url: str = info.get("url", "")

        try:
            result = run_with_timeout(
                source_html, url,
                remove_ref=remove_ref, timeout=timeout,
            )
        except TimeoutError:
            ctx.report_error(
                "text", str(item_id),
                f"Parse timed out after {timeout}s",
            )
            data_out.append("")
            info_out.append(json.dumps(info))
            ctx.set_progress(i + 1)
            continue
        except Exception as exc:
            ctx.report_error(
                "text", str(item_id), f"Parse failed: {exc}",
            )
            data_out.append("")
            info_out.append(json.dumps(info))
            ctx.set_progress(i + 1)
            continue

        if out_format == "html":
            output = result.simple_html
        else:
            output = result.markdown

        data_out.append(restore_local_paths(output, url))

        info["format"] = out_format
        info_out.append(json.dumps(info))
        ctx.set_progress(i + 1)

    return {**batch, "data": data_out, "info": info_out}
