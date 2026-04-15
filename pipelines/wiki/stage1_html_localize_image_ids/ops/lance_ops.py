"""Lance helpers for scans, stream-once writes, caches, and compaction."""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import lance
import pyarrow as pa
from lance.optimize import Compaction

from ops.cache_io import write_arrow_table


LOG = logging.getLogger(__name__)

COMPACT_TABLE_ORDER = ("text", "image_labels", "images")
IMAGE_COMPACTION_OPTIONS = {
    "num_threads": min(16, os.cpu_count() or 16),
    "batch_size": 2048,
    "compaction_mode": "try_binary_copy",
    "binary_copy_read_batch_bytes": 64 * 1024 * 1024,
    "max_bytes_per_file": 64 * 1024 * 1024 * 1024,
}


@dataclass
class StageProgress:
    """Small helper for row-progress logging."""

    name: str
    total_rows: int
    progress_every: int
    counters: dict[str, int]
    processed_rows: int = 0
    start_time: float = field(default_factory=time.time)
    next_report_at: int = 0

    def __post_init__(self) -> None:
        self.next_report_at = self.progress_every if self.progress_every > 0 else sys.maxsize

    def advance(self, count: int = 1) -> None:
        self.processed_rows += count
        if self.progress_every > 0 and self.processed_rows >= self.next_report_at:
            self.report()
            while self.next_report_at <= self.processed_rows:
                self.next_report_at += self.progress_every

    def report(self, *, final: bool = False) -> None:
        elapsed = max(time.time() - self.start_time, 1e-9)
        rate = self.processed_rows / elapsed
        pct = 100.0 * self.processed_rows / self.total_rows if self.total_rows > 0 else 100.0
        if self.total_rows > 0 and self.processed_rows > 0 and rate > 0:
            remaining = max(self.total_rows - self.processed_rows, 0)
            eta_seconds = remaining / rate
            eta_text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + eta_seconds))
        else:
            eta_text = "n/a"
        suffix = "final" if final else "progress"
        counters = " ".join(f"{key}={value:,}" for key, value in self.counters.items())
        print(
            f"[{self.name}:{suffix}] rows={self.processed_rows:,}/{self.total_rows:,} "
            f"({pct:.1f}%) rate={rate:,.0f}/s eta={eta_text} {counters}".rstrip(),
            file=sys.stderr,
        )


def load_callable(spec: str) -> Callable[..., Any]:
    """Load ``module:function`` and return the callable."""
    if ":" not in spec:
        raise ValueError(f"Callable spec must be module:function, got {spec!r}")
    module_name, func_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    fn = getattr(module, func_name)
    if not callable(fn):
        raise TypeError(f"{spec!r} did not resolve to a callable.")
    return fn


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    """Return unique non-empty string values in first-seen order."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    """Create an empty output directory."""
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"Output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def create_absolute_symlink(source_path: Path, link_path: Path) -> None:
    """Create ``link_path`` as an absolute symlink to ``source_path``."""
    if link_path.exists() or link_path.is_symlink():
        if link_path.is_dir() and not link_path.is_symlink():
            shutil.rmtree(link_path)
        else:
            link_path.unlink()
    os.symlink(str(source_path.resolve()), str(link_path))


def quote_sql_string(value: str) -> str:
    """Escape a string literal for Lance SQL filters."""
    return "'" + value.replace("'", "''") + "'"


def make_id_in_filter(id_column: str, ids: Sequence[str]) -> str:
    """Build a SQL ``IN (...)`` predicate for a non-empty list of IDs."""
    if not ids:
        raise ValueError("Cannot build ID filter for an empty list.")
    quoted = ", ".join(quote_sql_string(value) for value in ids)
    return f"{id_column} IN ({quoted})"


def chunked(values: Sequence[str], chunk_size: int) -> Iterable[list[str]]:
    """Yield fixed-size list chunks."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    for start in range(0, len(values), chunk_size):
        yield list(values[start:start + chunk_size])


