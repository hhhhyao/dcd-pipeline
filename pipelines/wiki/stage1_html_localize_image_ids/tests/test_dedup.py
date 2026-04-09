from __future__ import annotations

import json

import lance
import pyarrow as pa

from ops.cache_io import JsonlShardWriter
from ops.lance_ops import load_order_cache, load_rowids_cache, scan_image_label_caches, scan_images_caches
from tests.helpers import IMAGE_LABELS_SCHEMA, IMAGES_SCHEMA, write_dataset
from workflow.dedup import dedup_image_labels_dataset, dedup_images_dataset


def test_dedup_images_and_labels_merges_expected_fields(tmp_path) -> None:
    images_path = tmp_path / "images.lance"
    images_out = tmp_path / "images_out.lance"
    image_labels_path = tmp_path / "image_labels.lance"
    image_labels_out = tmp_path / "image_labels_out.lance"
    cache_dir = tmp_path / "cache"

    write_dataset(
        images_path,
        IMAGES_SCHEMA,
        [
            {"id": "img-1", "image_bytes": b"a", "sha256": "sha-a"},
            {"id": "img-1", "image_bytes": b"a", "sha256": "sha-a"},
            {"id": "img-2", "image_bytes": b"b", "sha256": "sha-b"},
        ],
    )
    write_dataset(
        image_labels_path,
        IMAGE_LABELS_SCHEMA,
        [
            {
                "id": "img-1",
                "info": json.dumps({"caption_text": "a", "image_url_ori": "u1"}, ensure_ascii=False),
                "data": "",
                "tags": ["x"],
            },
            {
                "id": "img-1",
                "info": json.dumps({"caption_text": "b", "image_url_ori": "u2"}, ensure_ascii=False),
                "data": "",
                "tags": ["y", "x"],
            },
            {
                "id": "img-2",
                "info": json.dumps({"caption_text": "c", "image_url_ori": "u3"}, ensure_ascii=False),
                "data": "",
                "tags": [],
            },
        ],
    )

    warning_writer = JsonlShardWriter(cache_dir, "warnings", flush_rows=10)
    image_stats = dedup_images_dataset(
        images_path,
        images_out,
        first_row_id_by_image_id={"img-1": 0, "img-2": 2},
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        warning_writer=warning_writer,
    )
    label_stats = dedup_image_labels_dataset(
        image_labels_path,
        image_labels_out,
        row_ids_by_image_id={"img-1": [0, 1], "img-2": [2]},
        ordered_image_ids=["img-1", "img-2"],
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        warning_writer=warning_writer,
    )
    warning_writer.finalize(tmp_path / "warnings.jsonl")

    assert image_stats["kept_rows"] == 2
    label_rows = lance.dataset(str(image_labels_out)).to_table().to_pylist()
    label_rows_by_id = {row["id"]: row for row in label_rows}
    img1_info = json.loads(label_rows_by_id["img-1"]["info"])
    assert img1_info["caption_text"] == "a"
    assert len(img1_info["info_addtional"]) == 1
    assert label_rows_by_id["img-1"]["tags"] == ["x", "y"]
    assert label_stats["info_conflicts"] == 1


def test_dedup_uses_table_specific_caches_when_first_seen_order_differs(tmp_path) -> None:
    images_path = tmp_path / "images_misaligned.lance"
    images_out = tmp_path / "images_misaligned_out.lance"
    image_labels_path = tmp_path / "image_labels_misaligned.lance"
    image_labels_out = tmp_path / "image_labels_misaligned_out.lance"
    cache_dir = tmp_path / "cache_misaligned"
    images_order_cache = cache_dir / "images_order.arrow"
    image_labels_rowids_cache = cache_dir / "image_labels_rowids.arrow"
    image_labels_order_cache = cache_dir / "image_labels_order.arrow"

    write_dataset(
        images_path,
        IMAGES_SCHEMA,
        [
            {"id": "img-2", "image_bytes": b"b", "sha256": "sha-b"},
            {"id": "img-1", "image_bytes": b"a1", "sha256": "sha-a1"},
            {"id": "img-1", "image_bytes": b"a2", "sha256": "sha-a1"},
        ],
    )
    write_dataset(
        image_labels_path,
        IMAGE_LABELS_SCHEMA,
        [
            {
                "id": "img-1",
                "info": json.dumps({"caption_text": "a", "image_url_ori": "u1"}, ensure_ascii=False),
                "data": "",
                "tags": ["x"],
            },
            {
                "id": "img-1",
                "info": json.dumps({"caption_text": "b", "image_url_ori": "u2"}, ensure_ascii=False),
                "data": "",
                "tags": ["y"],
            },
            {
                "id": "img-2",
                "info": json.dumps({"caption_text": "c", "image_url_ori": "u3"}, ensure_ascii=False),
                "data": "",
                "tags": [],
            },
        ],
    )

    cache_dir.mkdir()
    scan_images_caches(
        images_path,
        order_cache_path=images_order_cache,
        batch_size=8,
        progress_every=0,
    )
    scan_image_label_caches(
        image_labels_path,
        rowids_cache_path=image_labels_rowids_cache,
        order_cache_path=image_labels_order_cache,
        batch_size=8,
        progress_every=0,
    )
    image_first_row_id_by_id = {
        str(row["image_id"]): int(row["first_row_id"])
        for row in load_order_cache(images_order_cache)
    }
    label_ordered_ids = [str(row["image_id"]) for row in load_order_cache(image_labels_order_cache)]
    label_row_ids_by_id = load_rowids_cache(image_labels_rowids_cache)

    warning_writer = JsonlShardWriter(cache_dir, "warnings", flush_rows=10)
    image_stats = dedup_images_dataset(
        images_path,
        images_out,
        first_row_id_by_image_id=image_first_row_id_by_id,
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        warning_writer=warning_writer,
    )
    label_stats = dedup_image_labels_dataset(
        image_labels_path,
        image_labels_out,
        row_ids_by_image_id=label_row_ids_by_id,
        ordered_image_ids=label_ordered_ids,
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        warning_writer=warning_writer,
    )
    warning_writer.finalize(tmp_path / "misaligned_warnings.jsonl")

    image_rows = lance.dataset(str(images_out)).to_table().to_pylist()
    label_rows = lance.dataset(str(image_labels_out)).to_table().to_pylist()
    assert [row["id"] for row in image_rows] == ["img-2", "img-1"]
    assert [row["id"] for row in label_rows] == ["img-1", "img-2"]
    assert image_stats["kept_rows"] == 2
    assert image_stats["duplicate_rows"] == 1
    assert label_stats["duplicate_rows"] == 1


