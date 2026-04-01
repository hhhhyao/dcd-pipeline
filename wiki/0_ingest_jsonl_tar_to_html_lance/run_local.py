#!/usr/bin/env python3
"""Run the raw wiki jsonl+tar -> html Lance ingest stage locally."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _bootstrap_paths() -> Path:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    for dcd_cli_root in (root / "refer_repo" / "dcd-cli", root.parent / "dcd-cli"):
        if dcd_cli_root.is_dir() and str(dcd_cli_root) not in sys.path:
            sys.path.insert(0, str(dcd_cli_root))
            break
    return root


ROOT = _bootstrap_paths()

from wiki._module_loader import load_pipe_package  # noqa: E402

INGEST_MODULE = load_pipe_package(
    Path(__file__).resolve().parent,
    alias="0_ingest_jsonl_tar_to_html_lance_pkg",
)
ingest = INGEST_MODULE.ingest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run 0_ingest_jsonl_tar_to_html_lance locally",
    )
    parser.add_argument(
        "src_dir",
        nargs="?",
        type=Path,
        default=ROOT / "workspace" / "source" / "wiki_0320_en_has_pic",
    )
    parser.add_argument(
        "dst_dir",
        nargs="?",
        type=Path,
        default=ROOT / "workspace" / "html_lance" / "wiki_0320_en_has_pic_v2_raw",
    )
    parser.add_argument("--log-interval", type=int, default=250)
    args = parser.parse_args()

    from dcd_cli.pipe import PipeContext

    src_dir = args.src_dir.resolve()
    dst_dir = args.dst_dir.resolve()
    dst_dir.mkdir(parents=True, exist_ok=True)

    ctx = PipeContext(
        dataset=dst_dir.name,
        pipe_name="stage0_ingest_jsonl_tar_to_html_lance",
        pipe_version=1,
        output_dir=dst_dir,
        config={
            "source_dir": str(src_dir),
            "log_interval": max(1, args.log_interval),
        },
    )
    ingest(ctx)


if __name__ == "__main__":
    main()
