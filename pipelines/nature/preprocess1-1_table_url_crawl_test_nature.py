#!/usr/bin/env python3
"""Collect and fetch full-size Nature table HTML pages from raw article JSONL.

Some Nature article pages include table placeholders in the article HTML and a
``Full size table`` link such as ``/articles/<article-id>/tables/1``. The table
body is served on that separate page, so downstream HTML parsing needs those
table pages saved explicitly.

This helper reads raw article rows containing an ``html`` field, extracts only
Nature full-size table page URLs, fetches each unique table URL with a
cookie-aware opener, and writes machine-readable JSONL for later processing.

By default, the output is a single JSONL file beside the input:
``part2026-06-08-00000.jsonl`` -> ``part2026-06-08-00000_table.jsonl``.
Each output row is one fetched table page and includes the fetched HTML.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html as html_lib
import http.cookiejar
import json
import re
import sys
import time
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


DEFAULT_INPUT_JSONL = Path(
    "/root/zhouyiren/data/interleaved/nature/web_eng_20260608_sample/"
    "part2026-06-08-00000_OA/part2026-06-08-00000.jsonl"
)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 "
    "dcd-pipeline-nature-table-crawler/0.1"
)
TABLE_PATH_RE = re.compile(r"^/articles/([^/?#]+)/tables/(\d+)/?$", re.I)
TAG_RE = re.compile(r"<[^>]+>")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


@dataclass(frozen=True)
class Anchor:
    href: str
    attrs: dict[str, str]
    text: str


@dataclass(frozen=True)
class TableURLRecord:
    id: str
    source_jsonl: str
    source_index: int
    article_url: str
    article_final_url: str
    article_id: str
    table_number: int
    table_url: str
    link_text: str
    link_attrs: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchResult:
    url: str
    ok: bool
    status: str
    final_url: str
    content: bytes
    content_type: str
    charset: str
    http_status: int | None = None
    error: str = ""


class AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[Anchor] = []
        self._active_href: str | None = None
        self._active_attrs: dict[str, str] = {}
        self._active_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._active_href is not None:
            return
        if tag != "a":
            return
        attrs_dict = {name.lower(): value for name, value in attrs if value is not None}
        href = attrs_dict.get("href")
        if not href:
            return
        self._active_href = href
        self._active_attrs = attrs_dict
        self._active_text = []

    def handle_endtag(self, tag: str) -> None:
        if self._active_href is None:
            return
        if tag.lower() != "a":
            return
        text = re.sub(r"\s+", " ", "".join(self._active_text)).strip()
        self.anchors.append(
            Anchor(
                href=self._active_href,
                attrs=dict(self._active_attrs),
                text=text,
            )
        )
        self._active_href = None
        self._active_attrs = {}
        self._active_text = []

    def handle_data(self, data: str) -> None:
        if self._active_href is not None:
            self._active_text.append(data)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_hex(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def title_from_html(html: str) -> str:
    match = TITLE_RE.search(html)
    if not match:
        return ""
    text = TAG_RE.sub(" ", match.group(1))
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def is_nature_host(host: str) -> bool:
    host = host.lower()
    return host == "nature.com" or host.endswith(".nature.com")


def normalize_table_url(raw_url: str, *, page_url: str) -> tuple[str, str, int] | None:
    raw_url = html_lib.unescape(raw_url).strip()
    if not raw_url:
        return None
    if raw_url.lower().startswith(("about:", "data:", "javascript:", "mailto:", "#")):
        return None

    absolute_url = urljoin(page_url, raw_url)
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if not is_nature_host(parsed.netloc):
        return None

    path = unquote(parsed.path)
    match = TABLE_PATH_RE.match(path)
    if not match:
        return None

    article_id = match.group(1)
    table_number = int(match.group(2))
    normalized = urlunparse(
        (
            parsed.scheme,
            parsed.netloc.lower(),
            path.rstrip("/"),
            "",
            parsed.query,
            "",
        )
    )
    return normalized, article_id, table_number


def extract_table_urls_from_html(
    html: str,
    *,
    article_url: str,
    article_final_url: str,
    source_jsonl: Path,
    source_index: int,
) -> list[TableURLRecord]:
    parser = AnchorParser()
    parser.feed(html)

    by_url: OrderedDict[str, TableURLRecord] = OrderedDict()
    page_url = article_final_url or article_url
    for anchor in parser.anchors:
        normalized = normalize_table_url(anchor.href, page_url=page_url)
        if normalized is None:
            continue
        table_url, article_id, table_number = normalized
        if table_url in by_url:
            continue
        by_url[table_url] = TableURLRecord(
            id=sha256_hex(table_url),
            source_jsonl=str(source_jsonl),
            source_index=source_index,
            article_url=article_url,
            article_final_url=article_final_url,
            article_id=article_id,
            table_number=table_number,
            table_url=table_url,
            link_text=anchor.text,
            link_attrs=anchor.attrs,
        )
    return list(by_url.values())


def iter_jsonl_rows(jsonl_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{jsonl_path}:{line_number}: invalid JSONL") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{jsonl_path}:{line_number}: expected JSON object")
            rows.append(row)
    return rows


def discover_table_urls(
    jsonl_path: Path,
    *,
    page_limit: int | None,
) -> tuple[list[dict[str, Any]], list[TableURLRecord]]:
    rows = iter_jsonl_rows(jsonl_path)
    if page_limit is not None:
        rows = rows[:page_limit]

    page_records: list[dict[str, Any]] = []
    all_table_records: list[TableURLRecord] = []
    for source_index, row in enumerate(rows):
        article_url = str(row.get("url") or "")
        article_final_url = str(row.get("final_url") or article_url)
        html = str(row.get("html") or "")
        table_records = extract_table_urls_from_html(
            html,
            article_url=article_url,
            article_final_url=article_final_url,
            source_jsonl=jsonl_path,
            source_index=source_index,
        )
        all_table_records.extend(table_records)
        page_records.append(
            {
                "source_jsonl": str(jsonl_path),
                "source_index": source_index,
                "article_url": article_url,
                "article_final_url": article_final_url,
                "article_title": title_from_html(html),
                "table_url_count": len(table_records),
                "table_urls": [
                    {
                        "id": record.id,
                        "table_url": record.table_url,
                        "article_id": record.article_id,
                        "table_number": record.table_number,
                        "link_text": record.link_text,
                    }
                    for record in table_records
                ],
            }
        )
    return page_records, all_table_records


def unique_table_records(records: list[TableURLRecord]) -> list[TableURLRecord]:
    by_url: OrderedDict[str, TableURLRecord] = OrderedDict()
    for record in records:
        by_url.setdefault(record.table_url, record)
    return list(by_url.values())


def read_limited(response: Any, *, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(1024 * 128)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"response exceeded max_bytes={max_bytes}")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_url(
    url: str,
    *,
    timeout: float,
    retries: int,
    max_bytes: int,
) -> FetchResult:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        try:
            request = Request(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.1",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                    "User-Agent": USER_AGENT,
                },
            )
            with opener.open(request, timeout=timeout) as response:
                content = read_limited(response, max_bytes=max_bytes)
                encoding = response.headers.get("Content-Encoding", "").lower()
                content_type = response.headers.get_content_type() or ""
                charset = response.headers.get_content_charset() or "utf-8"
                final_url = response.geturl()
                http_status = getattr(response, "status", None)
            if encoding == "gzip":
                content = gzip.decompress(content)
            return FetchResult(
                url=url,
                ok=True,
                status="ok",
                final_url=final_url,
                content=content,
                content_type=content_type,
                charset=charset,
                http_status=http_status,
            )
        except HTTPError as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
            return FetchResult(
                url=url,
                ok=False,
                status=f"http_{exc.code}",
                final_url=exc.geturl(),
                content=b"",
                content_type=exc.headers.get_content_type() if exc.headers else "",
                charset=exc.headers.get_content_charset() if exc.headers else "utf-8",
                http_status=exc.code,
                error=repr(exc),
            )
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
                continue
    assert last_error is not None
    return FetchResult(
        url=url,
        ok=False,
        status="error",
        final_url=url,
        content=b"",
        content_type="",
        charset="utf-8",
        error=repr(last_error),
    )


def table_html_file(record: TableURLRecord) -> str:
    safe_article_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", record.article_id)
    return f"html/{safe_article_id}_table_{record.table_number}_{record.id[:12]}.html"


def crawl_one_table(
    record: TableURLRecord,
    *,
    timeout: float,
    retries: int,
    max_html_bytes: int,
) -> dict[str, Any]:
    started_at = utc_now()
    result = fetch_url(
        record.table_url,
        timeout=timeout,
        retries=retries,
        max_bytes=max_html_bytes,
    )
    html_text = (
        result.content.decode(result.charset or "utf-8", errors="replace")
        if result.content
        else ""
    )
    table_element_count = len(re.findall(r"<table\b", html_text, re.I))
    article_table_container_count = len(re.findall(r"\bc-article-table\b", html_text, re.I))
    html_sha256 = sha256_hex(result.content) if result.content else ""
    status = result.status
    if result.ok and table_element_count == 0 and article_table_container_count == 0:
        status = "ok_no_table_content"

    return {
        "id": record.id,
        "source_jsonl": record.source_jsonl,
        "source_index": record.source_index,
        "article_url": record.article_url,
        "article_final_url": record.article_final_url,
        "article_id": record.article_id,
        "table_number": record.table_number,
        "table_url": record.table_url,
        "link_text": record.link_text,
        "ok": result.ok,
        "status": status,
        "http_status": result.http_status,
        "final_url": result.final_url,
        "content_type": result.content_type,
        "charset": result.charset,
        "html_bytes": len(result.content),
        "html_sha256": html_sha256,
        "html_title": title_from_html(html_text),
        "table_element_count": table_element_count,
        "article_table_container_count": article_table_container_count,
        "html_file": table_html_file(record) if result.content else "",
        "html": html_text,
        "error": result.error,
        "started_at": started_at,
        "finished_at": utc_now(),
    }


def crawl_table_urls(
    table_records: list[TableURLRecord],
    *,
    workers: int,
    timeout: float,
    retries: int,
    max_html_bytes: int,
    submit_sleep: float,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for record in table_records:
            futures.append(
                executor.submit(
                    crawl_one_table,
                    record,
                    timeout=timeout,
                    retries=retries,
                    max_html_bytes=max_html_bytes,
                )
            )
            if submit_sleep > 0:
                time.sleep(submit_sleep)

        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if completed == 1 or completed % 50 == 0 or completed == len(futures):
                print(
                    f"fetched tables {completed}/{len(table_records)}; "
                    f"latest_status={result['status']}; latest_tables={result['table_element_count']}",
                    file=sys.stderr,
                )
    return sorted(results, key=lambda row: (str(row["article_id"]), int(row["table_number"]), str(row["table_url"])))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_output_summary(
    *,
    page_records: list[dict[str, Any]],
    table_records: list[TableURLRecord],
    table_results: list[dict[str, Any]],
    metadata: dict[str, Any],
    output_jsonl: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    unique_records = unique_table_records(table_records)
    ok_count = sum(1 for row in table_results if row.get("ok"))
    table_element_count = sum(1 for row in table_results if int(row.get("table_element_count") or 0) > 0)
    table_content_count = sum(
        1
        for row in table_results
        if int(row.get("table_element_count") or 0) > 0
        or int(row.get("article_table_container_count") or 0) > 0
    )
    status_counts = Counter(str(row.get("status")) for row in table_results)

    metadata.update(
        {
            "counts": {
                "source_page_rows": len(page_records),
                "pages_with_table_urls": sum(1 for row in page_records if int(row["table_url_count"]) > 0),
                "table_url_occurrences": len(table_records),
                "unique_table_url_count": len(unique_records),
                "fetched_table_url_count": len(table_results),
                "ok_table_fetch_count": ok_count,
                "failed_table_fetch_count": len(table_results) - ok_count,
                "fetched_pages_with_table_element": table_element_count,
                "fetched_pages_with_table_content": table_content_count,
            },
            "status_counts": dict(status_counts.most_common()),
        }
    )
    if output_jsonl is not None:
        metadata["output_jsonl"] = str(output_jsonl)
    if output_dir is not None:
        metadata["output_dir"] = str(output_dir)
    return metadata


def table_url_rows(table_records: list[TableURLRecord]) -> list[dict[str, Any]]:
    table_occurrence_counts = Counter(record.table_url for record in table_records)
    rows: list[dict[str, Any]] = []
    for record in unique_table_records(table_records):
        rows.append(
            {
                "id": record.id,
                "article_url": record.article_url,
                "article_final_url": record.article_final_url,
                "article_id": record.article_id,
                "table_number": record.table_number,
                "table_url": record.table_url,
                "link_text": record.link_text,
                "occurrence_count": table_occurrence_counts[record.table_url],
            }
        )
    return rows


def write_single_jsonl_output(
    *,
    output_jsonl: Path,
    table_records: list[TableURLRecord],
    table_results: list[dict[str, Any]],
    inline_html: bool,
) -> None:
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    occurrence_counts = Counter(record.table_url for record in table_records)

    rows: list[dict[str, Any]]
    if table_results:
        rows = []
        for row in table_results:
            out_row = dict(row)
            out_row["occurrence_count"] = occurrence_counts.get(str(row.get("table_url")), 1)
            out_row.pop("html_file", None)
            if not inline_html:
                out_row.pop("html", None)
            rows.append(out_row)
    else:
        rows = table_url_rows(table_records)

    write_jsonl(output_jsonl, rows)


def write_directory_outputs(
    *,
    output_dir: Path,
    page_records: list[dict[str, Any]],
    table_records: list[TableURLRecord],
    table_results: list[dict[str, Any]],
    metadata: dict[str, Any],
    inline_html: bool,
    write_html_files: bool,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_dir = output_dir / "html"
    if write_html_files:
        html_dir.mkdir(parents=True, exist_ok=True)

    serialized_table_results: list[dict[str, Any]] = []
    for row in table_results:
        out_row = dict(row)
        html_text = str(out_row.get("html") or "")
        html_file = str(out_row.get("html_file") or "")
        if write_html_files and html_text and html_file:
            (output_dir / html_file).write_text(html_text, encoding="utf-8")
        if not inline_html:
            out_row.pop("html", None)
        serialized_table_results.append(out_row)

    table_urls_txt = output_dir / "table_urls.txt"
    table_urls_jsonl = output_dir / "table_urls.jsonl"
    page_table_urls_jsonl = output_dir / "page_table_urls.jsonl"
    table_html_jsonl = output_dir / "table_html.jsonl"
    metadata_json = output_dir / "metadata.json"

    rows = table_url_rows(table_records)
    with table_urls_txt.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(f"{row['table_url']}\n")
    write_jsonl(table_urls_jsonl, rows)
    write_jsonl(page_table_urls_jsonl, page_records)
    write_jsonl(table_html_jsonl, serialized_table_results)

    metadata = build_output_summary(
        page_records=page_records,
        table_records=table_records,
        table_results=table_results,
        metadata=metadata,
        output_dir=output_dir,
    )
    metadata["output_files"] = {
        "table_urls_txt": str(table_urls_txt),
        "table_urls_jsonl": str(table_urls_jsonl),
        "page_table_urls_jsonl": str(page_table_urls_jsonl),
        "table_html_jsonl": str(table_html_jsonl),
        "metadata_json": str(metadata_json),
        "html_dir": str(html_dir) if write_html_files else None,
    }
    metadata_json.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metadata


def default_output_dir(input_jsonl: Path) -> Path:
    return input_jsonl.parent / f"{input_jsonl.stem}_table_html"


def default_output_jsonl(input_jsonl: Path) -> Path:
    return input_jsonl.parent / f"{input_jsonl.stem}_table.jsonl"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract Nature /articles/<id>/tables/<n> links from raw article JSONL "
            "and fetch the full-size table HTML pages."
        )
    )
    parser.add_argument(
        "input_jsonl",
        nargs="?",
        type=Path,
        default=DEFAULT_INPUT_JSONL,
        help="Input raw article JSONL with an html field.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Optional legacy directory output. If omitted, writes a single "
            "<input-stem>_table.jsonl beside the input."
        ),
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=None,
        help="Single JSONL output path. Defaults to <input-stem>_table.jsonl beside the input.",
    )
    parser.add_argument("--page-limit", type=int, default=None)
    parser.add_argument("--table-limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--submit-sleep", type=float, default=0.02)
    parser.add_argument("--max-html-bytes", type=int, default=10_000_000)
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Only extract table URLs and skip downloading table pages.",
    )
    parser.add_argument(
        "--no-inline-html",
        action="store_true",
        help="Do not include fetched HTML in the JSONL output.",
    )
    parser.add_argument(
        "--no-html-files",
        action="store_true",
        help="Do not write standalone html/*.html files.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    input_jsonl = args.input_jsonl.expanduser()
    if not input_jsonl.exists():
        print(f"Input JSONL does not exist: {input_jsonl}", file=sys.stderr)
        return 2
    if args.workers <= 0:
        print("--workers must be positive", file=sys.stderr)
        return 2
    if args.retries < 0:
        print("--retries must be non-negative", file=sys.stderr)
        return 2
    if args.page_limit is not None and args.page_limit <= 0:
        print("--page-limit must be positive when provided", file=sys.stderr)
        return 2
    if args.table_limit is not None and args.table_limit <= 0:
        print("--table-limit must be positive when provided", file=sys.stderr)
        return 2
    if args.output_dir is not None and args.output_jsonl is not None:
        print("--output-dir and --output-jsonl cannot be used together", file=sys.stderr)
        return 2

    started_at = utc_now()
    page_records, all_table_records = discover_table_urls(input_jsonl, page_limit=args.page_limit)
    unique_records = unique_table_records(all_table_records)
    if args.table_limit is not None:
        unique_records = unique_records[: args.table_limit]

    print(
        f"discovered source_pages={len(page_records)}; "
        f"table_occurrences={len(all_table_records)}; unique_table_urls={len(unique_records)}",
        file=sys.stderr,
    )

    table_results: list[dict[str, Any]] = []
    if not args.no_fetch and unique_records:
        table_results = crawl_table_urls(
            unique_records,
            workers=args.workers,
            timeout=args.timeout,
            retries=args.retries,
            max_html_bytes=args.max_html_bytes,
            submit_sleep=args.submit_sleep,
        )

    metadata: dict[str, Any] = {
        "created_at": utc_now(),
        "started_at": started_at,
        "finished_at": utc_now(),
        "input_jsonl": str(input_jsonl),
        "page_limit": args.page_limit,
        "table_limit": args.table_limit,
        "workers": args.workers,
        "timeout": args.timeout,
        "retries": args.retries,
        "max_html_bytes": args.max_html_bytes,
        "fetched": not args.no_fetch,
        "inline_html": not args.no_inline_html,
        "write_html_files": bool(args.output_dir and not args.no_html_files),
    }

    if args.output_dir is not None:
        metadata = write_directory_outputs(
            output_dir=args.output_dir.expanduser(),
            page_records=page_records,
            table_records=all_table_records,
            table_results=table_results,
            metadata=metadata,
            inline_html=not args.no_inline_html,
            write_html_files=not args.no_html_files,
        )
    else:
        output_jsonl = (
            args.output_jsonl.expanduser()
            if args.output_jsonl is not None
            else default_output_jsonl(input_jsonl)
        )
        write_single_jsonl_output(
            output_jsonl=output_jsonl,
            table_records=all_table_records,
            table_results=table_results,
            inline_html=not args.no_inline_html,
        )
        metadata = build_output_summary(
            page_records=page_records,
            table_records=all_table_records,
            table_results=table_results,
            metadata=metadata,
            output_jsonl=output_jsonl,
        )

    print(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True))
    if args.no_fetch:
        return 0
    return 0 if not unique_records or metadata["counts"]["ok_table_fetch_count"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
