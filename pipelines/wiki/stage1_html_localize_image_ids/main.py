#!/usr/bin/env python3
"""Rewrite wiki HTML image URLs and deduplicate image tables in a Lance dataset."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Sequence

_PIPE_DIR = Path(__file__).resolve().parent
if str(_PIPE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPE_DIR))

from workflow.core import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    DEFAULT_EXTRACTOR,
    DEFAULT_FORMATTER,
    DEFAULT_IMAGE_LABELS_DB_NAME,
    DEFAULT_IMAGES_DB_NAME,
    DEFAULT_INPUT_DIR,
    DEFAULT_NORMALIZER,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_PROGRESS_EVERY,
    DEFAULT_REWRITER,
    DEFAULT_TEXT_DB_NAME,
    DEFAULT_WRITE_FLUSH_ROWS,
    PipelineArgs,
    run_pipeline,
)


def parse_args(argv: Sequence[str] | None = None) -> PipelineArgs:
    """Parse CLI arguments into a typed pipeline args object."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--text-db-name", default=DEFAULT_TEXT_DB_NAME)
    parser.add_argument("--images-db-name", default=DEFAULT_IMAGES_DB_NAME)
    parser.add_argument("--image-labels-db-name", default=DEFAULT_IMAGE_LABELS_DB_NAME)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--write-flush-rows", type=int, default=DEFAULT_WRITE_FLUSH_ROWS)
    parser.add_argument("--progress-every", type=int, default=DEFAULT_PROGRESS_EVERY)
    parser.add_argument("--extractor", default=DEFAULT_EXTRACTOR)
    parser.add_argument("--normalizer", default=DEFAULT_NORMALIZER)
    parser.add_argument("--formatter", default=DEFAULT_FORMATTER)
    parser.add_argument("--rewriter", default=DEFAULT_REWRITER)
    parser.add_argument(
        "--compact-tables",
        nargs="*",
        default=None,
        choices=("text", "image_labels", "images"),
    )
    parser.add_argument("--overwrite", action="store_true")
    ns = parser.parse_args(argv)
    if ns.batch_size <= 0:
        raise ValueError("--batch-size must be > 0")
    if ns.write_flush_rows <= 0:
        raise ValueError("--write-flush-rows must be > 0")
    if ns.progress_every < 0:
        raise ValueError("--progress-every must be >= 0")
    return PipelineArgs(
        input_dir=ns.input_dir,
        output_dir=ns.output_dir,
        text_db_name=ns.text_db_name,
        images_db_name=ns.images_db_name,
        image_labels_db_name=ns.image_labels_db_name,
        cache_dir=ns.cache_dir,
        batch_size=ns.batch_size,
        write_flush_rows=ns.write_flush_rows,
        progress_every=ns.progress_every,
        extractor=ns.extractor,
        normalizer=ns.normalizer,
        formatter=ns.formatter,
        rewriter=ns.rewriter,
        compact_tables=ns.compact_tables,
        overwrite=ns.overwrite,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = parse_args(argv)
    result = run_pipeline(args, argv)
    logging.getLogger(__name__).info(
        "Done. missing_urls=%s warnings=%s compact_tables=%s timings=%s",
        f"{result['missing_count']:,}",
        f"{result['warning_count']:,}",
        ",".join(result["compact_tables"]),
        result["timings"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
