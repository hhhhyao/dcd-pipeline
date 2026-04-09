"""Pipe entrypoints for the wiki HTML image rewrite + dataset dedup stage."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

_PIPE_DIR = Path(__file__).resolve().parent
if str(_PIPE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPE_DIR))

from main import parse_args  # noqa: E402
from workflow.core import PipelineArgs, run_pipeline  # noqa: E402

if TYPE_CHECKING:
    from dcd_cli.pipe import PipeContext


def _resolve_dataset_root(ctx: "PipeContext") -> Path:
    dataset_name = str(getattr(ctx, "dataset", "") or "").strip()
    volume_dataset = None
    if getattr(ctx, "volumes", None):
        volume_dataset = ctx.volumes.get("dataset")

    if volume_dataset is not None:
        volume_path = Path(str(volume_dataset))
        if (volume_path / "text.lance").is_dir():
            return volume_path

    if dataset_name:
        named_path = Path("/datasets") / dataset_name
        if (named_path / "text.lance").is_dir():
            return named_path

    if volume_dataset is not None:
        volume_path = Path(str(volume_dataset))
        if volume_path.is_dir():
            return volume_path

    raise ValueError(
        "Input dataset could not be resolved. Expected ctx.volumes['dataset'] "
        "to point to a dataset root or ctx.dataset to resolve under /datasets/<name>.",
    )


def _parse_compact_tables(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        raw = [item.strip() for item in value.split(",")]
        out = [item for item in raw if item]
        return out or None
    if isinstance(value, (list, tuple)):
        out = [str(item).strip() for item in value if str(item).strip()]
        return out or None
    return None


def _build_args_from_ctx(ctx: "PipeContext") -> PipelineArgs:
    config = getattr(ctx, "config", None) or {}
    output_dir = getattr(ctx, "output_dir", None)
    if output_dir is None:
        raise ValueError("ctx.output_dir is required for this pipe.")

    defaults = parse_args([])
    batch_size = int(config.get("batch_size", defaults.batch_size))
    write_flush_rows = int(config.get("write_flush_rows", defaults.write_flush_rows))
    progress_every = int(config.get("progress_every", defaults.progress_every))
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    if write_flush_rows <= 0:
        raise ValueError("write_flush_rows must be > 0")
    if progress_every < 0:
        raise ValueError("progress_every must be >= 0")

    return PipelineArgs(
        input_dir=str(_resolve_dataset_root(ctx)),
        output_dir=str(output_dir),
        text_db_name=str(config.get("text_db_name", defaults.text_db_name)),
        images_db_name=str(config.get("images_db_name", defaults.images_db_name)),
        image_labels_db_name=str(
            config.get("image_labels_db_name", defaults.image_labels_db_name),
        ),
        cache_dir=str(config["cache_dir"]) if config.get("cache_dir") else None,
        batch_size=batch_size,
        write_flush_rows=write_flush_rows,
        progress_every=progress_every,
        extractor=str(config.get("extractor", defaults.extractor)),
        normalizer=str(config.get("normalizer", defaults.normalizer)),
        formatter=str(config.get("formatter", defaults.formatter)),
        rewriter=str(config.get("rewriter", defaults.rewriter)),
        compact_tables=_parse_compact_tables(
            config.get("compact_tables", defaults.compact_tables),
        ),
        overwrite=bool(config.get("overwrite", defaults.overwrite)),
    )


def ingest(ctx: "PipeContext") -> Path | None:
    """Pipe entry: rewrite HTML image refs and dedup an existing Lance dataset."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _build_args_from_ctx(ctx)
    run_pipeline(args, None)
    return Path(str(ctx.output_dir))


__all__ = ["ingest"]
