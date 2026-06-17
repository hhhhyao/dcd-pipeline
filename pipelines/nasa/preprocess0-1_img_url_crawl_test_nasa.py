#!/usr/bin/env python3
"""Collect image URLs from NASA article pages listed by preprocess0-0."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_INPUT_URLS = Path("/root/zhouyiren/data/interleaved/nasa/url_raw/urls.txt")
DEFAULT_OUTPUT_DIR = Path("/root/zhouyiren/data/interleaved/nasa/img_url_raw")
USER_AGENT = (
    "dcd-pipeline-nasa-img-url-crawler/0.1 "
    "(content image URL collection; +https://www.nasa.gov/)"
)

IMAGE_EXT_RE = re.compile(r"\.(?:avif|bmp|gif|jpe?g|png|svg|tiff?|webp)(?:$|[?#])", re.I)
ABSOLUTE_IMAGE_URL_RE = re.compile(
    r"https?:\\?/\\?/[^\\s\"'<>)}]+?\.(?:avif|bmp|gif|jpe?g|png|svg|tiff?|webp)"
    r"(?:\?[^\\s\"'<>)}]*)?",
    re.I,
)
MAIN_START_RE = re.compile(
    r"<main\b[^>]*(?:id=[\"']primary[\"']|class=[\"'][^\"']*\bsite-main\b)",
    re.I,
)
ARTICLE_START_RE = re.compile(r"<article\b", re.I)
IMAGE_CONTEXT_TAGS = {"amp-img", "img", "source", "video"}
IMAGE_VALUE_ATTRS = {
    "content",
    "data-background",
    "data-background-image",
    "data-bg",
    "data-hires",
    "data-lazy-src",
    "data-original",
    "data-src",
    "data-srcset",
    "data-zoomable-image",
    "href",
    "imagesrcset",
    "src",
    "srcset",
    "poster",
}
IMAGE_META_NAMES = {
    "og:image",
    "og:image:secure_url",
    "og:image:url",
    "twitter:image",
    "twitter:image:src",
}
ALLOWED_IMAGE_HOSTS = {
    "assets.science.nasa.gov",
    "images-assets.nasa.gov",
    "images.nasa.gov",
    "media.nasa.gov",
    "science.nasa.gov",
    "www.nasa.gov",
}
DYNAMIC_IMAGE_HOSTS = {
    "assets.science.nasa.gov",
    "images-assets.nasa.gov",
}
SKIP_HOST_PARTS = (
    "doubleclick.net",
    "facebook.com",
    "google-analytics.com",
    "googlesyndication.com",
    "googletagmanager.com",
)
SKIP_PATH_PARTS = (
    "/wp-content/plugins/gravityforms/",
    "/wp-content/plugins/nasa-hds-core-setup/assets/favicons/",
    "/wp-content/themes/nasa/assets/",
    "/wp-includes/",
)
SKIP_FILE_RE = re.compile(r"(?:favicon|apple-touch-icon|cropped-nasa-logo|nasa-logo)\.(?:ico|png|svg)$", re.I)


@dataclass(frozen=True)
class Candidate:
    raw_url: str
    source: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_url(url: str, *, timeout: float, retries: int) -> tuple[bytes, str, str]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                    "User-Agent": USER_AGENT,
                },
            )
            with urlopen(request, timeout=timeout) as response:
                data = response.read()
                encoding = response.headers.get("Content-Encoding", "").lower()
                charset = response.headers.get_content_charset() or "utf-8"
                final_url = response.geturl()
            if encoding == "gzip":
                data = gzip.decompress(data)
            return data, charset, final_url
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    assert last_error is not None
    raise last_error


def clean_raw_url(value: str) -> str:
    value = html.unescape(value).strip()
    value = value.replace("\\/", "/")
    value = value.strip("\"' \t\r\n")
    return value


def parse_srcset(value: str) -> Iterable[str]:
    for part in value.split(","):
        part = clean_raw_url(part)
        if not part:
            continue
        yield part.split()[0]


def slice_until_close_tag(page_html: str, *, start: int, tag_name: str) -> str:
    lower_html = page_html.lower()
    end_marker = f"</{tag_name.lower()}>"
    close_index = lower_html.find(end_marker, start)
    if close_index == -1:
        return page_html[start:]
    return page_html[start : close_index + len(end_marker)]


def scoped_image_html(page_html: str) -> str:
    """Return head image metadata plus NASA's main/article content region."""
    pieces: list[str] = []
    lower_html = page_html.lower()
    head_end = lower_html.find("</head>")
    if head_end != -1:
        pieces.append(page_html[: head_end + len("</head>")])

    main_match = MAIN_START_RE.search(page_html)
    if main_match:
        pieces.append(slice_until_close_tag(page_html, start=main_match.start(), tag_name="main"))
        return "\n".join(pieces)

    article_match = ARTICLE_START_RE.search(page_html)
    if article_match:
        pieces.append(slice_until_close_tag(page_html, start=article_match.start(), tag_name="article"))
        return "\n".join(pieces)

    return page_html