def make_scanner(
    dataset: Any,
    *,
    columns: list[str] | None,
    batch_size: int,
    filter_expr: str | None = None,
    with_row_id: bool = False,
) -> Any:
    """Build a Lance scanner with compatibility fallbacks."""
    scanner_kwargs: dict[str, Any] = {
        "columns": columns,
        "batch_size": batch_size,
        "batch_readahead": 1,
        "fragment_readahead": 1,
        "scan_in_order": True,
    }
    if filter_expr:
        scanner_kwargs["filter"] = filter_expr
    if with_row_id:
        scanner_kwargs["with_row_id"] = True
    try:
        return dataset.scanner(**scanner_kwargs)
    except TypeError:
        scanner_kwargs.pop("scan_in_order", None)
        try:
            return dataset.scanner(**scanner_kwargs)
        except TypeError:
            scanner_kwargs.pop("batch_readahead", None)
            scanner_kwargs.pop("fragment_readahead", None)
            return dataset.scanner(**scanner_kwargs)


def iter_batches(scanner: Any, batch_size: int) -> Iterable[Any]:
    """Yield record batches from a Lance scanner."""
    if hasattr(scanner, "to_batches"):
        yield from scanner.to_batches()
        return
    if hasattr(scanner, "to_table"):
        yield from scanner.to_table().to_batches(max_chunksize=batch_size)
        return
    raise RuntimeError("Unsupported Lance scanner type.")


def rows_to_table(rows: list[dict[str, Any]], schema: pa.Schema) -> pa.Table:
    """Convert row dicts to a typed Arrow table."""
    return pa.Table.from_pydict(
        {field.name: [row.get(field.name) for row in rows] for field in schema},
        schema=schema,
    )


def columns_to_table(columns: dict[str, Sequence[Any]], schema: pa.Schema) -> pa.Table:
    """Convert column arrays to a typed Arrow table."""
    return pa.Table.from_pydict(
        {field.name: list(columns.get(field.name, [])) for field in schema},
        schema=schema,
    )


@dataclass
class LanceWriteStats:
    """Bookkeeping for a logical dataset write."""

    write_seconds: float = 0.0
    finalize_seconds: float = 0.0
    rows_written: int = 0
    batches_written: int = 0

    @property
    def total_seconds(self) -> float:
        return self.write_seconds + self.finalize_seconds


class LanceDatasetWriter:
    """Single-commit Lance writer backed by an Arrow IPC stream.

    The pipe writes batches incrementally into a temporary Arrow stream, then
    performs one ``lance.write_dataset`` call at finalize time. This keeps memory
    bounded while avoiding many append commits.
    """

    def __init__(self, dataset_path: Path, schema: pa.Schema, *, temp_dir: Path) -> None:
        self.dataset_path = dataset_path
        self.schema = schema
        self.temp_dir = temp_dir
        self.stats = LanceWriteStats()
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{dataset_path.stem}_",
            suffix=".arrowstream",
            dir=str(self.temp_dir),
        )
        os.close(fd)
        self._tmp_path: Path | None = Path(tmp_name)
        self._stream_sink: pa.OSFile | None = pa.OSFile(str(self._tmp_path), "wb")
        self._stream_writer: pa.ipc.RecordBatchStreamWriter | None = pa.ipc.new_stream(
            self._stream_sink,
            schema,
        )

    def write_rows(self, rows: list[dict[str, Any]]) -> None:
        if rows:
            self.write_table(rows_to_table(rows, self.schema))

    def write_columns(self, columns: dict[str, Sequence[Any]]) -> None:
        if not columns:
            return
        row_count = len(next(iter(columns.values()), []))
        if row_count > 0:
            self.write_table(columns_to_table(columns, self.schema))

    def write_table(self, table: pa.Table) -> None:
        if table.num_rows <= 0:
            return
        if self._stream_writer is None:
            raise RuntimeError("stream writer is not initialized")
        t0 = time.perf_counter()
        for batch in table.to_batches():
            self._stream_writer.write_batch(batch)
            self.stats.batches_written += 1
        self.stats.write_seconds += time.perf_counter() - t0
        self.stats.rows_written += table.num_rows

    def finalize(self) -> LanceWriteStats:
        t0 = time.perf_counter()
        try:
            if self._stream_writer is not None:
                self._stream_writer.close()
                self._stream_writer = None
            if self._stream_sink is not None:
                self._stream_sink.close()
                self._stream_sink = None
            if self.stats.rows_written > 0 and self._tmp_path is not None:
                reader = pa.ipc.open_stream(str(self._tmp_path))
                data: Any = reader
            else:
                data = pa.Table.from_batches([], schema=self.schema)
            lance.write_dataset(
                data,
                str(self.dataset_path),
                mode="create",
                schema=self.schema,
                data_storage_version="2.1",
            )
        finally:
            if self._tmp_path is not None:
                self._tmp_path.unlink(missing_ok=True)
                self._tmp_path = None
        self.stats.finalize_seconds += time.perf_counter() - t0
        return self.stats


