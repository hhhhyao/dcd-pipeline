#!/usr/bin/env python3
"""Build NASA raw_data JSONL+TAR from page-to-image URL mappings."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import mimetypes
import sys
import tarfile
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_PAGE_IMG_MAP = Path("/root/zhouyiren/data/interleaved/nasa/img_url_raw/page_img_urls.jsonl")
DEFAULT_OUTPUT_DIR = Path("/root/zhouyiren/data/interleaved/nasa/raw_data")
USER_AGENT = (
    "dcd-pipeline-nasa-raw-data-crawler/0.1 "
    "(content HTML and image collection; +https://www.nasa.gov/)"
)

CONTENT_TYPE_EXTENSIONS = {
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/tiff": ".tiff",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class PageImage:
    img_url: str
    source: str


@dataclass(frozen=True)
class PageMapping:
    index: int
    page_url: str
    images: list[PageImage]


@dataclass(frozen=True)
class FetchResult:
    url: str
    ok: bool
    final_url: str
    content: bytes
    content_type: str
    charset: str
    error: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def default_part_name() -> str:
    return f"part{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-00000"


def md5_hex(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.md5(value).hexdigest()


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def iri_to_uri(url: str) -> str:
    """Percent-encode non-ASCII URL components before urllib requests."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    path = quote(parsed.path or "/", safe="/%:@")
    query = quote(parsed.query, safe="=&?/:;+,%")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


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
    accept: str,
    timeout: float,
    retries: int,
    max_bytes: int,
) -> FetchResult:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(
                iri_to_uri(url),
                headers={
                    "Accept": accept,
                    "User-Agent": USER_AGENT,
                },
            )
            with urlopen(request, timeout=timeout) as response:
                content = read_limited(response, max_bytes=max_bytes)
                encoding = response.headers.get("Content-Encoding", "").lower()
                content_type = response.headers.get_content_type() or ""
                charset = response.headers.get_content_charset() or "utf-8"
                final_url = response.geturl()
            if encoding == "gzip":
                content = gzip.decompress(content)
            return FetchResult(
                url=url,
                ok=True,
                final_url=final_url,
                content=content,
                content_type=content_type,
                charset=charset,
            )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(0.8 * (attempt + 1))
    assert last_error is not None
    return FetchResult(
        url=url,
        ok=False,
        final_url=url,
        content=b"",
        content_type="",
        charset="utf-8",
        error=repr(last_error),
    )


def read_page_mappings(path: Path) -> list[PageMapping]:
    mappings: list[PageMapping] = []
    with path.open("r", encoding="utf-8") as handle:
        for fallback_index, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            page_url = row.get("page_url")
            if not isinstance(page_url, str) or not page_url:
                raise ValueError(f"{path}:{fallback_index + 1}: missing page_url")

            images: list[PageImage] = []
            for image_row in row.get("img_urls", []):
                if not isinstance(image_row, dict):
                    continue
                img_url = image_row.get("img_url")
                if not isinstance(img_url, str) or not img_url:
                    continue
                source = image_row.get("source")
                images.append(PageImage(img_url=img_url, source=str(source or "")))

            index = row.get("index")
            mappings.append(
                PageMapping(
                    index=int(index) if isinstance(index, int) else fallback_index,
                    page_url=page_url,
                    images=list(OrderedDict((img.img_url, img) for img in images).values()),
                )
            )
    return sorted(mappings, key=lambda item: item.index)


def fetch_pages(
    mappings: list[PageMapping],
    *,
    workers: int,
    timeout: float,
    retries: int,
    max_html_bytes: int,
) -> dict[str, FetchResult]:
    results: dict[str, FetchResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                fetch_url,
                mapping.page_url,
                accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                timeout=timeout,
                retries=retries,
                max_bytes=max_html_bytes,
            ): mapping.page_url
            for mapping in mappings
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            page_url = futures[future]
            results[page_url] = future.result()
            if completed == 1 or completed % 50 == 0 or completed == len(futures):
                print(f"fetched pages {completed}/{len(futures)}", file=sys.stderr)
    return results


def resolve_image_url_for_page(page_url: str, img_url: str, page_final_url: str) -> str:
    """Return the canonical image URL to fetch for a NASA page."""
    _ = (page_url, page_final_url)
    return img_url


def unique_image_urls(
    mappings: list[PageMapping],
    *,
    page_results: dict[str, FetchResult],
) -> list[str]:
    urls: OrderedDict[str, None] = OrderedDict()
    for mapping in mappings:
        page_result = page_results.get(mapping.page_url)
        page_final_url = page_result.final_url if page_result else mapping.page_url
        for image in mapping.images:
            urls.setdefault(resolve_image_url_for_page(mapping.page_url, image.img_url, page_final_url), None)
    return list(urls)


def fetch_images(
    image_urls: list[str],
    *,
    workers: int,
    timeout: float,
    retries: int,
    max_image_bytes: int,
) -> dict[str, FetchResult]:
    results: dict[str, FetchResult] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                fetch_url,
                img_url,
                accept="image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.1",
                timeout=timeout,
                retries=retries,
                max_bytes=max_image_bytes,
            ): img_url
            for img_url in image_urls
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            img_url = futures[future]
            results[img_url] = future.result()
            if completed == 1 or completed % 200 == 0 or completed == len(futures):
                print(f"fetched images {completed}/{len(futures)}", file=sys.stderr)
    return results


