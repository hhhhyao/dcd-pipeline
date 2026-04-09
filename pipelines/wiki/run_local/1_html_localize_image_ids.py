#!/usr/bin/env python3
"""Run stage1_html_localize_image_ids locally on a Lance dataset."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


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
import pipelines.wiki.stage1_html_localize_image_ids as PIPE_MODULE  # noqa: E402

PIPE_NAME = "stage1_html_localize_image_ids"

def run(
    src_dataset_dir: Path,
    dst_dataset_dir: Path,
    *,
    batch_size: int = 1024,
    write_flush_rows: int = 8192,
    progress_every: int = 5000,
    compact_tables: str = "text,image_labels,images",
    run_prepare: bool = True,
) -> None:
    if not (src_dataset_dir / "text.lance").is_dir():
        raise FileNotFoundError(f"Source text.lance not found: {src_dataset_dir / 'text.lance'}")

    dst_dataset_dir.mkdir(parents=True, exist_ok=True)
    ctx = PipeContext(
        dataset=src_dataset_dir.name,
        pipe_name=PIPE_NAME,
        pipe_version=1,
        config={
            "batch_size": batch_size,
            "write_flush_rows": write_flush_rows,
            "progress_every": progress_every,
            "compact_tables": compact_tables,
            "overwrite": True,
        },
        volumes={"dataset": src_dataset_dir},
        output_dir=dst_dataset_dir,
    )

    print(f"source: {src_dataset_dir}")
    print(f"target: {dst_dataset_dir}")
    print(
        "config: "
        f"batch_size={batch_size}, "
        f"write_flush_rows={write_flush_rows}, "
        f"progress_every={progress_every}, "
        f"compact_tables={compact_tables}",
    )

    t0 = time.time()
    PIPE_MODULE.ingest(ctx)

    if run_prepare:
        from dataclawdev.data.util.prepare_dataset import run as prepare_dataset_run

        print("prepare_dataset: start (tokenizer=simple)")
        prepare_dataset_run(dst_dataset_dir, base_tokenizer="simple")
        print("prepare_dataset: done")

    print(f"done in {time.time() - t0:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Run {PIPE_NAME} locally",
    )
    parser.add_argument(
        "src_dataset_dir",
        nargs="?",
        type=Path,
        default=ROOT / "workspace" / "html_lance" / "wiki_0320_en_has_pic_v2_raw",
    )
    parser.add_argument(
        "dst_dataset_dir",
        nargs="?",
        type=Path,
        default=ROOT / "workspace" / "html_lance" / "wiki_0320_en_has_pic_v2_localized_tmp",
    )
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--write-flush-rows", type=int, default=8192)
    parser.add_argument("--progress-every", type=int, default=5000)
    parser.add_argument("--compact-tables", default="text,image_labels,images")
    parser.add_argument("--no-prepare", action="store_true")
    args = parser.parse_args()

    run(
        args.src_dataset_dir.resolve(),
        args.dst_dataset_dir.resolve(),
        batch_size=max(1, args.batch_size),
        write_flush_rows=max(1, args.write_flush_rows),
        progress_every=max(0, args.progress_every),
        compact_tables=args.compact_tables,
        run_prepare=not args.no_prepare,
    )


if __name__ == "__main__":
    main()
