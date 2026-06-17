#!/usr/bin/env python3
"""Collect standalone NASA content URLs from public sitemap files."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


DEFAULT_SITEMAP = "https://www.nasa.gov/sitemap.xml"
DEFAULT_OUTPUT_DIR = Path("/root/zhouyiren/data/interleaved/nasa/url_raw")
USER_AGENT = (
    "dcd-pipeline-nasa-url-crawler/0.1 "
    "(standalone content URL collection; +https://www.nasa.gov/)"
)

ALLOWED_HOSTS = {"www.nasa.gov", "nasa.gov"}
SKIP_PATH_PREFIXES = (
    "/author/",
    "/category/",
    "/feed/",
    "/search/",
    "/tag/",
    "/wp-",
    "/wp-content/",
    "/wp-json/",
)
SKIP_PATH_CONTAINS = (
    "/page/",
    "/xmlrpc.php",
)
SKIP_EXTENSIONS = (
    ".css",
    ".gif",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".pdf",
    ".png",
    ".svg",
    ".webp",
    ".xml",
    ".zip",
)
SITEMAP_KIND_PRIORITY = (
    ("wp-sitemap-posts-post-", 0),
    ("wp-sitemap-news-posts-post-", 1),
    ("wp-sitemap-posts-press-release-", 2),
    ("wp-sitemap-news-posts-press-release-", 3),
    ("wp-sitemap-posts-image-article-", 4),
    ("wp-sitemap-news-posts-image-article-", 5),
    ("wp-sitemap-posts-feature-", 6),
    ("wp-sitemap-news-posts-feature-", 7),
    ("wp-sitemap-posts-nasa-blog-", 8),
    ("wp-sitemap-news-posts-nasa-blog-", 9),
    ("wp-sitemap-posts-mission-", 10),
    ("wp-sitemap-news-posts-mission-", 11),
    ("wp-sitemap-posts-reference-", 12),
    ("wp-sitemap-news-posts-reference-", 13),
    ("wp-sitemap-posts-gallery-", 14),
    ("wp-sitemap-history-posts-gallery-", 15),
    ("wp-sitemap-posts-topic-", 16),
    ("wp-sitemap-posts-stem-content-", 17),
    ("wp-sitemap-posts-person-", 18),
    ("wp-sitemap-posts-location-", 19),
    ("wp-sitemap-posts-event-", 20),
    ("wp-sitemap-posts-podcast-", 21),
    ("wp-sitemap-posts-page-", 30),
    ("wp-sitemap-news-posts-page-", 31),
    ("wp-sitemap-history-posts-page-", 32),
    ("wp-sitemap-history-posts-post-", 33),
)
SITEMAP_SHARD_RE = re.compile(r"-(\d+)\.xml(?:\.gz)?$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def fetch_url(url: str, *, timeout: float, retries: int = 2) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(
                url,
                headers={
                    "Accept": "application/xml,text/xml,text/html;q=0.8,*/*;q=0.1",
                    "User-Agent": USER_AGENT,
                },
            )
            with urlopen(request, timeout=timeout) as response:
                data = response.read()
                encoding = response.headers.get("Content-Encoding", "").lower()
            if url.endswith(".gz") or encoding == "gzip":
                return gzip.decompress(data)
            return data
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    assert last_error is not None
    raise last_error


def parse_sitemap(xml_bytes: bytes) -> tuple[str, list[str]]:
    root = ET.fromstring(xml_bytes)
    root_kind = local_name(root.tag)
    locations: list[str] = []
    for elem in root.iter():
        if local_name(elem.tag) == "loc" and elem.text:
            locations.append(elem.text.strip())
    return root_kind, locations


def normalize_nasa_url(raw_url: str) -> str | None:
    parsed = urlparse(raw_url.strip())
    if not parsed.scheme:
        return None
    host = parsed.netloc.lower()
    if host not in ALLOWED_HOSTS:
        return None
    path = parsed.path or "/"
    if path.lower().endswith(SKIP_EXTENSIONS):
        return None
    if path != "/":
        path = f"{path.rstrip('/')}/"
    return urlunparse(("https", "www.nasa.gov", path, "", "", ""))


def is_standalone_content_url(url: str) -> bool:
    parsed = urlparse(url)
    path = parsed.path or "/"
    lower_path = path.lower()
    if parsed.netloc.lower() != "www.nasa.gov":
        return False
    if path == "/" or not path.endswith("/"):
        return False
    if lower_path.endswith(SKIP_EXTENSIONS):
        return False
    if any(lower_path.startswith(prefix) for prefix in SKIP_PATH_PREFIXES):
        return False
    if any(part in lower_path for part in SKIP_PATH_CONTAINS):
        return False
    return any(ch.isalpha() for ch in path.strip("/"))


def is_content_sitemap(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "www.nasa.gov":
        return False
    path = parsed.path.lower()
    if not path.endswith((".xml", ".xml.gz")):
        return False
    if not path.startswith("/wp-sitemap-"):
        return False
    if "taxonomies" in path or "statics" in path:
        return False
    return True


def sitemap_priority(url: str) -> tuple[int, int, str]:
    lower = url.lower()
    shard = 0
    match = SITEMAP_SHARD_RE.search(lower)
    if match:
        shard = int(match.group(1))
    for token, priority in SITEMAP_KIND_PRIORITY:
        if token in lower:
            return (priority, shard, lower)
    return (90, shard, lower)


def iter_unique(values: Iterable[str]) -> Iterable[str]:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        yield value


def collect_urls(
    *,
    sitemap_url: str,
    limit: int,
    max_sitemaps: int,
    timeout: float,
    sleep_seconds: float,
) -> tuple[OrderedDict[str, str], list[dict[str, object]]]:
    queue: deque[str] = deque([sitemap_url])
    seen_sitemaps: set[str] = set()
    urls: OrderedDict[str, str] = OrderedDict()
    sitemap_log: list[dict[str, object]] = []

    while queue and len(urls) < limit and len(seen_sitemaps) < max_sitemaps:
        current = queue.popleft()
        if current in seen_sitemaps:
            continue
        seen_sitemaps.add(current)

        entry: dict[str, object] = {"url": current, "started_at": utc_now()}
        try:
            xml_bytes = fetch_url(current, timeout=timeout)
            root_kind, locations = parse_sitemap(xml_bytes)
        except Exception as exc:  # noqa: BLE001 - log and continue across public sitemap shards.
            entry.update({"ok": False, "error": repr(exc), "finished_at": utc_now()})
            sitemap_log.append(entry)
            continue

        if root_kind == "sitemapindex":
            child_sitemaps = [
                loc
                for loc in iter_unique(locations)
                if is_content_sitemap(loc)
            ]
            for child in sorted(child_sitemaps, key=sitemap_priority):
                if child not in seen_sitemaps:
                    queue.append(child)
        elif root_kind == "urlset":
            for raw_url in locations:
                normalized = normalize_nasa_url(raw_url)
                if normalized and is_standalone_content_url(normalized):
                    urls.setdefault(normalized, current)
                    if len(urls) >= limit:
                        break

        entry.update(
            {
                "ok": True,
                "root_kind": root_kind,
                "locations": len(locations),
                "collected_total": len(urls),
                "finished_at": utc_now(),
            }
        )
        sitemap_log.append(entry)

        if sleep_seconds > 0 and queue and len(urls) < limit:
            time.sleep(sleep_seconds)

    return urls, sitemap_log


def write_outputs(
    urls: OrderedDict[str, str],
    *,
    output_dir: Path,
    metadata: dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    txt_path = output_dir / "urls.txt"
    jsonl_path = output_dir / "urls.jsonl"
    metadata_path = output_dir / "metadata.json"

    with txt_path.open("w", encoding="utf-8") as handle:
        for url in urls:
            handle.write(f"{url}\n")

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for url, source_sitemap in urls.items():
            row = {
                "id": hashlib.sha256(url.encode("utf-8")).hexdigest(),
                "url": url,
                "source_sitemap": source_sitemap,
                "site": "www.nasa.gov",
                "page_type": "nasa_page",
                "created_at": metadata["finished_at"],
            }
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect standalone www.nasa.gov content page URLs from sitemaps.",
    )
    parser.add_argument("--sitemap-url", default=DEFAULT_SITEMAP)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--max-sitemaps", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--sleep", type=float, default=0.1)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.limit <= 0:
        print("--limit must be positive", file=sys.stderr)
        return 2

    started_at = utc_now()
    urls, sitemap_log = collect_urls(
        sitemap_url=args.sitemap_url,
        limit=args.limit,
        max_sitemaps=args.max_sitemaps,
        timeout=args.timeout,
        sleep_seconds=args.sleep,
    )
    finished_at = utc_now()

    metadata: dict[str, object] = {
        "started_at": started_at,
        "finished_at": finished_at,
        "sitemap_url": args.sitemap_url,
        "output_dir": str(args.output_dir),
        "requested_limit": args.limit,
        "collected_url_count": len(urls),
        "max_sitemaps": args.max_sitemaps,
        "sitemaps_fetched": len(sitemap_log),
        "sitemap_log": sitemap_log,
        "filter": "standalone https://www.nasa.gov/ content pages from WordPress post/page sitemaps",
    }

    write_outputs(urls, output_dir=args.output_dir, metadata=metadata)

    if len(urls) < args.limit:
        print(
            f"Only collected {len(urls)} URLs; requested at least {args.limit}. "
            f"Increase --max-sitemaps or inspect {args.output_dir / 'metadata.json'}.",
            file=sys.stderr,
        )
        return 1

    print(f"Collected {len(urls)} NASA content URLs into {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
