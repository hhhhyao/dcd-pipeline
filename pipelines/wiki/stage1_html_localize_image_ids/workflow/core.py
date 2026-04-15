"""Main production pipeline orchestration."""

from __future__ import annotations

import json
import logging
import shlex
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import lance

from ops.cache_io import JsonlShardWriter, cleanup_generated_cache_artifacts
from ops.lance_ops import (
    LanceDatasetWriter,
    StageProgress,
    compact_selected_tables,
    create_absolute_symlink,
    iter_batches,
    load_callable,
    load_order_cache,
    load_rowids_cache,
    normalize_compact_tables,
    prepare_output_dir,
    scan_image_label_caches,
)
from workflow.dedup import dedup_image_labels_dataset
from workflow.html_rewrite import (
    RewriterFn,
    build_html_rewrite_plan,
    build_local_url_map,
    dedupe_preserve_order,
    json_dumps,
    parse_image_ref_id,
)
from workflow.metadata import (
    discover_repo_metadata,
    discover_runtime_user,
    write_dataset_yaml,
    write_run_info_yaml,
)


LOG = logging.getLogger(__name__)

DEFAULT_INPUT_DIR = "/mnt-c526/lancedb/html/wiki_20260324_zh_fig_backfill"
DEFAULT_OUTPUT_DIR = "/cache/wiki_20260324_zh_fig_html_replace_image_url_and_dedup_id"
DEFAULT_TEXT_DB_NAME = "text.lance"
DEFAULT_IMAGES_DB_NAME = "images.lance"
DEFAULT_IMAGE_LABELS_DB_NAME = "image_labels.lance"
DEFAULT_BATCH_SIZE = 1024
DEFAULT_WRITE_FLUSH_ROWS = 8192
DEFAULT_PROGRESS_EVERY = 5000
DEFAULT_EXTRACTOR = "plugins.wikimedia_production:extract_img_urls_from_html"
DEFAULT_NORMALIZER = "plugins.wikimedia_production:normalize_image_url"
DEFAULT_FORMATTER = "plugins.wikimedia_production:format_image_ref"
DEFAULT_REWRITER = "plugins.wikimedia_production:rewrite_html"
DEFAULT_IMAGE_LABELS_IMAGE_ID_ROWIDS_CACHE_NAME = "image_labels_image_id_rowids.arrow"
DEFAULT_IMAGE_LABELS_IMAGE_ID_ORDER_CACHE_NAME = "image_labels_image_id_order.arrow"
DEFAULT_MISSING_JSONL_NAME = "image_url_missing.jsonl"
DEFAULT_WARNING_JSONL_NAME = "image_id_unmatched_warning.jsonl"


ExtractorFn = Callable[[str], list[str]]
NormalizerFn = Callable[[str], str]
FormatterFn = Callable[..., Any]


@dataclass
class PipelineArgs:
    input_dir: str
    output_dir: str
    text_db_name: str
    images_db_name: str
    image_labels_db_name: str
    cache_dir: str | None
    batch_size: int
    write_flush_rows: int
    progress_every: int
    extractor: str
    normalizer: str
    formatter: str
    rewriter: str
    compact_tables: list[str] | None
    overwrite: bool


def _parse_info(info_raw: str) -> dict[str, Any]:
    try:
        info = json.loads(info_raw or "{}")
    except json.JSONDecodeError:
        info = {}
    return info if isinstance(info, dict) else {}


def _make_metric_bucket() -> dict[str, float]:
    return {"seconds": 0.0}


def _record_metric(metrics: dict[str, dict[str, float]], key: str, seconds: float) -> None:
    metrics.setdefault(key, _make_metric_bucket())
    metrics[key]["seconds"] += seconds