def scan_image_label_caches(
    image_labels_path: Path,
    *,
    rowids_cache_path: Path,
    order_cache_path: Path,
    batch_size: int,
    progress_every: int,
) -> dict[str, int]:
    """Scan image_labels once and persist dedup-oriented caches."""
    ds = lance.dataset(str(image_labels_path))
    counters = {"rows": 0, "unique_image_ids": 0, "duplicate_rows": 0}
    progress = StageProgress(
        name="image_labels_cache",
        total_rows=int(ds.count_rows()),
        progress_every=progress_every,
        counters=counters,
    )
    row_ids_by_image_id: dict[str, list[int]] = {}
    order_rows: list[dict[str, Any]] = []
    ordinal = 0
    next_position = 0
    scanner = make_scanner(ds, columns=["id"], batch_size=batch_size)
    for batch in iter_batches(scanner, batch_size):
        ids = batch.column("id").to_pylist()
        row_positions = range(next_position, next_position + len(ids))
        next_position += len(ids)
        for image_id, row_id in zip(ids, row_positions, strict=True):
            image_id = str(image_id)
            row_id = int(row_id)
            counters["rows"] += 1
            progress.advance()
            bucket = row_ids_by_image_id.setdefault(image_id, [])
            if bucket:
                counters["duplicate_rows"] += 1
            else:
                counters["unique_image_ids"] += 1
                order_rows.append({
                    "image_id": image_id,
                    "first_row_id": row_id,
                    "first_seen_ordinal": ordinal,
                })
                ordinal += 1
            bucket.append(row_id)

    rowids_table = pa.table({
        "image_id": pa.array(list(row_ids_by_image_id.keys()), type=pa.string()),
        "row_ids": pa.array(list(row_ids_by_image_id.values()), type=pa.list_(pa.int64())),
    })
    order_table = pa.table({
        "image_id": pa.array([row["image_id"] for row in order_rows], type=pa.string()),
        "first_row_id": pa.array([row["first_row_id"] for row in order_rows], type=pa.int64()),
        "first_seen_ordinal": pa.array([row["first_seen_ordinal"] for row in order_rows], type=pa.int64()),
    })
    write_arrow_table(rowids_cache_path, rowids_table)
    write_arrow_table(order_cache_path, order_table)
    progress.report(final=True)
    return counters