def extension_from_image(result: FetchResult) -> str:
    content_type = result.content_type.lower().split(";", 1)[0]
    if content_type in CONTENT_TYPE_EXTENSIONS:
        return CONTENT_TYPE_EXTENSIONS[content_type]

    parsed = urlparse(result.final_url or result.url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in set(CONTENT_TYPE_EXTENSIONS.values()):
        return suffix
    guessed = mimetypes.guess_extension(content_type)
    return guessed or ".bin"


def image_size(image_bytes: bytes, content_type: str) -> tuple[int | None, int | None]:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n") and len(image_bytes) >= 24:
        return int.from_bytes(image_bytes[16:20], "big"), int.from_bytes(image_bytes[20:24], "big")
    if image_bytes.startswith((b"GIF87a", b"GIF89a")) and len(image_bytes) >= 10:
        return int.from_bytes(image_bytes[6:8], "little"), int.from_bytes(image_bytes[8:10], "little")
    if image_bytes.startswith(b"\xff\xd8"):
        pos = 2
        while pos + 9 < len(image_bytes):
            if image_bytes[pos] != 0xFF:
                pos += 1
                continue
            marker = image_bytes[pos + 1]
            pos += 2
            if marker in {0xD8, 0xD9}:
                continue
            if pos + 2 > len(image_bytes):
                break
            segment_length = int.from_bytes(image_bytes[pos : pos + 2], "big")
            if segment_length < 2 or pos + segment_length > len(image_bytes):
                break
            if marker in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                height = int.from_bytes(image_bytes[pos + 3 : pos + 5], "big")
                width = int.from_bytes(image_bytes[pos + 5 : pos + 7], "big")
                return width, height
            pos += segment_length
    if content_type.lower().startswith("image/webp") and image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        chunk = image_bytes[12:16]
        if chunk == b"VP8X" and len(image_bytes) >= 30:
            width = int.from_bytes(image_bytes[24:27], "little") + 1
            height = int.from_bytes(image_bytes[27:30], "little") + 1
            return width, height
    return None, None


def write_tar_member(tar: tarfile.TarFile, name: str, content: bytes, *, mtime: int) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(content)
    info.mtime = mtime
    tar.addfile(info, io.BytesIO(content))


def build_outputs(
    mappings: list[PageMapping],
    *,
    page_results: dict[str, FetchResult],
    image_results: dict[str, FetchResult],
    output_dir: Path,
    part_name: str,
    metadata: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / f"{part_name}.jsonl"
    tar_path = output_dir / f"{part_name}.tar"
    metadata_path = output_dir / "metadata.json"
    tar_mtime = int(time.time())

    page_rows = 0
    image_occurrences = 0
    downloaded_occurrences = 0
    image_failures: OrderedDict[str, str] = OrderedDict()

    with jsonl_path.open("w", encoding="utf-8") as jsonl_handle, tarfile.open(tar_path, "w") as tar:
        for mapping in mappings:
            page_result = page_results.get(mapping.page_url)
            html_text = ""
            final_url = mapping.page_url
            page_error = ""
            if page_result and page_result.ok:
                html_text = page_result.content.decode(page_result.charset or "utf-8", errors="replace")
                final_url = page_result.final_url
            elif page_result:
                page_error = page_result.error

            page_hash = md5_hex(mapping.page_url)
            images: list[dict[str, Any]] = []
            image_errors: list[dict[str, str]] = []

            for image_index, image in enumerate(mapping.images):
                image_occurrences += 1
                resolved_img_url = resolve_image_url_for_page(mapping.page_url, image.img_url, final_url)
                image_result = image_results.get(resolved_img_url)
                if not image_result or not image_result.ok:
                    error = image_result.error if image_result else "not fetched"
                    image_failures.setdefault(resolved_img_url, error)
                    image_errors.append(
                        {
                            "image_url": image.img_url,
                            "resolved_image_url": resolved_img_url,
                            "error": error,
                            "source": image.source,
                        }
                    )
                    continue
                if not image_result.content_type.lower().startswith("image/"):
                    error = f"non-image content type: {image_result.content_type}"
                    image_failures.setdefault(resolved_img_url, error)
                    image_errors.append(
                        {
                            "image_url": image.img_url,
                            "resolved_image_url": resolved_img_url,
                            "error": error,
                            "source": image.source,
                        }
                    )
                    continue

                image_bytes = image_result.content
                image_md5 = md5_hex(image_bytes)
                ext = extension_from_image(image_result)
                tar_member = f"{page_hash}/{image_md5}_{image_index}{ext}"
                image_file = f"{part_name}/{tar_member}"
                write_tar_member(tar, tar_member, image_bytes, mtime=tar_mtime)

                width, height = image_size(image_bytes, image_result.content_type)
                image_meta: dict[str, Any] = {
                    "caption_text": "",
                    "caption_title": "",
                    "content_type": image_result.content_type,
                    "download_bytes": len(image_bytes),
                    "final_image_url": image_result.final_url,
                    "image_file": image_file,
                    "image_md5": image_md5,
                    "image_sha256": sha256_hex(image_bytes),
                    "image_url": image_result.final_url,
                    "image_url_ori": image.img_url,
                    "source": image.source,
                }
                if resolved_img_url != image.img_url:
                    image_meta["resolved_image_url"] = resolved_img_url
                if width is not None:
                    image_meta["width"] = width
                if height is not None:
                    image_meta["height"] = height
                images.append(image_meta)
                downloaded_occurrences += 1

            if not mapping.images:
                image_status = "empty"
            elif len(images) == len(mapping.images):
                image_status = "complete"
            elif images:
                image_status = "partial"
            else:
                image_status = "failed"

            row: dict[str, Any] = {
                "crawl_time": str(int(time.time())),
                "crawl_type": "PC",
                "final_url": final_url,
                "html": html_text,
                "image_status": image_status,
                "images": images,
                "page_type": ["NASA_PAGE"],
                "part": part_name,
                "url": mapping.page_url,
            }
            if page_error:
                row["page_error"] = page_error
            if image_errors:
                row["image_errors"] = image_errors
            jsonl_handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            page_rows += 1

    metadata.update(
        {
            "jsonl_path": str(jsonl_path),
            "tar_path": str(tar_path),
            "metadata_path": str(metadata_path),
            "page_rows": page_rows,
            "image_occurrences": image_occurrences,
            "downloaded_image_occurrences": downloaded_occurrences,
            "failed_unique_image_count": len(image_failures),
            "image_failures_sample": [
                {"image_url": url, "error": error}
                for url, error in list(image_failures.items())[:50]
            ],
        }
    )
    with metadata_path.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build NASA raw_data JSONL+TAR from preprocess0-1 page image mappings.",
    )
    parser.add_argument("--page-img-map", type=Path, default=DEFAULT_PAGE_IMG_MAP)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--part-name", default=default_part_name())
    parser.add_argument("--page-limit", type=int, default=None)
    parser.add_argument("--page-workers", type=int, default=4)
    parser.add_argument("--image-workers", type=int, default=12)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--max-html-bytes", type=int, default=10_000_000)
    parser.add_argument("--max-image-bytes", type=int, default=25_000_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.page_img_map.exists():
        print(f"Page-image mapping file does not exist: {args.page_img_map}", file=sys.stderr)
        return 2
    if args.page_workers <= 0 or args.image_workers <= 0:
        print("--page-workers and --image-workers must be positive", file=sys.stderr)
        return 2
    if args.retries < 0:
        print("--retries must be non-negative", file=sys.stderr)
        return 2

    mappings = read_page_mappings(args.page_img_map)
    if args.page_limit is not None:
        if args.page_limit <= 0:
            print("--page-limit must be positive when provided", file=sys.stderr)
            return 2
        mappings = mappings[: args.page_limit]
    if not mappings:
        print(f"No page mappings found in {args.page_img_map}", file=sys.stderr)
        return 2

    started_at = utc_now()
    print(f"loaded {len(mappings)} page mappings", file=sys.stderr)
    page_results = fetch_pages(
        mappings,
        workers=args.page_workers,
        timeout=args.timeout,
        retries=args.retries,
        max_html_bytes=args.max_html_bytes,
    )
    image_urls = unique_image_urls(mappings, page_results=page_results)
    print(f"loaded {len(image_urls)} unique image URLs", file=sys.stderr)
    image_results = fetch_images(
        image_urls,
        workers=args.image_workers,
        timeout=args.timeout,
        retries=args.retries,
        max_image_bytes=args.max_image_bytes,
    )
    finished_at = utc_now()

    ok_pages = sum(1 for result in page_results.values() if result.ok)
    ok_images = sum(1 for result in image_results.values() if result.ok)
    metadata: dict[str, Any] = {
        "started_at": started_at,
        "finished_at": finished_at,
        "page_img_map": str(args.page_img_map),
        "output_dir": str(args.output_dir),
        "part_name": args.part_name,
        "requested_page_count": len(mappings),
        "unique_img_url_count": len(image_urls),
        "ok_page_count": ok_pages,
        "failed_page_count": len(mappings) - ok_pages,
        "ok_unique_image_count": ok_images,
        "failed_unique_image_count_before_write": len(image_urls) - ok_images,
        "page_workers": args.page_workers,
        "image_workers": args.image_workers,
        "timeout": args.timeout,
        "retries": args.retries,
        "max_html_bytes": args.max_html_bytes,
        "max_image_bytes": args.max_image_bytes,
    }
    build_outputs(
        mappings,
        page_results=page_results,
        image_results=image_results,
        output_dir=args.output_dir,
        part_name=args.part_name,
        metadata=metadata,
    )

    print(
        f"Built raw_data under {args.output_dir}; pages={len(mappings)}; "
        f"ok_pages={ok_pages}; unique_images={len(image_urls)}; ok_unique_images={ok_images}"
    )
    return 0 if ok_pages else 1


if __name__ == "__main__":
    raise SystemExit(main())