def _parse_image_refs(info: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    raw_image_refs = info.get("image_refs") or {}
    warnings: list[dict[str, Any]] = []
    if isinstance(raw_image_refs, str):
        try:
            raw_image_refs = json.loads(raw_image_refs or "{}")
        except json.JSONDecodeError:
            raw_image_refs = {}
            warnings.append({
                "type": "invalid_image_refs_json",
                "error_message": "info.image_refs is not valid JSON.",
            })
    if not isinstance(raw_image_refs, dict):
        warnings.append({
            "type": "invalid_image_refs_type",
            "error_message": "info.image_refs is missing or is not a dict.",
        })
        return {}, warnings

    image_refs: dict[str, dict[str, Any]] = {}
    for image_ref_id, ref_info in raw_image_refs.items():
        if not isinstance(image_ref_id, str) or not image_ref_id:
            warnings.append({
                "type": "invalid_image_ref_id",
                "image_ref_id": str(image_ref_id),
                "error_message": "image_ref_id must be a non-empty string.",
            })
            continue
        if parse_image_ref_id(image_ref_id) is None:
            warnings.append({
                "type": "invalid_image_ref_id",
                "image_ref_id": image_ref_id,
                "error_message": "image_ref_id must be formatted as <image_id>_<image_url_ori_hash>.",
            })
            continue
        if not isinstance(ref_info, dict):
            warnings.append({
                "type": "invalid_image_ref_info",
                "image_ref_id": image_ref_id,
                "error_message": "image_refs value must be a dict.",
            })
            continue
        image_refs[image_ref_id] = ref_info
    return image_refs, warnings


def _parse_rows_from_pylist(batch_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    parsed_rows: list[dict[str, Any]] = []
    row_image_ids = 0
    row_image_refs = 0
    for row in batch_rows:
        info = _parse_info(str(row.get("info") or "{}"))
        image_ids = dedupe_preserve_order(str(item) for item in (info.get("image_ids") or []) if item)
        image_refs, ref_warnings = _parse_image_refs(info)
        parsed_rows.append({
            "id": str(row["id"]),
            "info": info,
            "data": str(row.get("data") or ""),
            "tags": row.get("tags") or [],
            "image_ids": image_ids,
            "image_refs": image_refs,
            "ref_warnings": ref_warnings,
        })
        row_image_ids += len(image_ids)
        row_image_refs += len(image_refs)
    return parsed_rows, row_image_ids, row_image_refs


def _rewrite_rows(
    parsed_rows: list[dict[str, Any]],
    *,
    extract_urls: ExtractorFn,
    normalize_url: NormalizerFn,
    format_image_ref: FormatterFn,
    rewrite_html: RewriterFn,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int], dict[str, float]]:
    output_rows: list[dict[str, Any]] = []
    missing_records: list[dict[str, Any]] = []
    warning_records: list[dict[str, Any]] = []
    counters = {
        "rewritten_rows": 0,
        "rewritten_images": 0,
        "missing_urls": 0,
        "unmatched_image_refs": 0,
        "html_urls": 0,
    }
    metrics = {
        "build_local_url_map_seconds": 0.0,
        "extract_html_urls_seconds": 0.0,
        "build_html_rewrite_plan_seconds": 0.0,
        "apply_html_rewrite_seconds": 0.0,
    }
    for row in parsed_rows:
        row_t0 = time.perf_counter()
        normalized_to_ref, raw_urls_by_ref_id, normalized_urls_by_ref_id = build_local_url_map(
            row["image_refs"],
            normalize_url,
        )
        metrics["build_local_url_map_seconds"] += time.perf_counter() - row_t0

        row_t0 = time.perf_counter()
        raw_html_urls = extract_urls(row["data"])
        metrics["extract_html_urls_seconds"] += time.perf_counter() - row_t0
        counters["html_urls"] += len(raw_html_urls)

        row_t0 = time.perf_counter()
        rewrite_plan = build_html_rewrite_plan(
            row["data"],
            extract_urls=lambda _html, urls=raw_html_urls: urls,
            normalize_url=normalize_url,
            format_image_ref=format_image_ref,
            normalized_to_ref=normalized_to_ref,
        )
        metrics["build_html_rewrite_plan_seconds"] += time.perf_counter() - row_t0

        row_t0 = time.perf_counter()
        rewritten_html = rewrite_html(row["data"], rewrite_plan["replacements_by_raw_url"])
        metrics["apply_html_rewrite_seconds"] += time.perf_counter() - row_t0

        missing_urls = rewrite_plan["missing_urls"]
        matched_normalized_urls = rewrite_plan["matched_normalized_urls"]
        used_image_ids = rewrite_plan["used_image_ids"]
        if rewritten_html != row["data"]:
            counters["rewritten_rows"] += 1
        counters["rewritten_images"] += len(used_image_ids)

        html_url = str(row["info"].get("url") or row["info"].get("final_url") or "")
        for missing in missing_urls:
            counters["missing_urls"] += 1
            missing_records.append({
                "text_id": row["id"],
                "html_url": html_url,
                **missing,
            })

        for ref_warning in row["ref_warnings"]:
            counters["unmatched_image_refs"] += 1
            warning_records.append({
                "text_id": row["id"],
                "html_url": html_url,
                **ref_warning,
            })

        for image_ref_id, _ref_info in row["image_refs"].items():
            parsed_ref = parse_image_ref_id(image_ref_id)
            if parsed_ref is None:
                continue
            image_id, _ = parsed_ref
            candidate_norms = normalized_urls_by_ref_id.get(image_ref_id, [])
            if not candidate_norms:
                counters["unmatched_image_refs"] += 1
                warning_records.append({
                    "type": "image_ref_id_no_candidate_urls",
                    "text_id": row["id"],
                    "html_url": html_url,
                    "image_ref_id": image_ref_id,
                    "image_id": image_id,
                    "candidate_urls_raw": raw_urls_by_ref_id.get(image_ref_id, []),
                    "candidate_urls_normalized": candidate_norms,
                })
                LOG.warning("text_id=%s image_ref_id=%s has no candidate image_ref URLs", row["id"], image_ref_id)
                continue
            if not any(norm in matched_normalized_urls for norm in candidate_norms):
                counters["unmatched_image_refs"] += 1
                warning_records.append({
                    "type": "image_ref_id_not_matched_to_html_url",
                    "text_id": row["id"],
                    "html_url": html_url,
                    "image_ref_id": image_ref_id,
                    "image_id": image_id,
                    "candidate_urls_raw": raw_urls_by_ref_id.get(image_ref_id, []),
                    "candidate_urls_normalized": candidate_norms,
                })
                LOG.warning("text_id=%s image_ref_id=%s did not match any HTML image URL", row["id"], image_ref_id)

        row["info"]["image_ids"] = dedupe_preserve_order(used_image_ids)
        row["info"]["image_refs"] = row["image_refs"]
        output_rows.append({
            "id": row["id"],
            "info": json_dumps(row["info"]),
            "data": rewritten_html,
            "tags": row["tags"],
        })
    return output_rows, missing_records, warning_records, counters, metrics


def rewrite_text_dataset(
    text_path: Path,
    text_output_path: Path,
    *,
    extract_urls: ExtractorFn,
    normalize_url: NormalizerFn,
    format_image_ref: FormatterFn,
    rewrite_html: RewriterFn,
    batch_size: int,
    write_flush_rows: int,
    progress_every: int,
    missing_writer: JsonlShardWriter,
    warning_writer: JsonlShardWriter,
    temp_dir: Path,
) -> dict[str, Any]:
    """Rewrite HTML image URLs in text.lance."""
    del write_flush_rows
    text_ds = lance.dataset(str(text_path))
    schema = text_ds.schema
    counters = {
        "rows": 0,
        "rewritten_rows": 0,
        "rewritten_images": 0,
        "missing_urls": 0,
        "unmatched_image_refs": 0,
    }
    profile_metrics: dict[str, dict[str, float]] = {
        "batch_to_pylist_seconds": _make_metric_bucket(),
        "parse_text_rows_seconds": _make_metric_bucket(),
        "build_local_url_map_seconds": _make_metric_bucket(),
        "extract_html_urls_seconds": _make_metric_bucket(),
        "build_html_rewrite_plan_seconds": _make_metric_bucket(),
        "apply_html_rewrite_seconds": _make_metric_bucket(),
        "emit_warning_records_seconds": _make_metric_bucket(),
        "append_text_output_seconds": _make_metric_bucket(),
        "finalize_text_output_seconds": _make_metric_bucket(),
    }
    profile_totals = {
        "batches": 0,
        "row_image_ids": 0,
        "row_image_refs": 0,
        "html_urls": 0,
        "missing_records": 0,
        "warning_records": 0,
    }
    progress = StageProgress(
        name="text_rewrite",
        total_rows=int(text_ds.count_rows()),
        progress_every=progress_every,
        counters=counters,
    )
    writer = LanceDatasetWriter(text_output_path, schema, temp_dir=temp_dir)
    scanner = text_ds.scanner(
        columns=["id", "info", "data", "tags"],
        batch_size=batch_size,
        batch_readahead=1,
        fragment_readahead=1,
        scan_in_order=True,
    )
    for batch in iter_batches(scanner, batch_size):
        profile_totals["batches"] += 1
        load_t0 = time.perf_counter()
        batch_rows = batch.to_pylist()
        _record_metric(profile_metrics, "batch_to_pylist_seconds", time.perf_counter() - load_t0)
        parse_t0 = time.perf_counter()
        parsed_rows, row_image_ids, row_image_refs = _parse_rows_from_pylist(batch_rows)
        profile_totals["row_image_ids"] += row_image_ids
        profile_totals["row_image_refs"] += row_image_refs
        _record_metric(profile_metrics, "parse_text_rows_seconds", time.perf_counter() - parse_t0)

        rewritten_rows, missing_records, warning_records, row_counts, row_metrics = _rewrite_rows(
            parsed_rows,
            extract_urls=extract_urls,
            normalize_url=normalize_url,
            format_image_ref=format_image_ref,
            rewrite_html=rewrite_html,
        )
        counters["rows"] += len(parsed_rows)
        counters["rewritten_rows"] += int(row_counts["rewritten_rows"])
        counters["rewritten_images"] += int(row_counts["rewritten_images"])
        counters["missing_urls"] += int(row_counts["missing_urls"])
        counters["unmatched_image_refs"] += int(row_counts["unmatched_image_refs"])
        profile_totals["html_urls"] += int(row_counts["html_urls"])
        profile_totals["missing_records"] += len(missing_records)
        profile_totals["warning_records"] += len(warning_records)
        for _ in parsed_rows:
            progress.advance()
        for metric_key, metric_value in row_metrics.items():
            _record_metric(profile_metrics, metric_key, metric_value)

        emit_t0 = time.perf_counter()
        for record in missing_records:
            missing_writer.write(record)
        for record in warning_records:
            warning_writer.write(record)
        _record_metric(profile_metrics, "emit_warning_records_seconds", time.perf_counter() - emit_t0)

        write_t0 = time.perf_counter()
        writer.write_rows(rewritten_rows)
        _record_metric(profile_metrics, "append_text_output_seconds", time.perf_counter() - write_t0)

    finalize_t0 = time.perf_counter()
    writer.finalize()
    _record_metric(profile_metrics, "finalize_text_output_seconds", time.perf_counter() - finalize_t0)
    progress.report(final=True)
    return {**counters, "profile": {"metrics": profile_metrics, "totals": profile_totals}}


def run_pipeline(args: PipelineArgs, argv: Sequence[str] | None = None) -> dict[str, Any]:
    """Run the full rewrite + dedup + compact pipeline."""
    extract_urls = load_callable(args.extractor)
    normalize_url = load_callable(args.normalizer)
    format_image_ref = load_callable(args.formatter)
    rewrite_html = load_callable(args.rewriter)

    input_dir = Path(args.input_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    cache_dir = Path(args.cache_dir).expanduser().resolve() if args.cache_dir else output_dir / "cache"
    tmp_dir = output_dir / "tmp"
    text_source_path = input_dir / args.text_db_name
    images_source_path = input_dir / args.images_db_name
    image_labels_source_path = input_dir / args.image_labels_db_name
    text_output_path = output_dir / args.text_db_name
    images_output_path = output_dir / args.images_db_name
    image_labels_output_path = output_dir / args.image_labels_db_name
    image_labels_rowids_cache_path = cache_dir / DEFAULT_IMAGE_LABELS_IMAGE_ID_ROWIDS_CACHE_NAME
    image_labels_order_cache_path = cache_dir / DEFAULT_IMAGE_LABELS_IMAGE_ID_ORDER_CACHE_NAME
    missing_jsonl_path = output_dir / DEFAULT_MISSING_JSONL_NAME
    warning_jsonl_path = output_dir / DEFAULT_WARNING_JSONL_NAME
    compact_tables = normalize_compact_tables(args.compact_tables)

    for path in (text_source_path, images_source_path, image_labels_source_path):
        if not path.exists():
            raise FileNotFoundError(f"Dataset path not found: {path}")

    prepare_output_dir(output_dir, args.overwrite)
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    timings = {
        "rewrite_text_seconds": 0.0,
        "link_images_seconds": 0.0,
        "scan_image_labels_cache_seconds": 0.0,
        "dedup_image_labels_seconds": 0.0,
        "finalize_outputs_seconds": 0.0,
        "compact_seconds": 0.0,
        "write_metadata_seconds": 0.0,
        "cleanup_cache_seconds": 0.0,
        "total_seconds": 0.0,
    }
    total_t0 = time.perf_counter()

    missing_writer = JsonlShardWriter(cache_dir, "missing", flush_rows=args.write_flush_rows)
    warning_writer = JsonlShardWriter(cache_dir, "warnings", flush_rows=args.write_flush_rows)

    stage_t0 = time.perf_counter()
    text_stats = rewrite_text_dataset(
        text_source_path,
        text_output_path,
        extract_urls=extract_urls,
        normalize_url=normalize_url,
        format_image_ref=format_image_ref,
        rewrite_html=rewrite_html,
        batch_size=args.batch_size,
        write_flush_rows=args.write_flush_rows,
        progress_every=args.progress_every,
        missing_writer=missing_writer,
        warning_writer=warning_writer,
        temp_dir=tmp_dir,
    )
    timings["rewrite_text_seconds"] = time.perf_counter() - stage_t0

    stage_t0 = time.perf_counter()
    create_absolute_symlink(images_source_path, images_output_path)
    timings["link_images_seconds"] = time.perf_counter() - stage_t0
    image_stats = {
        "mode": "symlink",
        "linked": 1,
        "source_rows": int(lance.dataset(str(images_source_path)).count_rows()),
    }

    stage_t0 = time.perf_counter()
    image_labels_cache_stats = scan_image_label_caches(
        image_labels_source_path,
        rowids_cache_path=image_labels_rowids_cache_path,
        order_cache_path=image_labels_order_cache_path,
        batch_size=args.batch_size,
        progress_every=args.progress_every,
    )
    timings["scan_image_labels_cache_seconds"] = time.perf_counter() - stage_t0
    row_ids_by_image_id = load_rowids_cache(image_labels_rowids_cache_path)
    ordered_image_ids = [str(row["image_id"]) for row in load_order_cache(image_labels_order_cache_path)]

    stage_t0 = time.perf_counter()
    image_label_stats = dedup_image_labels_dataset(
        image_labels_source_path,
        image_labels_output_path,
        row_ids_by_image_id=row_ids_by_image_id,
        ordered_image_ids=ordered_image_ids,
        batch_size=args.batch_size,
        write_flush_rows=args.write_flush_rows,
        progress_every=args.progress_every,
        warning_writer=warning_writer,
        temp_dir=tmp_dir,
    )
    timings["dedup_image_labels_seconds"] = time.perf_counter() - stage_t0

    stage_t0 = time.perf_counter()
    missing_count = missing_writer.finalize(missing_jsonl_path)
    warning_count = warning_writer.finalize(warning_jsonl_path)
    timings["finalize_outputs_seconds"] = time.perf_counter() - stage_t0

    stage_t0 = time.perf_counter()
    compact_stats = compact_selected_tables(output_dir, compact_tables)
    timings["compact_seconds"] = time.perf_counter() - stage_t0

    stage_t0 = time.perf_counter()
    repo_metadata = discover_repo_metadata(Path(__file__).resolve())
    command = shlex.join([
        sys.executable,
        str((Path(__file__).resolve().parents[1] / "main.py").resolve()),
        *(argv or sys.argv[1:]),
    ])
    owner = discover_runtime_user()
    text_ds = lance.dataset(str(text_output_path))
    images_ds = lance.dataset(str(images_output_path))
    image_labels_ds = lance.dataset(str(image_labels_output_path))
    write_dataset_yaml(
        output_dir / "dataset.yaml",
        dataset_name=output_dir.name,
        description=f"Dataset with inline text image-ref rewrite, linked images table, and deduplicated image labels for {input_dir.name}.",
        owner=owner,
        source_dataset_name=input_dir.name,
        text_rows=int(text_ds.count_rows()),
        text_fields=list(text_ds.schema.names),
        image_rows=int(images_ds.count_rows()),
        image_fields=list(images_ds.schema.names),
        image_label_rows=int(image_labels_ds.count_rows()),
        image_label_fields=list(image_labels_ds.schema.names),
        source_root=input_dir,
        text_source_path=text_source_path,
        images_source_path=images_source_path,
        image_labels_source_path=image_labels_source_path,
        output_dir=output_dir,
        missing_jsonl_path=missing_jsonl_path,
        warning_jsonl_path=warning_jsonl_path,
        command=command,
        extractor_spec=args.extractor,
        normalizer_spec=args.normalizer,
        formatter_spec=args.formatter,
        rewriter_spec=args.rewriter,
        repo_metadata=repo_metadata,
    )
    timings["write_metadata_seconds"] = time.perf_counter() - stage_t0

    stage_t0 = time.perf_counter()
    cache_cleanup_stats = cleanup_generated_cache_artifacts(
        cache_dir,
        cache_paths=[
            image_labels_rowids_cache_path,
            image_labels_order_cache_path,
        ],
        jsonl_shard_stems=[missing_writer.stem, warning_writer.stem],
    )
    timings["cleanup_cache_seconds"] = time.perf_counter() - stage_t0
    timings["total_seconds"] = time.perf_counter() - total_t0
    write_run_info_yaml(
        output_dir / "run_info.yaml",
        source_root=input_dir,
        text_source_path=text_source_path,
        images_source_path=images_source_path,
        image_labels_source_path=image_labels_source_path,
        output_dir=output_dir,
        text_output_path=text_output_path,
        images_output_path=images_output_path,
        image_labels_output_path=image_labels_output_path,
        missing_jsonl_path=missing_jsonl_path,
        warning_jsonl_path=warning_jsonl_path,
        command=command,
        extractor_spec=args.extractor,
        normalizer_spec=args.normalizer,
        formatter_spec=args.formatter,
        rewriter_spec=args.rewriter,
        compact_tables=compact_tables,
        repo_metadata=repo_metadata,
        timings=timings,
    )

    LOG.info(
        "Stage timing summary: rewrite=%.3fs link_images=%.3fs "
        "scan_labels=%.3fs dedup_labels=%.3fs compact=%.3fs cleanup=%.3fs total=%.3fs",
        timings["rewrite_text_seconds"],
        timings["link_images_seconds"],
        timings["scan_image_labels_cache_seconds"],
        timings["dedup_image_labels_seconds"],
        timings["compact_seconds"],
        timings["cleanup_cache_seconds"],
        timings["total_seconds"],
    )
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return {
        "image_labels_cache_stats": image_labels_cache_stats,
        "text_stats": text_stats,
        "image_stats": image_stats,
        "image_label_stats": image_label_stats,
        "compact_stats": compact_stats,
        "missing_writer_stats": missing_writer.snapshot(),
        "warning_writer_stats": warning_writer.snapshot(),
        "missing_count": missing_count,
        "warning_count": warning_count,
        "compact_tables": compact_tables,
        "cache_cleanup_stats": cache_cleanup_stats,
        "timings": timings,
    }