def scan_images_caches(
    images_path: Path,
    *,
    order_cache_path: Path,
    batch_size: int,
    progress_every: int,
) -> dict[str, int]:
    """Scan images once and persist first-seen ordering for dedup."""
    ds = lance.dataset(str(images_path))
    counters = {"rows": 0, "unique_image_ids": 0, "duplicate_rows": 0}
    progress = StageProgress(
        name="images_cache",
        total_rows=int(ds.count_rows()),
        progress_every=progress_every,
        counters=counters,
    )
    first_row_id_by_image_id: dict[str, int] = {}
    order_rows: list[dict[str, Any]] = []
    ordinal = 0
    next_position = 0
    scanner = make_scanner(ds, columns=["id"], batch_size=batch_size)
    for batch in iter_batches(scanner, batch_size):
        ids = batch.column("id").to_pylist()
        row_positions = range(next_position, next_position + len(ids))
        next_position += len(ids)
        for image_id, row_id in zip(ids, row_positions, strict=True):
            image_id = str(image_id)
            row_id = int(row_id)
            counters["rows"] += 1
            progress.advance()
            if image_id in first_row_id_by_image_id:
                counters["duplicate_rows"] += 1
                continue
            first_row_id_by_image_id[image_id] = row_id
            counters["unique_image_ids"] += 1
            order_rows.append({
                "image_id": image_id,
                "first_row_id": row_id,
                "first_seen_ordinal": ordinal,
            })
            ordinal += 1

    order_table = pa.table({
        "image_id": pa.array([row["image_id"] for row in order_rows], type=pa.string()),
        "first_row_id": pa.array([row["first_row_id"] for row in order_rows], type=pa.int64()),
        "first_seen_ordinal": pa.array([row["first_seen_ordinal"] for row in order_rows], type=pa.int64()),
    })
    write_arrow_table(order_cache_path, order_table)
    progress.report(final=True)
    return counters