def normalize_image_url(raw_url: str, *, page_url: str) -> str | None:
    raw_url = clean_raw_url(raw_url)
    if not raw_url:
        return None
    lowered = raw_url.lower()
    if lowered.startswith(("about:", "blob:", "data:", "javascript:", "mailto:", "#")):
        return None

    absolute_url = urljoin(page_url, raw_url)
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    host = parsed.netloc.lower()
    if host not in ALLOWED_IMAGE_HOSTS:
        return None
    if any(skip_host in host for skip_host in SKIP_HOST_PARTS):
        return None

    path = parsed.path or "/"
    lower_path = path.lower()
    if any(part in lower_path for part in SKIP_PATH_PARTS):
        return None
    if SKIP_FILE_RE.search(lower_path):
        return None

    image_like = bool(IMAGE_EXT_RE.search(path)) or host in DYNAMIC_IMAGE_HOSTS
    if not image_like:
        return None

    path = quote(path, safe="/%:@")
    query = quote(parsed.query, safe="=&?/:;+,%")
    return urlunparse((parsed.scheme, host, path, "", query, ""))


class ImageURLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[Candidate] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {name.lower(): value for name, value in attrs if value}

        if tag in IMAGE_CONTEXT_TAGS:
            for attr_name, attr_value in attrs_dict.items():
                if attr_name not in IMAGE_VALUE_ATTRS:
                    continue
                if attr_name.endswith("srcset") or attr_name == "srcset":
                    for srcset_url in parse_srcset(attr_value):
                        self.candidates.append(Candidate(srcset_url, f"{tag}.{attr_name}"))
                else:
                    self.candidates.append(Candidate(attr_value, f"{tag}.{attr_name}"))
            return

        if tag == "meta":
            meta_name = attrs_dict.get("property") or attrs_dict.get("name")
            content = attrs_dict.get("content")
            if meta_name and content and meta_name.lower() in IMAGE_META_NAMES:
                self.candidates.append(Candidate(content, f"meta.{meta_name.lower()}"))
            return

        if tag == "link":
            rel = attrs_dict.get("rel", "").lower()
            href = attrs_dict.get("href")
            if href and ("image_src" in rel or attrs_dict.get("as", "").lower() == "image"):
                self.candidates.append(Candidate(href, "link.href"))
            imagesrcset = attrs_dict.get("imagesrcset")
            if imagesrcset:
                for srcset_url in parse_srcset(imagesrcset):
                    self.candidates.append(Candidate(srcset_url, "link.imagesrcset"))


def extract_image_records(page_url: str, page_html: str) -> list[dict[str, str]]:
    page_html = scoped_image_html(page_html)
    parser = ImageURLParser()
    parser.feed(page_html)

    candidates = list(parser.candidates)
    for match in ABSOLUTE_IMAGE_URL_RE.finditer(page_html):
        candidates.append(Candidate(match.group(0), "html.regex"))

    by_url: OrderedDict[str, str] = OrderedDict()
    for candidate in candidates:
        normalized = normalize_image_url(candidate.raw_url, page_url=page_url)
        if normalized:
            by_url.setdefault(normalized, candidate.source)

    return [{"img_url": img_url, "source": source} for img_url, source in by_url.items()]


def read_page_urls(input_path: Path) -> list[str]:
    urls: list[str] = []
    with input_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            if input_path.suffix == ".jsonl":
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"{input_path}:{line_number}: invalid JSONL row") from exc
                page_url = row.get("url")
                if not isinstance(page_url, str):
                    raise ValueError(f"{input_path}:{line_number}: missing string field 'url'")
                urls.append(page_url)
            else:
                urls.append(line)
    return list(OrderedDict.fromkeys(urls))


def crawl_one(
    *,
    index: int,
    page_url: str,
    timeout: float,
    retries: int,
) -> dict[str, object]:
    started_at = utc_now()
    try:
        data, charset, final_url = fetch_url(page_url, timeout=timeout, retries=retries)
        page_html = data.decode(charset, errors="replace")
        image_records = extract_image_records(final_url, page_html)
        return {
            "index": index,
            "page_url": page_url,
            "final_url": final_url,
            "ok": True,
            "status": "ok",
            "html_bytes": len(data),
            "img_url_count": len(image_records),
            "img_urls": image_records,
            "started_at": started_at,
            "finished_at": utc_now(),
        }
    except Exception as exc:  # noqa: BLE001 - keep crawling remaining pages.
        return {
            "index": index,
            "page_url": page_url,
            "ok": False,
            "status": "error",
            "error": repr(exc),
            "img_url_count": 0,
            "img_urls": [],
            "started_at": started_at,
            "finished_at": utc_now(),
        }


