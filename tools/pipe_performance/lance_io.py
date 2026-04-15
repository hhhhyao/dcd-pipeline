"""Generic Lance I/O helpers for local performance experiments."""

from __future__ import annotations

import time
from dataclasses import dataclass
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

import lance
import pyarrow as pa


@dataclass
class LanceWriteStats:
    rows_written: int = 0
    batches_written: int = 0
    write_seconds: float = 0.0


class StreamOnceLanceWriter:
    """Collect RecordBatches and commit them to Lance with one write call.

    This helper is intentionally generic and repo-local. Production pipes should
    vendor only the tiny writer code they need to stay self-contained.
    """

    def __init__(self, output_path: Path, schema: pa.Schema, *, temp_dir: Path | None = None) -> None:
        self.output_path = output_path
        self.schema = schema
        self.temp_dir = temp_dir or output_path.parent
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{output_path.stem}_",
            suffix=".arrowstream",
            dir=str(self.temp_dir),
        )
        os.close(fd)
        self._tmp_path: Path | None = Path(tmp_name)
        self._sink: pa.OSFile | None = pa.OSFile(str(self._tmp_path), "wb")
        self._writer: pa.ipc.RecordBatchStreamWriter | None = pa.ipc.new_stream(self._sink, schema)
        self.stats = LanceWriteStats()

    def write_batch(self, batch: pa.RecordBatch) -> None:
        if batch.num_rows <= 0:
            return
        if self._writer is None:
            raise RuntimeError("writer already finalized")
        self._writer.write_batch(batch)
        self.stats.rows_written += batch.num_rows
        self.stats.batches_written += 1

    def write_table(self, table: pa.Table) -> None:
        for batch in table.to_batches():
            self.write_batch(batch)

    def finish(self) -> LanceWriteStats:
        start = time.perf_counter()
        try:
            if self._writer is not None:
                self._writer.close()
                self._writer = None
            if self._sink is not None:
                self._sink.close()
                self._sink = None
            if self.stats.rows_written > 0 and self._tmp_path is not None:
                data: Any = pa.ipc.open_stream(str(self._tmp_path))
            else:
                data = pa.Table.from_batches([], schema=self.schema)
            lance.write_dataset(
                data,
                str(self.output_path),
                mode="create",
                schema=self.schema,
                data_storage_version="2.1",
            )
        finally:
            if self._tmp_path is not None:
                self._tmp_path.unlink(missing_ok=True)
                self._tmp_path = None
        self.stats.write_seconds = time.perf_counter() - start
        return self.stats


def write_record_batches_once(
    output_path: Path,
    schema: pa.Schema,
    batches: Iterable[pa.RecordBatch],
) -> None:
    """Write a RecordBatch iterable to Lance with a single dataset commit."""
    batch_list = list(batches)
    if batch_list:
        data: Any = pa.RecordBatchReader.from_batches(schema, batch_list)
    else:
        data = pa.Table.from_batches([], schema=schema)
    lance.write_dataset(
        data,
        str(output_path),
        mode="create",
        schema=schema,
        data_storage_version="2.1",
    )


def scan_columns(
    dataset_path: Path,
    *,
    columns: Sequence[str] | None = None,
    batch_size: int = 1024,
) -> Iterable[pa.RecordBatch]:
    """Yield narrow-column RecordBatches from a Lance dataset."""
    ds = lance.dataset(str(dataset_path))
    scanner = ds.scanner(
        columns=list(columns) if columns is not None else None,
        batch_size=batch_size,
        batch_readahead=1,
        fragment_readahead=1,
    )
    if hasattr(scanner, "to_batches"):
        yield from scanner.to_batches()
    else:
        yield from scanner.to_table().to_batches(max_chunksize=batch_size)
