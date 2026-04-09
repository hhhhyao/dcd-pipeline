#!/usr/bin/env python3
"""Run stage3_md_to_openai locally on a Lance dataset."""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import multiprocessing as mp
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import lance
import pyarrow as pa


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

from dcd_cli.pipe import PipeContext  # noqa: E402
import pipelines.wiki.stage3_md_to_openai as PIPE_MODULE  # noqa: E402

PIPE_NAME = "stage3_md_to_openai"
pipe_map = PIPE_MODULE.map

_WORKER_MAP = None
_WORKER_CTX = None


def _build_table(out_batch: dict[str, list[Any]], schema: pa.Schema) -> pa.Table:
    arrays: dict[str, pa.Array] = {}
    for field in schema:
        values = out_batch.get(field.name)
        if values is None:
            raise KeyError(f"Missing output column: {field.name}")
        arrays[field.name] = pa.array(values, type=field.type)
    return pa.table(arrays, schema=schema)


def _drop_tags_schema(schema: pa.Schema) -> pa.Schema:
    return pa.schema([field for field in schema if field.name != "tags"])


def _link_or_replace(src: Path, dst: Path) -> None:
    import os as os_mod

    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        else:
            shutil.rmtree(dst)
    rel = os_mod.path.relpath(src, dst.parent)
    os_mod.symlink(rel, dst)


def _worker_init(
    root_str: str,
    dataset: str,
    dataset_dir_str: str,
    message_role: str,
) -> None:
    global _WORKER_MAP, _WORKER_CTX
    root = Path(root_str)
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

    from dcd_cli.pipe import PipeContext as _PipeContext

    _WORKER_MAP = PIPE_MODULE.map
    _WORKER_CTX = _PipeContext(
        dataset=dataset,
        pipe_name=PIPE_NAME,
        pipe_version=1,
        config={"message_role": message_role},
        volumes={"dataset": Path(dataset_dir_str)},
    )


def _worker_process(
    payload: tuple[int, dict[str, list[Any]]],
) -> tuple[int, int, dict[str, list[Any]]]:
    idx, batch = payload
    out_batch = _WORKER_MAP(batch, _WORKER_CTX)
    row_count = len(next(iter(out_batch.values()))) if out_batch else 0
    return idx, row_count, out_batch


def _iter_batches(
    ds: Any,
    batch_size: int,
) -> Iterator[tuple[int, dict[str, list[Any]]]]:
    scanner = ds.scanner(batch_size=batch_size)
    for idx, rb in enumerate(scanner.to_batches(), start=1):
        yield idx, {name: rb.column(name).to_pylist() for name in rb.schema.names}


def _verify_same_order(src_text: Path, dst_text: Path) -> None:
    src_ids = lance.dataset(str(src_text)).to_table(columns=["id"]).column("id").to_pylist()
    dst_ids = lance.dataset(str(dst_text)).to_table(columns=["id"]).column("id").to_pylist()
    if len(src_ids) != len(dst_ids):
        raise RuntimeError(
            f"Row count mismatch: src={len(src_ids)} dst={len(dst_ids)}",
        )
    for idx, (sid, did) in enumerate(zip(src_ids, dst_ids, strict=True)):
        if sid != did:
            raise RuntimeError(
                f"Row order mismatch at index={idx}: src_id={sid}, dst_id={did}",
            )