def crawl_pages(
    page_urls: list[str],
    *,
    workers: int,
    timeout: float,
    retries: int,
    submit_sleep: float,
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = []
        for index, page_url in enumerate(page_urls):
            futures.append(
                executor.submit(
                    crawl_one,
                    index=index,
                    page_url=page_url,
                    timeout=timeout,
                    retries=retries,
                )
            )
            if submit_sleep > 0:
                time.sleep(submit_sleep)

        for completed, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            if completed == 1 or completed % 50 == 0 or completed == len(futures):
                print(
                    f"processed {completed}/{len(futures)} pages; "
                    f"latest_img_url_count={result['img_url_count']}",
                    file=sys.stderr,
                )

    return sorted(results, key=lambda row: int(row["index"]))


def write_outputs(
    results: list[dict[str, object]],
    *,
    output_dir: Path,
    metadata: dict[str, object],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    unique_images: OrderedDict[str, dict[str, str]] = OrderedDict()
    image_occurrences = 0
    for result in results:
        page_url = str(result["page_url"])
        for image_record in result["img_urls"]:
            image_occurrences += 1
            img_url = str(image_record["img_url"])
            unique_images.setdefault(
                img_url,
                {
                    "img_url": img_url,
                    "first_page_url": page_url,
                    "first_source": str(image_record["source"]),
                },
            )

    img_txt_path = output_dir / "img_urls.txt"
    img_jsonl_path = output_dir / "img_urls.jsonl"
    page_jsonl_path = output_dir / "page_img_urls.jsonl"
    metadata_path = output_dir / "metadata.json"

    with img_txt_path.open("w", encoding="utf-8") as handle:
        for img_url in unique_images:
            handle.write(f"{img_url}\n")

    with img_jsonl_path.open("w", encoding="utf-8") as handle:
        for img_url, row in unique_images.items():
            output_row = {
                "id": hashlib.sha256(img_url.encode("utf-8")).hexdigest(),
                "img_url": img_url,
                "first_page_url": row["first_page_url"],
                "first_source": row["first_source"],
                "site": "www.nasa.gov",
                "created_at": metadata["finished_at"],
            }
            handle.write(json.dumps(output_row, ensure_ascii=False, sort_keys=True) + "\n")

    with page_jsonl_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")

    metadata["image_occurrences"] = image_occurrences
    metadata["unique_img_url_count"] = len(unique_images)
    metadata["output_files"] = {
        "img_urls_txt": str(img_txt_path),
        "img_urls_jsonl": str(img_jsonl_path),
        "page_img_urls_jsonl": str(page_jsonl_path),
    }
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect image URLs from NASA article URLs generated by preprocess0-0.",
    )
    parser.add_argument("--input-urls", type=Path, default=DEFAULT_INPUT_URLS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--page-limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--submit-sleep", type=float, default=0.02)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers <= 0:
        print("--workers must be positive", file=sys.stderr)
        return 2
    if args.retries < 0:
        print("--retries must be non-negative", file=sys.stderr)
        return 2
    if not args.input_urls.exists():
        print(f"Input URL list does not exist: {args.input_urls}", file=sys.stderr)
        return 2

    started_at = utc_now()
    page_urls = read_page_urls(args.input_urls)
    if args.page_limit is not None:
        if args.page_limit <= 0:
            print("--page-limit must be positive when provided", file=sys.stderr)
            return 2
        page_urls = page_urls[: args.page_limit]
    if not page_urls:
        print(f"No page URLs found in {args.input_urls}", file=sys.stderr)
        return 2

    results = crawl_pages(
        page_urls,
        workers=args.workers,
        timeout=args.timeout,
        retries=args.retries,
        submit_sleep=args.submit_sleep,
    )
    finished_at = utc_now()

    ok_pages = sum(1 for result in results if result["ok"])
    pages_with_images = sum(1 for result in results if int(result["img_url_count"]) > 0)
    metadata: dict[str, object] = {
        "started_at": started_at,
        "finished_at": finished_at,
        "input_urls": str(args.input_urls),
        "output_dir": str(args.output_dir),
        "requested_page_count": len(page_urls),
        "ok_page_count": ok_pages,
        "failed_page_count": len(results) - ok_pages,
        "pages_with_images": pages_with_images,
        "workers": args.workers,
        "timeout": args.timeout,
        "retries": args.retries,
    }
    write_outputs(results, output_dir=args.output_dir, metadata=metadata)

    if ok_pages == 0:
        print("No pages were fetched successfully.", file=sys.stderr)
        return 1
    print(
        f"Crawled {len(results)} pages; ok={ok_pages}; pages_with_images={pages_with_images}; "
        f"output_dir={args.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