def test_dedup_handles_images_without_duplicates_but_labels_with_duplicates(tmp_path) -> None:
    images_path = tmp_path / "images_no_dups.lance"
    images_out = tmp_path / "images_no_dups_out.lance"
    image_labels_path = tmp_path / "image_labels_with_dups.lance"
    image_labels_out = tmp_path / "image_labels_with_dups_out.lance"
    cache_dir = tmp_path / "cache_no_dups"
    images_order_cache = cache_dir / "images_order.arrow"
    image_labels_rowids_cache = cache_dir / "image_labels_rowids.arrow"
    image_labels_order_cache = cache_dir / "image_labels_order.arrow"

    write_dataset(
        images_path,
        IMAGES_SCHEMA,
        [
            {"id": "img-2", "image_bytes": b"b", "sha256": "sha-b"},
            {"id": "img-1", "image_bytes": b"a", "sha256": "sha-a"},
        ],
    )
    write_dataset(
        image_labels_path,
        IMAGE_LABELS_SCHEMA,
        [
            {"id": "img-1", "info": json.dumps({"caption_text": "a"}, ensure_ascii=False), "data": "", "tags": []},
            {"id": "img-1", "info": json.dumps({"caption_text": "b"}, ensure_ascii=False), "data": "", "tags": []},
            {"id": "img-2", "info": json.dumps({"caption_text": "c"}, ensure_ascii=False), "data": "", "tags": []},
        ],
    )

    cache_dir.mkdir()
    scan_images_caches(
        images_path,
        order_cache_path=images_order_cache,
        batch_size=8,
        progress_every=0,
    )
    scan_image_label_caches(
        image_labels_path,
        rowids_cache_path=image_labels_rowids_cache,
        order_cache_path=image_labels_order_cache,
        batch_size=8,
        progress_every=0,
    )
    image_first_row_id_by_id = {
        str(row["image_id"]): int(row["first_row_id"])
        for row in load_order_cache(images_order_cache)
    }
    label_ordered_ids = [str(row["image_id"]) for row in load_order_cache(image_labels_order_cache)]
    label_row_ids_by_id = load_rowids_cache(image_labels_rowids_cache)

    warning_writer = JsonlShardWriter(cache_dir, "warnings", flush_rows=10)
    image_stats = dedup_images_dataset(
        images_path,
        images_out,
        first_row_id_by_image_id=image_first_row_id_by_id,
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        warning_writer=warning_writer,
    )
    label_stats = dedup_image_labels_dataset(
        image_labels_path,
        image_labels_out,
        row_ids_by_image_id=label_row_ids_by_id,
        ordered_image_ids=label_ordered_ids,
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        warning_writer=warning_writer,
    )
    warning_writer.finalize(tmp_path / "no_dups_warnings.jsonl")

    assert image_stats["kept_rows"] == 2
    assert image_stats["duplicate_rows"] == 0
    assert label_stats["duplicate_rows"] == 1


def test_scan_image_label_caches_uses_logical_positions_for_take(tmp_path) -> None:
    image_labels_path = tmp_path / "image_labels_multifragment.lance"
    rowids_cache_path = tmp_path / "rowids.arrow"
    order_cache_path = tmp_path / "order.arrow"

    first = pa.Table.from_pydict(
        {
            "id": ["img-1", "img-2"],
            "info": [json.dumps({"n": 1}), json.dumps({"n": 2})],
            "data": ["", ""],
            "tags": [["a"], ["b"]],
        },
        schema=IMAGE_LABELS_SCHEMA,
    )
    second = pa.Table.from_pydict(
        {
            "id": ["img-1", "img-3"],
            "info": [json.dumps({"n": 3}), json.dumps({"n": 4})],
            "data": ["", ""],
            "tags": [["c"], ["d"]],
        },
        schema=IMAGE_LABELS_SCHEMA,
    )
    lance.write_dataset(first, str(image_labels_path), data_storage_version="2.1")
    lance.write_dataset(second, str(image_labels_path), mode="append", data_storage_version="2.1")

    scan_image_label_caches(
        image_labels_path,
        rowids_cache_path=rowids_cache_path,
        order_cache_path=order_cache_path,
        batch_size=8,
        progress_every=0,
    )
    row_ids_by_id = load_rowids_cache(rowids_cache_path)

    assert row_ids_by_id["img-1"] == [0, 2]
    assert row_ids_by_id["img-2"] == [1]
    assert row_ids_by_id["img-3"] == [3]

    ds = lance.dataset(str(image_labels_path))
    taken = ds.take(row_ids_by_id["img-1"], columns=["id"]).to_pylist()
    assert [row["id"] for row in taken] == ["img-1", "img-1"]