def run(
    src_dataset_dir: Path,
    dst_dataset_dir: Path,
    *,
    batch_size: int = 64,
    message_role: str = "user",
    workers: int = 1,
    run_prepare: bool = True,
) -> None:
    src_text = src_dataset_dir / "text.lance"
    if not src_text.is_dir():
        raise FileNotFoundError(f"Source text.lance not found: {src_text}")

    dst_dataset_dir.mkdir(parents=True, exist_ok=True)
    dst_text = dst_dataset_dir / "text.lance"
    if dst_text.exists():
        shutil.rmtree(dst_text)

    ds = lance.dataset(str(src_text))
    schema = _drop_tags_schema(ds.schema)
    total = ds.count_rows()

    ctx = PipeContext(
        dataset=src_dataset_dir.name,
        pipe_name=PIPE_NAME,
        pipe_version=1,
        config={"message_role": message_role},
        volumes={"dataset": src_dataset_dir},
    )

    print(f"source: {src_dataset_dir}")
    print(f"target: {dst_dataset_dir}")
    print(
        f"rows: {total}, batch_size: {batch_size}, "
        f"message_role: {message_role}, workers: {workers}",
    )

    t0 = time.time()
    done = 0
    first_batch_written = False
    if workers <= 1:
        for i, batch in _iter_batches(ds, batch_size):
            out_batch = pipe_map(batch, ctx)
            out_table = _build_table(out_batch, schema)
            mode = "overwrite" if not first_batch_written else "append"
            lance.write_dataset(out_table, str(dst_text), mode=mode)
            first_batch_written = True
            row_count = len(next(iter(batch.values()))) if batch else 0
            done += row_count
            if i % 20 == 0 or done >= total:
                elapsed = time.time() - t0
                eta = (total - done) * elapsed / done if done else 0.0
                print(
                    f"progress: {done}/{total} ({done * 100 / max(total, 1):.1f}%) | "
                    f"elapsed {elapsed:.1f}s | eta {eta:.1f}s",
                )
    else:
        mp_ctx = mp.get_context("spawn")
        with cf.ProcessPoolExecutor(
            max_workers=workers,
            mp_context=mp_ctx,
            initializer=_worker_init,
            initargs=(
                str(ROOT),
                src_dataset_dir.name,
                str(src_dataset_dir),
                message_role,
            ),
        ) as pool:
            pending: dict[cf.Future[tuple[int, int, dict[str, list[Any]]]], int] = {}
            buffered: dict[int, tuple[int, dict[str, list[Any]]]] = {}
            next_write_idx = 1
            batch_iter = iter(_iter_batches(ds, batch_size))
            max_pending = max(1, workers * 4)

            def _submit_until_full() -> None:
                while len(pending) < max_pending:
                    try:
                        payload = next(batch_iter)
                    except StopIteration:
                        return
                    fut = pool.submit(_worker_process, payload)
                    pending[fut] = payload[0]

            _submit_until_full()
            while pending:
                done_set, _ = cf.wait(pending.keys(), return_when=cf.FIRST_COMPLETED)
                for fut in done_set:
                    pending.pop(fut, None)
                    idx, row_count, out_batch = fut.result()
                    buffered[idx] = (row_count, out_batch)

                while next_write_idx in buffered:
                    row_count, out_batch = buffered.pop(next_write_idx)
                    out_table = _build_table(out_batch, schema)
                    mode = "overwrite" if not first_batch_written else "append"
                    lance.write_dataset(out_table, str(dst_text), mode=mode)
                    first_batch_written = True

                    done += row_count
                    if next_write_idx % 20 == 0 or done >= total:
                        elapsed = time.time() - t0
                        eta = (total - done) * elapsed / done if done else 0.0
                        print(
                            f"progress: {done}/{total} ({done * 100 / max(total, 1):.1f}%) | "
                            f"elapsed {elapsed:.1f}s | eta {eta:.1f}s",
                        )
                    next_write_idx += 1

                _submit_until_full()

    _verify_same_order(src_text, dst_text)

    for table_name in ("images.lance", "image_labels.lance"):
        src_table = src_dataset_dir / table_name
        dst_table = dst_dataset_dir / table_name
        if src_table.is_dir():
            _link_or_replace(src_table, dst_table)

    if run_prepare:
        from dataclawdev.data.util.prepare_dataset import run as prepare_dataset_run

        print("prepare_dataset: start (tokenizer=simple)")
        prepare_dataset_run(dst_dataset_dir, base_tokenizer="simple")
        print("prepare_dataset: done")

    print(f"done in {time.time() - t0:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Run {PIPE_NAME} locally")
    parser.add_argument(
        "src_dataset_dir",
        nargs="?",
        type=Path,
        default=ROOT / "workspace" / "md_lance" / "wiki_0320_en_has_pic",
    )
    parser.add_argument(
        "dst_dataset_dir",
        nargs="?",
        type=Path,
        default=ROOT / "workspace" / "openai_lance" / "wiki_0320_en_has_pic_openai",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument(
        "--message-role",
        default="user",
        help="Role used for the single generated OpenAI message",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 2) - 1),
    )
    parser.add_argument("--no-prepare", action="store_true")
    args = parser.parse_args()

    run(
        args.src_dataset_dir.resolve(),
        args.dst_dataset_dir.resolve(),
        batch_size=max(1, args.batch_size),
        message_role=str(args.message_role or "user"),
        workers=max(1, args.workers),
        run_prepare=not args.no_prepare,
    )


if __name__ == "__main__":
    main()
