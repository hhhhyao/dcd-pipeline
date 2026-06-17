"""Pipe entrypoints for the NASA HTML image rewrite + image table dedup stage."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_PIPE_DIR = Path(__file__).resolve().parent
if str(_PIPE_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPE_DIR))

from main import parse_args  # noqa: E402
from ops.lance_ops import load_callable  # noqa: E402
from workflow.core import (  # noqa: E402
    DEFAULT_EXTRACTOR,
    DEFAULT_FORMATTER,
    DEFAULT_NORMALIZER,
    DEFAULT_REWRITER,
    PipelineArgs,
    _parse_rows_from_pylist,
    _rewrite_rows,
    run_pipeline,
)

try:
    from dcd_cli.pipe import Batch, MultimodalBatch, PipeContext
except ImportError:  # pragma: no cover - helper-only imports in unit tests
    Batch = dict[str, list[Any]]  # type: ignore[misc,assignment]
    MultimodalBatch = dict[str, dict[str, list[Any]]]  # type: ignore[misc,assignment]
    PipeContext = Any  # type: ignore[misc,assignment]


def _resolve_dataset_root(ctx: PipeContext) -> Path:
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


def _build_args_from_ctx(ctx: PipeContext) -> PipelineArgs:
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


def ingest(ctx: PipeContext) -> Path | None:
    """Pipe entry: rewrite HTML image refs and dedup an existing Lance dataset."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = _build_args_from_ctx(ctx)
    run_pipeline(args, None)
    return Path(str(ctx.output_dir))


def _ctx_config(ctx: PipeContext) -> dict[str, Any]:
    config = getattr(ctx, "config", None)
    if config is None:
        inputs = getattr(ctx, "inputs", None)
        config = getattr(inputs, "config", None) if inputs is not None else None
    return config if isinstance(config, dict) else {}


def _text_batch_from_input(batch: dict[str, Any]) -> tuple[dict[str, list[Any]], bool]:
    text_batch = batch.get("text")
    if isinstance(text_batch, dict):
        return {str(key): list(value) for key, value in text_batch.items()}, True
    return {str(key): list(value) for key, value in batch.items()}, False


def _values_for_row(column: list[Any], row_idx: int) -> list[Any]:
    if row_idx >= len(column):
        return []
    value = column[row_idx]
    if isinstance(value, list):
        return value
    return [value]


def _label_values_for_row(
    column: list[Any],
    row_idx: int,
    *,
    linked_count: int,
    default: Any,
) -> list[Any]:
    if row_idx >= len(column):
        return [default for _ in range(linked_count)]
    value = column[row_idx]
    if not isinstance(value, list):
        return [value for _ in range(linked_count)]
    if linked_count == 1:
        if value and not all(isinstance(item, str) for item in value):
            return value
        return [value]
    if len(value) == linked_count:
        return value
    return [value for _ in range(linked_count)]


def _value_at(values: list[Any], idx: int, default: Any) -> Any:
    return values[idx] if idx < len(values) else default


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    if value in (None, ""):
        return []
    return [str(value)]


def _flatten_linked_image_batch(image_batch: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {
        "id": [],
        "image_bytes": [],
        "info": [],
        "data": [],
        "tags": [],
    }
    if not isinstance(image_batch, dict):
        return out

    ids_col = list(image_batch.get("id") or [])
    bytes_col = list(image_batch.get("image_bytes") or [])
    info_col = list(image_batch.get("info") or [])
    data_col = list(image_batch.get("data") or [])
    tags_col = list(image_batch.get("tags") or [])

    for row_idx in range(len(ids_col)):
        ids = _values_for_row(ids_col, row_idx)
        blobs = _values_for_row(bytes_col, row_idx)
        linked_count = len(ids)
        infos = _label_values_for_row(info_col, row_idx, linked_count=linked_count, default={})
        data_values = _label_values_for_row(data_col, row_idx, linked_count=linked_count, default={})
        tag_values = _label_values_for_row(tags_col, row_idx, linked_count=linked_count, default=[])

        for item_idx, item_id in enumerate(ids):
            blob = _value_at(blobs, item_idx, None)
            if not item_id or not isinstance(blob, (bytes, bytearray)) or not blob:
                continue
            out["id"].append(str(item_id))
            out["image_bytes"].append(bytes(blob))
            out["info"].append(_value_at(infos, item_idx, {}))
            out["data"].append(_value_at(data_values, item_idx, {}))
            out["tags"].append(_normalize_tags(_value_at(tag_values, item_idx, [])))

    return out


def _set_progress(ctx: PipeContext, completed: int, total: int) -> None:
    reporter = getattr(ctx, "reporter", None)
    set_progress = getattr(reporter, "set_progress", None)
    if callable(set_progress):
        set_progress(completed, total, "stage1_html_localize_image_ids")
        return
    set_progress = getattr(ctx, "set_progress", None)
    if callable(set_progress):
        set_progress(completed)


def map(batch: MultimodalBatch, ctx: PipeContext) -> MultimodalBatch:
    """DCD map entry: rewrite text HTML image refs and pass linked images through."""
    config = _ctx_config(ctx)
    text_batch, nested = _text_batch_from_input(batch)
    row_count = len(text_batch.get("id") or [])
    rows = [
        {
            "id": str(text_batch["id"][idx]),
            "info": text_batch.get("info", ["{}"] * row_count)[idx],
            "data": text_batch.get("data", [""] * row_count)[idx],
            "tags": text_batch.get("tags", [[]] * row_count)[idx],
        }
        for idx in range(row_count)
    ]

    parsed_rows, _row_image_ids, _row_image_refs = _parse_rows_from_pylist(rows)
    rewritten_rows, missing_records, warning_records, _counters, _metrics = _rewrite_rows(
        parsed_rows,
        extract_urls=load_callable(str(config.get("extractor", DEFAULT_EXTRACTOR))),
        normalize_url=load_callable(str(config.get("normalizer", DEFAULT_NORMALIZER))),
        format_image_ref=load_callable(str(config.get("formatter", DEFAULT_FORMATTER))),
        rewrite_html=load_callable(str(config.get("rewriter", DEFAULT_REWRITER))),
    )

    for record in missing_records:
        reporter = getattr(ctx, "reporter", None)
        report_error = getattr(reporter, "report_error", None)
        if callable(report_error):
            report_error("text", str(record.get("text_id", "")), str(record))
    for record in warning_records:
        logging.getLogger(__name__).warning("stage1 image warning: %s", record)
    _set_progress(ctx, row_count, row_count)

    text_out = {
        "id": [row["id"] for row in rewritten_rows],
        "data": [row["data"] for row in rewritten_rows],
        "info": [row["info"] for row in rewritten_rows],
        "tags": [row["tags"] for row in rewritten_rows],
    }
    if not nested:
        return text_out  # type: ignore[return-value]

    return {
        "text": text_out,
        "image": _flatten_linked_image_batch(batch.get("image")),
    }


__all__ = ["ingest", "map"]