def fetch_image_label_infos_by_ids(
    image_labels_dataset: Any,
    image_ids: Sequence[str],
    *,
    batch_size: int,
    filter_chunk_size: int = 1000,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch all image-label rows for the requested image IDs."""
    unique_ids = dedupe_preserve_order(image_ids)
    if not unique_ids:
        return {}

    out: dict[str, list[dict[str, Any]]] = {}
    for id_chunk in chunked(unique_ids, filter_chunk_size):
        scanner = make_scanner(
            image_labels_dataset,
            columns=["id", "info"],
            batch_size=batch_size,
            filter_expr=make_id_in_filter("id", id_chunk),
        )
        for batch in iter_batches(scanner, batch_size):
            ids = batch.column("id").to_pylist()
            infos = batch.column("info").to_pylist()
            for image_id, info_raw in zip(ids, infos, strict=True):
                out.setdefault(str(image_id), []).append({
                    "id": str(image_id),
                    "info": info_raw,
                })
    return out


def load_rowids_cache(path: Path) -> dict[str, list[int]]:
    """Load ``image_id -> row_ids`` from an Arrow cache file."""
    table = pa.ipc.RecordBatchFileReader(pa.memory_map(str(path), "r")).read_all()
    return {
        str(image_id): [int(value) for value in row_ids]
        for image_id, row_ids in zip(
            table.column("image_id").to_pylist(),
            table.column("row_ids").to_pylist(),
            strict=True,
        )
    }


def load_order_cache(path: Path) -> list[dict[str, Any]]:
    """Load first-seen image ID ordering from an Arrow cache file."""
    table = pa.ipc.RecordBatchFileReader(pa.memory_map(str(path), "r")).read_all()
    rows = table.to_pylist()
    rows.sort(key=lambda row: int(row["first_seen_ordinal"]))
    return rows


def _rss_gib() -> float:
    with open("/proc/self/status", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("VmRSS:"):
                rss_kib = int(line.split()[1])
                return rss_kib / 1024 / 1024
    return 0.0


def compact_lance_table(lance_path: str, table_name: str) -> dict[str, float]:
    """Compact a Lance dataset and refresh scalar indices."""
    LOG.info("Compacting %s (%s) ...", lance_path, table_name)
    t0 = time.time()
    ds: Any = lance.dataset(lance_path)
    metrics = {
        "rewrite_execute_seconds": 0.0,
        "commit_seconds": 0.0,
        "index_create_seconds": 0.0,
        "optimize_indices_seconds": 0.0,
        "cleanup_old_versions_seconds": 0.0,
        "total_seconds": 0.0,
    }
    compact_kwargs: dict[str, Any] = {}
    if table_name == "images":
        compact_kwargs.update(IMAGE_COMPACTION_OPTIONS)
    plan = Compaction.plan(ds, compact_kwargs)
    rewrites = []
    tasks = list(plan.tasks)
    progress_t0 = time.time()
    for task_idx, task in enumerate(tasks, start=1):
        task_t0 = time.perf_counter()
        rewrites.append(task.execute(ds))
        metrics["rewrite_execute_seconds"] += time.perf_counter() - task_t0
        elapsed = time.time() - progress_t0
        LOG.info(
            "Compaction progress %s: %d/%d tasks [elapsed %.0fs, rss %.1f GiB]",
            table_name,
            task_idx,
            len(tasks),
            elapsed,
            _rss_gib(),
        )
    if rewrites:
        commit_t0 = time.perf_counter()
        Compaction.commit(ds, rewrites)
        metrics["commit_seconds"] += time.perf_counter() - commit_t0

    existing = {idx["name"] for idx in ds.list_indices()}
    index_plan: list[tuple[str, str]] = [("id", "BTREE")]
    if "tags" in ds.schema.names:
        index_plan.append(("tags", "LABEL_LIST"))
    for column_name, index_type in index_plan:
        index_name = f"{column_name}_idx"
        if index_name not in existing:
            index_t0 = time.perf_counter()
            ds.create_scalar_index(column_name, index_type=index_type)
            metrics["index_create_seconds"] += time.perf_counter() - index_t0

    optimize_t0 = time.perf_counter()
    ds.optimize.optimize_indices()
    metrics["optimize_indices_seconds"] += time.perf_counter() - optimize_t0
    if hasattr(ds, "cleanup_old_versions"):
        cleanup_t0 = time.perf_counter()
        stats = ds.cleanup_old_versions(
            older_than=timedelta(seconds=0),
            delete_unverified=True,
        )
        metrics["cleanup_old_versions_seconds"] += time.perf_counter() - cleanup_t0
        if getattr(stats, "bytes_removed", 0):
            LOG.info(
                "Cleaned up %d old versions, freed %.1f GB",
                stats.old_versions,
                stats.bytes_removed / 1e9,
            )
    metrics["total_seconds"] = time.time() - t0
    LOG.info("Compact %s done in %.0fs", table_name, metrics["total_seconds"])
    return metrics


def normalize_compact_tables(table_names: list[str] | None) -> list[str]:
    """Return compact table names in preferred execution order."""
    if table_names is None:
        requested = {"text", "image_labels"}
    else:
        requested = set(table_names)
        unknown = requested.difference(COMPACT_TABLE_ORDER)
        if unknown:
            raise ValueError(f"unknown compact table(s): {sorted(unknown)}")
    if "images" in requested:
        LOG.warning("Skipping compaction request for images because output images.lance is a source symlink")
        requested.discard("images")
    return [name for name in COMPACT_TABLE_ORDER if name in requested]


def compact_selected_tables(output_dir: Path, compact_tables: list[str]) -> dict[str, Any]:
    """Compact selected output Lance datasets in stable order."""
    aggregated = {
        "rewrite_execute_seconds": 0.0,
        "commit_seconds": 0.0,
        "index_create_seconds": 0.0,
        "optimize_indices_seconds": 0.0,
        "cleanup_old_versions_seconds": 0.0,
        "total_seconds": 0.0,
    }
    table_metrics: dict[str, dict[str, float]] = {}
    if not compact_tables:
        LOG.info("Skipping compaction because no tables were selected")
        return {"tables": table_metrics, "profile": {"metrics": aggregated}}
    lance_paths = {
        "text": output_dir / "text.lance",
        "image_labels": output_dir / "image_labels.lance",
        "images": output_dir / "images.lance",
    }
    for table_name in compact_tables:
        lance_path = lance_paths[table_name]
        if not lance_path.exists():
            LOG.warning("Skipping compaction for %s because %s does not exist", table_name, lance_path)
            continue
        metrics = compact_lance_table(str(lance_path), table_name)
        table_metrics[table_name] = metrics
        for key, value in metrics.items():
            aggregated[key] += value
    return {"tables": table_metrics, "profile": {"metrics": aggregated}}
