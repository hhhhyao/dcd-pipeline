#!/usr/bin/env python3
"""Ingest wiki part*.jsonl + part*.tar source into Lance datasets.

Output tables:
- text.lance
- images.lance
- image_labels.lance
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import time
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import lance
import pyarrow as pa
from PIL import Image
try:
    from dcd_cli.pipe import PipeContext
except ImportError:  # pragma: no cover - helper-only imports in unit tests
    PipeContext = Any  # type: ignore[misc,assignment]

log = logging.getLogger(__name__)

DEFAULT_LOG_INTERVAL = 250
DEFAULT_WRITE_STRATEGY = "stream_once"
WRITE_STRATEGIES = {"append_parts", "stream_once"}

TEXT_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("info", pa.string()),
    pa.field("data", pa.large_string()),
    pa.field("tags", pa.list_(pa.string())),
])

IMAGES_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("image_bytes", pa.large_binary()),
    pa.field("sha256", pa.string()),
])

IMAGE_LABELS_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("info", pa.string()),
    pa.field("data", pa.string()),
    pa.field("tags", pa.list_(pa.string())),
])

TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
CANONICAL_RE = re.compile(
    r'<link[^>]*rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
CATEGORY_RE = re.compile(
    r'<a[^>]*href=["\'](?:https?://[^/]*)*/wiki/Category:[^"\']+["\'][^>]*>'
    r"([^<]+)</a>",
    re.IGNORECASE,
)

THUMB_SIZE_RE = re.compile(r"/thumb/(.*)/\d+px-[^/]+$")
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
IMG_SRC_RE = re.compile(r'(\bsrc=["\'])([^"\']+)(["\'])', re.IGNORECASE)
SRCSET_RE = re.compile(r'\s*\bsrcset=["\'][^"\']*["\']', re.IGNORECASE)
WIKIMEDIA_RE = re.compile(r"upload\.wikimedia\.org", re.IGNORECASE)
IMAGE_REF_FIELDS = (
    "caption_text",
    "image_url",
    "image_url_ori",
    "image_file",
    "caption_title",
)
IMAGE_LABEL_INFO_FIELDS = (
    "image_md5",
    "width",
    "height",
    "channel",
    "size_bytes",
)


class LanceStreamWriter:
    """Single-commit Lance writer backed by an Arrow IPC stream."""

    def __init__(
        self,
        dataset_path: Path,
        schema: pa.Schema,
        *,
        temp_dir: Path,
        data_storage_version: str | None = None,
    ) -> None:
        self.dataset_path = dataset_path
        self.schema = schema
        self.data_storage_version = data_storage_version
        self.rows_written = 0
        self.batches_written = 0
        self.write_seconds = 0.0
        self.finalize_seconds = 0.0
        temp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{dataset_path.stem}_",
            suffix=".arrowstream",
            dir=str(temp_dir),
        )
        os.close(fd)
        self._tmp_path: Path | None = Path(tmp_name)
        self._sink: pa.OSFile | None = pa.OSFile(str(self._tmp_path), "wb")
        self._writer: pa.ipc.RecordBatchStreamWriter | None = pa.ipc.new_stream(
            self._sink,
            schema,
        )

    def write_table(self, table: pa.Table) -> None:
        if table.num_rows <= 0:
            return
        if self._writer is None:
            raise RuntimeError("stream writer is already finalized")
        t0 = time.perf_counter()
        if not table.schema.equals(self.schema, check_metadata=False):
            table = table.cast(self.schema)
        for batch in table.to_batches():
            self._writer.write_batch(batch)
            self.batches_written += 1
        self.rows_written += table.num_rows
        self.write_seconds += time.perf_counter() - t0

    def finalize(self, *, create_empty: bool = False) -> None:
        t0 = time.perf_counter()
        try:
            if self._writer is not None:
                self._writer.close()
                self._writer = None
            if self._sink is not None:
                self._sink.close()
                self._sink = None
            if self.rows_written <= 0 and not create_empty:
                return
            if self.rows_written > 0 and self._tmp_path is not None:
                data: Any = pa.ipc.open_stream(str(self._tmp_path))
            else:
                data = pa.Table.from_batches([], schema=self.schema)
            kwargs: dict[str, Any] = {
                "schema": self.schema,
                "mode": "create",
            }
            if self.data_storage_version is not None:
                kwargs["data_storage_version"] = self.data_storage_version
            lance.write_dataset(data, str(self.dataset_path), **kwargs)
        finally:
            if self._tmp_path is not None:
                self._tmp_path.unlink(missing_ok=True)
                self._tmp_path = None
            self.finalize_seconds += time.perf_counter() - t0


def _remove_existing_lance_outputs(*paths: Path) -> None:
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


def _fmt_seconds(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m{s:02d}s"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def normalize_url(url: str) -> str:
    """Strip protocol and normalize Wikimedia thumbnail URLs."""
    url = unquote(re.sub(r"^https?:", "", url).lstrip("/"))
    m = THUMB_SIZE_RE.search(url)
    if m:
        url = url[: m.start()] + "/" + m.group(1)
    return url


def extract_html_meta(html: str) -> dict[str, object]:
    """Extract URL, title and category tags from HTML."""
    result: dict[str, object] = {}
    m = CANONICAL_RE.search(html)
    if m:
        result["url"] = m.group(1)

    m = TITLE_RE.search(html)
    if m:
        raw_title = m.group(1).strip()
        result["title"] = re.sub(r"\s*[-–—]\s*Wikipedia\s*$", "", raw_title)

    skip_prefixes = (
        "Category", "Articles", "Pages", "Webarchive", "CS1", "All ",
        "Use ", "Commons category", "Short description", "Wikipedia",
    )
    tags: list[str] = []
    for cm in CATEGORY_RE.finditer(html):
        cat = cm.group(1).strip()
        if not any(cat.startswith(s) for s in skip_prefixes):
            tags.append(cat.replace("&amp;", "&"))
    result["tags"] = tags
    return result


def build_text_info(
    entry: dict[str, Any],
    *,
    url: str,
    title: str,
    image_ids_for_article: list[str],
    image_refs_for_article: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    """Build text-row info with derived fields plus preserved raw metadata."""
    info: dict[str, object] = {
        "format": "html",
        "url": url,
        "title": title,
        "image_ids": image_ids_for_article,
        "image_refs": image_refs_for_article or {},
    }

    raw_url = entry.get("url")
    if raw_url not in (None, ""):
        info["original_url"] = raw_url

    raw_final_url = entry.get("final_url")
    if raw_final_url not in (None, ""):
        info["final_url"] = raw_final_url

    for key, value in entry.items():
        if key in {"html", "images", "url", "final_url", "page_type"}:
            continue
        if value is None or value == "":
            continue
        info[key] = value

    return info


def build_image_info(
    img_meta: dict[str, Any],
    *,
    image_record: dict[str, Any],
) -> dict[str, object]:
    """Build image-label info from image-stable metadata only."""
    merged = {**img_meta, **image_record}
    merged["size_bytes"] = len(image_record["image_bytes"])
    info: dict[str, object] = {}
    for key in IMAGE_LABEL_INFO_FIELDS:
        value = merged.get(key)
        if value is None or value == "":
            continue
        info[key] = value
    return info


def build_image_ref(img_meta: dict[str, Any]) -> dict[str, object]:
    """Build text-side image reference metadata from article-local fields."""
    return {key: img_meta.get(key, "") for key in IMAGE_REF_FIELDS}


def build_image_ref_id(image_id: str, image_url_ori: str) -> str:
    """Return a stable reference id for one image id and original URL."""
    url_hash = hashlib.sha256(image_url_ori.encode("utf-8")).hexdigest()
    return f"{image_id}_{url_hash}"


def rewrite_html_images(
    html: str,
    img_url_to_id: dict[str, str],
    available_ids: set[str],
) -> str:
    """Rewrite Wikimedia image URLs to local images/{id} when possible."""

    def replacer(m: re.Match[str]) -> str:
        tag = m.group(0)
        src_m = IMG_SRC_RE.search(tag)
        if not src_m:
            return tag
        src = src_m.group(2)
        if not WIKIMEDIA_RE.search(src):
            return tag

        image_id = img_url_to_id.get(normalize_url(src))
        if not image_id or image_id not in available_ids:
            return tag

        tag = SRCSET_RE.sub("", tag)
        return IMG_SRC_RE.sub(rf"\g<1>images/{image_id}\g<3>", tag)

    return IMG_TAG_RE.sub(replacer, html)


def _find_pairs(src_dir: Path) -> list[tuple[Path, Path]]:
    pairs: list[tuple[Path, Path]] = []
    for jf in sorted(src_dir.glob("*.jsonl")):
        tf = src_dir / f"{jf.stem}.tar"
        if tf.is_file():
            pairs.append((jf, tf))
    if not pairs:
        raise FileNotFoundError(f"No matched *.jsonl + *.tar pairs under {src_dir}")
    return pairs


def _count_non_empty_lines(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def _load_part_images(tar_path: Path) -> dict[str, dict[str, object]]:
    """Load one part tar into memory keyed as part/name and plain name."""
    store: dict[str, dict[str, object]] = {}
    part_name = tar_path.stem
    failed = 0
    with tarfile.open(tar_path) as tf:
        for member in tf:
            if not member.isfile():
                continue
            member_name = member.name.removeprefix("images/")
            fobj = tf.extractfile(member)
            if not fobj:
                failed += 1
                continue
            raw = fobj.read()
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    width, height = image.size
                    channel = "".join(image.getbands())
            except Exception:
                failed += 1
                log.warning("Image %s/%s open failed", part_name, member_name)
                continue
            record: dict[str, object] = {
                "image_bytes": raw,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "height": height,
                "width": width,
                "channel": channel,
            }
            store[f"{part_name}/{member_name}"] = record
            store[member_name] = record
    if failed:
        log.warning("%d images failed to read in %s", failed, tar_path)
    return store


def _resolve_image_record(
    image_file: str,
    part_name: str,
    image_store: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    normalized = image_file.removeprefix("images/")
    candidates = (
        image_file,
        normalized,
        f"{part_name}/{normalized}",
    )
    for cid in candidates:
        record = image_store.get(cid)
        if record is not None:
            return record
    return None


def compact_lance(lance_path: Path, table_name: str) -> None:
    log.info("Compacting %s (%s) ...", lance_path, table_name)
    t0 = time.perf_counter()
    ds: Any = lance.dataset(str(lance_path))
    ds.optimize.compact_files()

    existing = {idx["name"] for idx in ds.list_indices()}
    plan: list[tuple[str, str]] = [("id", "BTREE")]
    if "tags" in ds.schema.names:
        plan.append(("tags", "LABEL_LIST"))
    for col, idx_type in plan:
        idx_name = f"{col}_idx"
        if idx_name not in existing:
            log.info("Creating %s index on '%s' ...", idx_type, col)
            ds.create_scalar_index(col, index_type=idx_type)

    ds.optimize.optimize_indices()
    stats = ds.cleanup_old_versions(
        older_than=timedelta(seconds=0),
        delete_unverified=True,
    )
    if stats.bytes_removed:
        log.info(
            "Cleaned up %d old versions, freed %.2f GB",
            stats.old_versions,
            stats.bytes_removed / 1e9,
        )
    log.info("Compact %s done in %s", table_name, _fmt_seconds(time.perf_counter() - t0))


def run_streaming(
    src_dir: Path,
    dst_dir: Path,
    *,
    log_interval: int,
    write_strategy: str = DEFAULT_WRITE_STRATEGY,
    ctx: PipeContext | None = None,
) -> None:
    if write_strategy not in WRITE_STRATEGIES:
        raise ValueError(f"unknown write_strategy: {write_strategy}")
    pairs = _find_pairs(src_dir)
    line_counts = [_count_non_empty_lines(jf) for jf, _ in pairs]
    total_articles = sum(line_counts)
    dst_dir.mkdir(parents=True, exist_ok=True)
    text_lance = dst_dir / "text.lance"
    images_lance = dst_dir / "images.lance"
    image_labels_lance = dst_dir / "image_labels.lance"
    tmp_dir = dst_dir / "tmp_stage0_streams"
    text_writer: LanceStreamWriter | None = None
    images_writer: LanceStreamWriter | None = None
    image_labels_writer: LanceStreamWriter | None = None
    if write_strategy == "stream_once":
        _remove_existing_lance_outputs(text_lance, images_lance, image_labels_lance)
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        text_writer = LanceStreamWriter(text_lance, TEXT_SCHEMA, temp_dir=tmp_dir)
        images_writer = LanceStreamWriter(
            images_lance,
            IMAGES_SCHEMA,
            temp_dir=tmp_dir,
            data_storage_version="2.1",
        )
        image_labels_writer = LanceStreamWriter(
            image_labels_lance,
            IMAGE_LABELS_SCHEMA,
            temp_dir=tmp_dir,
            data_storage_version="2.1",
        )

    text_written = 0
    images_written = 0
    t0 = time.perf_counter()

    log.info(
        "Start: %d parts, %d articles total, log_interval=%d, write_strategy=%s",
        len(pairs), total_articles, log_interval, write_strategy,
    )

    for part_idx, ((jf, tf), part_total) in enumerate(zip(pairs, line_counts), start=1):
        part_name = tf.stem
        part_t0 = time.perf_counter()
        image_store = _load_part_images(tf)
        log.info(
            "Part %d/%d: %s (%d lines), loaded %d tar images in %s",
            part_idx, len(pairs), jf.name, part_total, len(image_store),
            _fmt_seconds(time.perf_counter() - part_t0),
        )

        text_ids: list[str] = []
        text_infos: list[str] = []
        text_datas: list[str] = []
        text_tags: list[list[str]] = []

        img_ids: list[str] = []
        img_bytes_list: list[bytes] = []
        img_sha256_list: list[str] = []

        imgdata_ids: list[str] = []
        imgdata_infos: list[str] = []
        imgdata_datas: list[str] = []
        imgdata_tags: list[list[str]] = []

        processed_in_part = 0
        with jf.open("r", encoding="utf-8") as f:
            for raw_line in f:
                if not raw_line.strip():
                    continue
                processed_in_part += 1
                entry = json.loads(raw_line)

                html_data = str(entry.get("html", ""))
                meta = extract_html_meta(html_data)
                url = str(entry.get("final_url", meta.get("url", "")))
                title = str(meta.get("title", ""))
                page_type = entry.get("page_type", [])
                if isinstance(page_type, list):
                    tags = [str(value) for value in page_type]
                elif page_type in (None, ""):
                    tags = []
                else:
                    tags = [str(page_type)]

                article_id = hashlib.sha256(html_data.encode("utf-8")).hexdigest()
                article_images = entry.get("images", [])
                image_ids_for_article: list[str] = []
                image_refs_for_article: dict[str, dict[str, object]] = {}

                for img_meta in article_images:
                    image_file = str(img_meta.get("image_file", ""))
                    if not image_file:
                        continue
                    image_record = _resolve_image_record(image_file, part_name, image_store)
                    if image_record is None:
                        log.warning("%s NOT EXIST", image_file)
                        continue
                    image_id = str(image_record["sha256"])
                    raw_bytes = image_record["image_bytes"]
                    if not isinstance(raw_bytes, bytes):
                        raise TypeError(f"image_bytes must be bytes for {image_file}")

                    img_ids.append(image_id)
                    img_bytes_list.append(raw_bytes)
                    img_sha256_list.append(image_id)

                    img_info = build_image_info(
                        img_meta,
                        image_record=image_record,
                    )

                    imgdata_ids.append(image_id)
                    imgdata_infos.append(json.dumps(img_info, ensure_ascii=False))
                    imgdata_datas.append("{}")
                    imgdata_tags.append([])

                    image_url_ori = img_meta.get("image_url_ori")
                    if not image_url_ori:
                        log.warning(
                            "Skip text-side image reference for image_id=%s because image_url_ori is missing",
                            image_id,
                        )
                        continue
                    image_ids_for_article.append(image_id)
                    image_ref_id = build_image_ref_id(image_id, str(image_url_ori))
                    image_refs_for_article[image_ref_id] = build_image_ref(img_meta)

                info = build_text_info(
                    entry,
                    url=url,
                    title=title,
                    image_ids_for_article=image_ids_for_article,
                    image_refs_for_article=image_refs_for_article,
                )

                text_ids.append(article_id)
                text_infos.append(json.dumps(info, ensure_ascii=False))
                text_datas.append(html_data)
                text_tags.append(tags)

                done = text_written + processed_in_part
                if ctx is not None:
                    ctx.set_progress(done, total_articles, f"{jf.name}:{processed_in_part}")
                if log_interval > 0 and (processed_in_part % log_interval == 0 or processed_in_part == part_total):
                    elapsed = time.perf_counter() - t0
                    speed = done / elapsed if elapsed > 0 else 0.0
                    eta = (total_articles - done) / speed if speed > 0 else 0.0
                    log.info(
                        "  progress %d/%d (%.1f%%) | elapsed %s | avg %.2f art/s | eta %s",
                        done, total_articles, 100.0 * done / total_articles,
                        _fmt_seconds(elapsed), speed, _fmt_seconds(max(eta, 0.0)),
                    )

        text_table = pa.table(
            {
                "id": pa.array(text_ids, type=pa.string()),
                "info": pa.array(text_infos, type=pa.string()),
                "data": pa.array(text_datas, type=pa.large_string()),
                "tags": pa.array(text_tags, type=pa.list_(pa.string())),
            },
            schema=TEXT_SCHEMA,
        )
        if write_strategy == "stream_once":
            assert text_writer is not None
            text_writer.write_table(text_table)
        else:
            mode = "overwrite" if part_idx == 1 else "append"
            lance.write_dataset(
                text_table,
                str(text_lance),
                mode=mode,
            )

        if img_ids:
            images_table = pa.table(
                {
                    "id": pa.array(img_ids, type=pa.string()),
                    "image_bytes": pa.array(img_bytes_list, type=pa.large_binary()),
                    "sha256": pa.array(img_sha256_list, type=pa.string()),
                },
                schema=IMAGES_SCHEMA,
            )
            image_labels_table = pa.table(
                {
                    "id": pa.array(imgdata_ids, type=pa.string()),
                    "info": pa.array(imgdata_infos, type=pa.string()),
                    "data": pa.array(imgdata_datas, type=pa.string()),
                    "tags": pa.array(imgdata_tags, type=pa.list_(pa.string())),
                },
                schema=IMAGE_LABELS_SCHEMA,
            )
            if write_strategy == "stream_once":
                assert images_writer is not None
                assert image_labels_writer is not None
                images_writer.write_table(images_table)
                image_labels_writer.write_table(image_labels_table)
            else:
                mode = "overwrite" if part_idx == 1 else "append"
                lance.write_dataset(
                    images_table,
                    str(images_lance),
                    mode=mode,
                    data_storage_version="2.1",
                )
                lance.write_dataset(
                    image_labels_table,
                    str(image_labels_lance),
                    mode=mode,
                    data_storage_version="2.1",
                )

        text_written += len(text_ids)
        images_written += len(img_ids)
        log.info(
            "part done: %s text=%d new_images=%d | part %s | total %s",
            jf.name, len(text_ids), len(img_ids),
            _fmt_seconds(time.perf_counter() - part_t0),
            _fmt_seconds(time.perf_counter() - t0),
        )

    if write_strategy == "stream_once":
        assert text_writer is not None
        assert images_writer is not None
        assert image_labels_writer is not None
        finalize_t0 = time.perf_counter()
        text_writer.finalize(create_empty=True)
        images_writer.finalize()
        image_labels_writer.finalize()
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        log.info(
            "Stream-once finalize done in %s | text_rows=%d image_rows=%d label_rows=%d",
            _fmt_seconds(time.perf_counter() - finalize_t0),
            text_writer.rows_written,
            images_writer.rows_written,
            image_labels_writer.rows_written,
        )

    log.info(
        "Ingest finished: articles=%d images=%d | total %s",
        text_written, images_written, _fmt_seconds(time.perf_counter() - t0),
    )

    compact_t0 = time.perf_counter()
    compact_lance(text_lance, "text")
    if images_lance.is_dir():
        compact_lance(images_lance, "images")
    if image_labels_lance.is_dir():
        compact_lance(image_labels_lance, "image_labels")
    log.info(
        "Compact done in %s | output: %s",
        _fmt_seconds(time.perf_counter() - compact_t0),
        dst_dir,
    )


def _get_source_dir(config: dict[str, Any] | None) -> Path:
    raw = (config or {}).get("source_dir", "")
    source_dir = Path(str(raw)).expanduser()
    if not str(raw).strip():
        raise ValueError("config.source_dir is required for ingest")
    return source_dir.resolve()


def _get_log_interval(config: dict[str, Any] | None) -> int:
    raw = (config or {}).get("log_interval", DEFAULT_LOG_INTERVAL)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_LOG_INTERVAL
    return max(1, value)


def _get_write_strategy(config: dict[str, Any] | None) -> str:
    value = str((config or {}).get("write_strategy", DEFAULT_WRITE_STRATEGY))
    if value not in WRITE_STRATEGIES:
        raise ValueError(f"config.write_strategy must be one of {sorted(WRITE_STRATEGIES)}")
    return value


def ingest(ctx: PipeContext) -> Path | None:
    """Ingest raw wiki jsonl+tar source into a Lance dataset directory."""
    output_dir = ctx.output_dir
    assert output_dir is not None

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    source_dir = _get_source_dir(ctx.config)
    log_interval = _get_log_interval(ctx.config)
    write_strategy = _get_write_strategy(ctx.config)
    run_streaming(
        source_dir,
        output_dir,
        log_interval=log_interval,
        write_strategy=write_strategy,
        ctx=ctx,
    )
    return output_dir


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Convert wiki part*.jsonl + part*.tar to Lance datasets",
    )
    parser.add_argument("src_dir", type=Path, help="Directory containing part*.jsonl and part*.tar")
    parser.add_argument("dst_dir", type=Path, help="Output dataset directory")
    parser.add_argument(
        "--log-interval",
        type=int,
        default=DEFAULT_LOG_INTERVAL,
        help=f"Progress log interval in articles (default: {DEFAULT_LOG_INTERVAL})",
    )
    parser.add_argument(
        "--write-strategy",
        choices=sorted(WRITE_STRATEGIES),
        default=DEFAULT_WRITE_STRATEGY,
        help=f"Lance write strategy (default: {DEFAULT_WRITE_STRATEGY})",
    )
    args = parser.parse_args()

    run_streaming(
        args.src_dir,
        args.dst_dir,
        log_interval=max(1, args.log_interval),
        write_strategy=args.write_strategy,
    )


if __name__ == "__main__":
    main()
