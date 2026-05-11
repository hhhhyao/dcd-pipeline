#!/usr/bin/env python3
"""Run FineWeb-Edu parquet -> DCD text.lance conversion locally."""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import multiprocessing as mp
import shutil
import sys
import tempfile
import time
from pathlib import Path

import lance
import pyarrow as pa
import pyarrow.parquet as pq


def _bootstrap_paths() -> Path:
    root = Path(__file__).resolve().parents[3]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for dcd_root in (root / "reference_repo" / "dcd", root.parent / "dcd"):
        if dcd_root.is_dir() and str(dcd_root) not in sys.path:
            sys.path.insert(0, str(dcd_root))
            break
    for dcd_cli_root in (root / "reference_repo" / "dcd-cli", root.parent / "dcd-cli"):
        if dcd_cli_root.is_dir() and str(dcd_cli_root) not in sys.path:
            sys.path.insert(0, str(dcd_cli_root))
            break
    return root


ROOT = _bootstrap_paths()

from pipelines.fineweb_edu.parquet_to_text_lance import main as pipe  # noqa: E402

DEFAULT_SOURCE_DIR = Path("/root/yaolewei/code/data_process/fineweb_index/workspace/data/fineweb_edu")
DEFAULT_OUTPUT_DIR = ROOT / "workspace" / "text_lance" / "fineweb-edu"


def _plan_file_limits(files: list[Path], max_rows: int) -> list[tuple[int, Path, int]]:
    planned: list[tuple[int, Path, int]] = []
    remaining = max_rows
    for path in files:
        rows = int(pq.ParquetFile(path).metadata.num_rows)
        limit = rows if max_rows <= 0 else min(rows, remaining)
        if limit > 0:
            planned.append((len(planned), path, limit))
        if max_rows > 0:
            remaining -= limit
            if remaining <= 0:
                break
    return planned


def _worker_convert(payload: tuple[int, str, str, str, int, int]) -> tuple[int, int, str]:
    idx, parquet_path_str, source_dir_str, temp_dir_str, batch_rows, max_rows = payload
    parquet_path = Path(parquet_path_str)
    source_dir = Path(source_dir_str)
    shard_path = Path(temp_dir_str) / f"{idx:06d}.lance"
    rows = 0
    first = True
    for table in pipe.iter_file_text_tables(
        parquet_path,
        source_dir=source_dir,
        batch_rows=batch_rows,
        max_rows=max_rows,
    ):
        lance.write_dataset(
            table,
            str(shard_path),
            schema=pipe.TEXT_SCHEMA,
            mode="create" if first else "append",
            data_storage_version="2.1",
        )
        first = False
        rows += table.num_rows
    if first:
        lance.write_dataset(
            pa.Table.from_batches([], schema=pipe.TEXT_SCHEMA),
            str(shard_path),
            schema=pipe.TEXT_SCHEMA,
            mode="create",
            data_storage_version="2.1",
        )
    return idx, rows, str(shard_path)


def _append_shard(shard_path: Path, dst_text: Path, *, first: bool, batch_rows: int) -> None:
    ds = lance.dataset(str(shard_path))
    reader = ds.scanner(batch_size=max(1, batch_rows)).to_reader()
    lance.write_dataset(
        reader,
        str(dst_text),
        schema=pipe.TEXT_SCHEMA,
        mode="create" if first else "append",
        data_storage_version="2.1",
    )


def run(
    *,
    source_dir: Path,
    output_dir: Path,
    workers: int,
    batch_rows: int,
    max_rows: int,
    overwrite: bool,
    prepare: bool,
) -> None:
    source_dir = source_dir.resolve()
    output_dir = output_dir.resolve()
    files = pipe.discover_parquet_files(source_dir)
    planned = _plan_file_limits(files, max_rows=max(0, max_rows))
    output_dir.mkdir(parents=True, exist_ok=True)
    dst_text = output_dir / "text.lance"
    if dst_text.exists():
        if not overwrite:
            raise FileExistsError(f"output already exists, pass --overwrite: {dst_text}")
        shutil.rmtree(dst_text)

    print(f"source: {source_dir}")
    print(f"target: {output_dir}")
    print(f"files: {len(planned)}/{len(files)}, workers: {workers}, batch_rows: {batch_rows}")
    t0 = time.time()
    done = 0
    first_write = True

    with tempfile.TemporaryDirectory(prefix=".fineweb_edu_lance_shards_", dir=str(output_dir.parent)) as temp_dir:
        mp_ctx = mp.get_context("spawn")
        with cf.ProcessPoolExecutor(max_workers=max(1, workers), mp_context=mp_ctx) as pool:
            pending: dict[cf.Future[tuple[int, int, str]], int] = {}
            buffered: dict[int, tuple[int, str]] = {}
            task_iter = iter(planned)
            next_write_idx = 0
            max_pending = max(1, workers * 2)

            def submit_until_full() -> None:
                while len(pending) < max_pending:
                    try:
                        idx, path, limit = next(task_iter)
                    except StopIteration:
                        return
                    fut = pool.submit(
                        _worker_convert,
                        (idx, str(path), str(source_dir), temp_dir, max(1, batch_rows), limit),
                    )
                    pending[fut] = idx

            submit_until_full()
            while pending:
                done_set, _ = cf.wait(pending.keys(), return_when=cf.FIRST_COMPLETED)
                for fut in done_set:
                    pending.pop(fut, None)
                    idx, rows, shard = fut.result()
                    buffered[idx] = (rows, shard)

                while next_write_idx in buffered:
                    rows, shard = buffered.pop(next_write_idx)
                    shard_path = Path(shard)
                    _append_shard(shard_path, dst_text, first=first_write, batch_rows=batch_rows)
                    first_write = False
                    shutil.rmtree(shard_path)
                    done += rows
                    elapsed = time.time() - t0
                    print(f"progress: {done} rows | {next_write_idx + 1}/{len(planned)} files | elapsed {elapsed:.1f}s")
                    next_write_idx += 1
                submit_until_full()

    if first_write:
        lance.write_dataset(
            pa.Table.from_batches([], schema=pipe.TEXT_SCHEMA),
            str(dst_text),
            schema=pipe.TEXT_SCHEMA,
            mode="create",
            data_storage_version="2.1",
        )

    if prepare:
        from dataclawdev.data.util.prepare_dataset import run as prepare_dataset_run

        print("prepare_dataset: start (tokenizer=simple)")
        prepare_dataset_run(output_dir, base_tokenizer="simple")
        print("prepare_dataset: done")

    print(f"done in {time.time() - t0:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert FineWeb-Edu parquet to DCD text.lance")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 1))
    parser.add_argument("--batch-rows", type=int, default=pipe.DEFAULT_BATCH_ROWS)
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    run(
        source_dir=args.source_dir,
        output_dir=args.output_dir,
        workers=max(1, args.workers),
        batch_rows=max(1, args.batch_rows),
        max_rows=max(0, args.max_rows),
        overwrite=args.overwrite,
        prepare=args.prepare,
    )


if __name__ == "__main__":
    main()

