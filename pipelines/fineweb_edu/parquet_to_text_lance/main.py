"""Convert FineWeb-Edu parquet shards into DCD text batches."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

try:
    from dcd_cli.pipe import PipeContext
except ImportError:  # pragma: no cover - local tests use a lightweight fake ctx
    PipeContext = Any  # type: ignore[misc,assignment]

DATASET_TAG = "fineweb-edu"
DEFAULT_SOURCE_GLOB = "**/*.parquet"
DEFAULT_BATCH_ROWS = 10_000
TEXT_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("data", pa.large_string()),
    pa.field("info", pa.string()),
    pa.field("tags", pa.list_(pa.string())),
])
PREFIXED_TEXT_SCHEMA = pa.schema([
    pa.field("text/id", pa.string()),
    pa.field("text/data", pa.large_string()),
    pa.field("text/info", pa.string()),
    pa.field("text/tags", pa.list_(pa.string())),
])


def _cfg_int(config: dict[str, Any], key: str, default: int) -> int:
    try:
        value = int(config.get(key, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(0, value)


def _cfg_str(config: dict[str, Any], key: str, default: str) -> str:
    value = str(config.get(key, default) or default).strip()
    return value or default


def source_dir_from_ctx(ctx: PipeContext) -> Path:
    volumes = getattr(ctx, "volumes", None) or {}
    source = volumes.get("source")
    if source is None:
        raise ValueError("volume 'source' is required")
    source_dir = Path(source)
    if not source_dir.is_dir():
        raise FileNotFoundError(f"source directory not found: {source_dir}")
    return source_dir


def discover_parquet_files(source_dir: Path, source_glob: str = DEFAULT_SOURCE_GLOB) -> list[Path]:
    files = sorted(path for path in source_dir.glob(source_glob) if path.is_file())
    if not files:
        raise FileNotFoundError(f"no parquet files matched {source_glob!r} under {source_dir}")
    return files


def parquet_row_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def count_rows(files: list[Path], max_rows: int = 0) -> int:
    total = 0
    for path in files:
        total += parquet_row_count(path)
        if max_rows > 0 and total >= max_rows:
            return max_rows
    return total


def _source_label(path: Path, source_dir: Path) -> str:
    try:
        return path.relative_to(source_dir).as_posix()
    except ValueError:
        return path.name


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        return str(value)
    return value


def _compact_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _fallback_id(source_file: str, row_index: int) -> str:
    digest = hashlib.sha1(f"{source_file}:{row_index}".encode("utf-8")).hexdigest()
    return f"{DATASET_TAG}-{digest}"


def _append_tag(tags: list[str], value: Any) -> None:
    if value is None:
        return
    tag = str(value).strip()
    if tag and tag not in tags:
        tags.append(tag)


def text_table_from_record_batch(
    batch: pa.RecordBatch,
    *,
    source_file: str,
    row_offset: int,
) -> pa.Table:
    names = batch.schema.names
    if "text" not in names:
        raise ValueError("parquet batch is missing required 'text' column")
    row_count = batch.num_rows
    text_values = batch.column(names.index("text")).to_pylist()
    id_values = (
        batch.column(names.index("id")).to_pylist()
        if "id" in names
        else [None] * row_count
    )
    metadata_names = [name for name in names if name not in {"text", "id"}]
    metadata = {
        name: batch.column(names.index(name)).to_pylist()
        for name in metadata_names
    }

    ids: list[str] = []
    data: list[str] = []
    info: list[str] = []
    tags: list[list[str]] = []
    for idx in range(row_count):
        raw_id = id_values[idx]
        item_id = str(raw_id).strip() if raw_id is not None else ""
        ids.append(item_id or _fallback_id(source_file, row_offset + idx))
        data.append("" if text_values[idx] is None else str(text_values[idx]))

        info_obj: dict[str, Any] = {"source_file": source_file}
        for name in metadata_names:
            info_obj[name] = _json_safe(metadata[name][idx])
        info.append(_compact_json(info_obj))

        row_tags = [DATASET_TAG]
        if "language" in metadata:
            _append_tag(row_tags, metadata["language"][idx])
        if "dump" in metadata:
            _append_tag(row_tags, metadata["dump"][idx])
        tags.append(row_tags)

    return pa.table(
        {
            "id": pa.array(ids, type=pa.string()),
            "data": pa.array(data, type=pa.large_string()),
            "info": pa.array(info, type=pa.string()),
            "tags": pa.array(tags, type=pa.list_(pa.string())),
        },
        schema=TEXT_SCHEMA,
    )


def prefixed_record_batch_from_text_table(table: pa.Table) -> pa.RecordBatch:
    prefixed = pa.table(
        {
            "text/id": table.column("id"),
            "text/data": table.column("data"),
            "text/info": table.column("info"),
            "text/tags": table.column("tags"),
        },
        schema=PREFIXED_TEXT_SCHEMA,
    )
    batches = prefixed.to_batches()
    if batches:
        return batches[0]
    return pa.RecordBatch.from_arrays(
        [pa.array([], type=field.type) for field in PREFIXED_TEXT_SCHEMA],
        schema=PREFIXED_TEXT_SCHEMA,
    )


def iter_file_text_tables(
    parquet_path: Path,
    *,
    source_dir: Path,
    batch_rows: int = DEFAULT_BATCH_ROWS,
    max_rows: int = 0,
) -> Iterator[pa.Table]:
    source_file = _source_label(parquet_path, source_dir)
    emitted = 0
    parquet_file = pq.ParquetFile(parquet_path)
    for batch in parquet_file.iter_batches(batch_size=max(1, batch_rows)):
        if max_rows > 0 and emitted >= max_rows:
            break
        if max_rows > 0 and emitted + batch.num_rows > max_rows:
            batch = batch.slice(0, max_rows - emitted)
        if batch.num_rows == 0:
            continue
        yield text_table_from_record_batch(batch, source_file=source_file, row_offset=emitted)
        emitted += batch.num_rows


def ingest(ctx: PipeContext) -> Iterator[pa.RecordBatch]:
    config = getattr(ctx, "config", None) or {}
    source_dir = source_dir_from_ctx(ctx)
    source_glob = _cfg_str(config, "source_glob", DEFAULT_SOURCE_GLOB)
    batch_rows = _cfg_int(config, "batch_rows", DEFAULT_BATCH_ROWS) or DEFAULT_BATCH_ROWS
    max_rows = _cfg_int(config, "max_rows", 0)
    files = discover_parquet_files(source_dir, source_glob)
    total = count_rows(files, max_rows=max_rows)
    completed = 0

    for parquet_path in files:
        remaining = max_rows - completed if max_rows > 0 else 0
        if max_rows > 0 and remaining <= 0:
            break
        for table in iter_file_text_tables(
            parquet_path,
            source_dir=source_dir,
            batch_rows=batch_rows,
            max_rows=remaining,
        ):
            completed += table.num_rows
            if hasattr(ctx, "set_progress"):
                ctx.set_progress(completed, total, f"rows: {completed}")
            yield prefixed_record_batch_from_text_table(table)
