"""Dedup logic for images.lance and image_labels.lance."""

from __future__ import annotations

import json
from typing import Any

import lance

from ops.lance_ops import (
    StageProgress,
    append_rows_to_lance_dataset,
    iter_batches,
    make_scanner,
)
from workflow.html_rewrite import dedupe_preserve_order, json_dumps


def _canonical_info_json(info: dict[str, Any]) -> str:
    sanitized = dict(info)
    sanitized.pop("info_addtional", None)
    return json.dumps(sanitized, ensure_ascii=False, sort_keys=True)


def dedup_images_dataset(
    source_path,
    output_path,
    *,
    first_row_id_by_image_id: dict[str, int],
    batch_size: int,
    write_flush_rows: int,
    progress_every: int,
    warning_writer,
) -> dict[str, int]:
    """Deduplicate images.lance by keeping the first row for each image ID."""
    ds = lance.dataset(str(source_path))
    schema = ds.schema
    counters = {
        "rows": 0,
        "kept_rows": 0,
        "duplicate_rows": 0,
        "sha256_conflicts": 0,
    }
    progress = StageProgress(
        name="images_dedup",
        total_rows=int(ds.count_rows()),
        progress_every=progress_every,
        counters=counters,
    )
    scanner = make_scanner(ds, columns=["id", "image_bytes", "sha256"], batch_size=batch_size)
    pending_rows: list[dict[str, Any]] = []
    first_sha256_by_id: dict[str, str] = {}
    fallback_first_row_id_by_image_id: dict[str, int] = {}
    next_position = 0
    for batch in iter_batches(scanner, batch_size):
        ids = batch.column("id").to_pylist()
        image_bytes_list = batch.column("image_bytes").to_pylist()
        sha256_list = batch.column("sha256").to_pylist()
        row_positions = range(next_position, next_position + len(ids))
        next_position += len(ids)
        for row_id, image_id, image_bytes, sha256 in zip(row_positions, ids, image_bytes_list, sha256_list, strict=True):
            counters["rows"] += 1
            progress.advance()
            image_id = str(image_id)
            sha256 = str(sha256 or "")
            first_sha = first_sha256_by_id.setdefault(image_id, sha256)
            target_first_row_id = first_row_id_by_image_id.get(image_id)
            if target_first_row_id is None:
                target_first_row_id = fallback_first_row_id_by_image_id.setdefault(image_id, int(row_id))
            if int(row_id) != int(target_first_row_id):
                counters["duplicate_rows"] += 1
                if first_sha != sha256:
                    counters["sha256_conflicts"] += 1
                    warning_writer.write({
                        "type": "images_sha256_conflict",
                        "image_id": image_id,
                        "first_sha256": first_sha,
                        "duplicate_sha256": sha256,
                    })
                continue
            counters["kept_rows"] += 1
            pending_rows.append({
                "id": image_id,
                "image_bytes": image_bytes,
                "sha256": sha256,
            })
            if len(pending_rows) >= write_flush_rows:
                append_rows_to_lance_dataset(pending_rows, schema, output_path)
                pending_rows = []
    if pending_rows:
        append_rows_to_lance_dataset(pending_rows, schema, output_path)
    progress.report(final=True)
    return counters


def dedup_image_labels_dataset(
    source_path,
    output_path,
    *,
    row_ids_by_image_id: dict[str, list[int]],
    ordered_image_ids: list[str],
    batch_size: int,
    write_flush_rows: int,
    progress_every: int,
    warning_writer,
) -> dict[str, int]:
    """Deduplicate image_labels.lance while merging info and tags."""
    ds = lance.dataset(str(source_path))
    schema = ds.schema
    counters = {
        "rows": int(ds.count_rows()),
        "unique_image_ids": len(ordered_image_ids),
        "duplicate_rows": 0,
        "info_conflicts": 0,
        "data_conflicts": 0,
    }
    progress = StageProgress(
        name="image_labels_dedup",
        total_rows=len(ordered_image_ids),
        progress_every=progress_every,
        counters=counters,
    )
    pending_rows: list[dict[str, Any]] = []

    # Current datasets keep ``data`` empty. We keep the first value and only warn
    # if future inputs ever introduce conflicting non-empty variants.
    for start in range(0, len(ordered_image_ids), batch_size):
        image_id_chunk = ordered_image_ids[start:start + batch_size]
        group_rows_by_image_id: dict[str, list[dict[str, Any]]] = {}
        flat_row_ids: list[int] = []
        group_sizes: list[tuple[str, int]] = []
        for image_id in image_id_chunk:
            row_ids = [int(row_id) for row_id in row_ids_by_image_id.get(image_id, [])]
            group_rows_by_image_id[image_id] = []
            if not row_ids:
                continue
            flat_row_ids.extend(row_ids)
            group_sizes.append((image_id, len(row_ids)))

        if flat_row_ids:
            taken_rows = ds.take(flat_row_ids, columns=["id", "info", "data", "tags"]).to_pylist()
            offset = 0
            for image_id, group_size in group_sizes:
                group_rows_by_image_id[image_id] = taken_rows[offset:offset + group_size]
                offset += group_size

        for image_id in image_id_chunk:
            progress.advance()
            group_rows = group_rows_by_image_id.get(image_id, [])
            counters["duplicate_rows"] += max(len(group_rows) - 1, 0)
            if not group_rows:
                continue

            first = group_rows[0]
            merged_tags: list[str] = []
            info_variants: list[str] = []
            first_data = str(first.get("data") or "")
            primary_info = json.loads(str(first.get("info") or "{}"))
            if not isinstance(primary_info, dict):
                primary_info = {}

            for row in group_rows:
                tags = row.get("tags") or []
                merged_tags.extend(str(tag) for tag in tags if tag)
                current_data = str(row.get("data") or "")
                if current_data != first_data and current_data and first_data and current_data != first_data:
                    counters["data_conflicts"] += 1
                    warning_writer.write({
                        "type": "image_labels_data_conflict",
                        "image_id": image_id,
                        "first_data": first_data,
                        "duplicate_data": current_data,
                    })
                try:
                    info = json.loads(str(row.get("info") or "{}"))
                except json.JSONDecodeError:
                    info = {}
                if not isinstance(info, dict):
                    info = {}
                info_variants.append(_canonical_info_json(info))

            unique_variants = dedupe_preserve_order(info_variants)
            if len(unique_variants) > 1:
                counters["info_conflicts"] += 1
            primary_info["info_addtional"] = unique_variants[1:]

            pending_rows.append({
                "id": image_id,
                "info": json_dumps(primary_info),
                "data": first_data,
                "tags": dedupe_preserve_order(merged_tags),
            })
            if len(pending_rows) >= write_flush_rows:
                append_rows_to_lance_dataset(pending_rows, schema, output_path)
                pending_rows = []

    if pending_rows:
        append_rows_to_lance_dataset(pending_rows, schema, output_path)
    progress.report(final=True)
    return counters
