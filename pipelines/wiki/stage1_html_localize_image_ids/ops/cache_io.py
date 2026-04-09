"""Arrow and JSONL cache helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.ipc as pa_ipc


def write_arrow_table(path: Path, table: pa.Table) -> None:
    """Write a single Arrow IPC file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with pa.OSFile(str(path), "wb") as sink:
        with pa_ipc.new_file(sink, table.schema) as writer:
            writer.write_table(table)


def read_arrow_table(path: Path) -> pa.Table:
    """Read a single Arrow IPC file."""
    with pa.memory_map(str(path), "r") as source:
        reader = pa_ipc.RecordBatchFileReader(source)
        return reader.read_all()


class JsonlShardWriter:
    """Buffer JSONL records into cache shards and merge them later."""

    def __init__(
        self,
        cache_dir: Path,
        stem: str,
        *,
        flush_rows: int,
    ) -> None:
        self.cache_dir = cache_dir
        self.stem = stem
        self.flush_rows = max(flush_rows, 1)
        self._buffer: list[str] = []
        self._rows = 0
        self._shard_idx = 0
        self._shards: list[Path] = []

    def write(self, record: dict[str, Any]) -> None:
        self._buffer.append(json.dumps(record, ensure_ascii=False))
        self._rows += 1
        if len(self._buffer) >= self.flush_rows:
            self.flush()

    def flush(self) -> None:
        if not self._buffer:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        shard_path = self.cache_dir / f"{self.stem}-{self._shard_idx:05d}.jsonl"
        shard_path.write_text("\n".join(self._buffer) + "\n", encoding="utf-8")
        self._shards.append(shard_path)
        self._shard_idx += 1
        self._buffer.clear()

    def finalize(self, output_path: Path) -> int:
        self.flush()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as out:
            for shard in self._shards:
                with shard.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        out.write(line)
        return self._rows

