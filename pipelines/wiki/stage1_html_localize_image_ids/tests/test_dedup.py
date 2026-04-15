from __future__ import annotations

import json

import lance
import pyarrow as pa

from ops.cache_io import JsonlShardWriter
from ops.lance_ops import load_order_cache, load_rowids_cache, scan_image_label_caches
from tests.helpers import IMAGE_LABELS_SCHEMA, write_dataset
from workflow.dedup import dedup_image_labels_dataset


def test_dedup_image_labels_merges_tags_without_warning_for_equivalent_info(tmp_path) -> None:
    image_labels_path = tmp_path / "image_labels.lance"
    image_labels_out = tmp_path / "image_labels_out.lance"
    cache_dir = tmp_path / "cache"

    write_dataset(
        image_labels_path,
        IMAGE_LABELS_SCHEMA,
        [
            {
                "id": "img-1",
                "info": json.dumps({"width": 1, "height": 2}, ensure_ascii=False),
                "data": "",
                "tags": ["x"],
            },
            {
                "id": "img-1",
                "info": json.dumps({"height": 2, "width": 1}, ensure_ascii=False),
                "data": "",
                "tags": ["y", "x"],
            },
            {
                "id": "img-2",
                "info": json.dumps({"width": 3}, ensure_ascii=False),
                "data": "",
                "tags": [],
            },
        ],
    )

    warning_writer = JsonlShardWriter(cache_dir, "warnings", flush_rows=10)
    label_stats = dedup_image_labels_dataset(
        image_labels_path,
        image_labels_out,
        row_ids_by_image_id={"img-1": [0, 1], "img-2": [2]},
        ordered_image_ids=["img-1", "img-2"],
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        warning_writer=warning_writer,
        temp_dir=cache_dir,
    )
    warning_count = warning_writer.finalize(tmp_path / "warnings.jsonl")

    label_rows = lance.dataset(str(image_labels_out)).to_table().to_pylist()
    label_rows_by_id = {row["id"]: row for row in label_rows}
    img1_info = json.loads(label_rows_by_id["img-1"]["info"])
    assert img1_info == {"width": 1, "height": 2}
    assert label_rows_by_id["img-1"]["tags"] == ["x", "y"]
    assert label_stats["content_mismatch_warnings"] == 0
    assert warning_count == 0


def test_dedup_image_labels_warns_when_non_tag_content_differs(tmp_path) -> None:
    image_labels_path = tmp_path / "image_labels_warn.lance"
    image_labels_out = tmp_path / "image_labels_warn_out.lance"
    cache_dir = tmp_path / "cache_warn"

    write_dataset(
        image_labels_path,
        IMAGE_LABELS_SCHEMA,
        [
            {"id": "img-1", "info": json.dumps({"width": 1}, ensure_ascii=False), "data": "", "tags": ["x"]},
            {"id": "img-1", "info": json.dumps({"width": 2}, ensure_ascii=False), "data": "", "tags": ["y"]},
            {"id": "img-2", "info": json.dumps({"width": 3}, ensure_ascii=False), "data": "", "tags": []},
        ],
    )

    warning_writer = JsonlShardWriter(cache_dir, "warnings", flush_rows=10)
    label_stats = dedup_image_labels_dataset(
        image_labels_path,
        image_labels_out,
        row_ids_by_image_id={"img-1": [0, 1], "img-2": [2]},
        ordered_image_ids=["img-1", "img-2"],
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        warning_writer=warning_writer,
        temp_dir=cache_dir,
    )
    warning_writer.finalize(tmp_path / "warnings_warn.jsonl")

    label_rows = lance.dataset(str(image_labels_out)).to_table().to_pylist()
    label_rows_by_id = {row["id"]: row for row in label_rows}
    assert json.loads(label_rows_by_id["img-1"]["info"]) == {"width": 1}
    assert label_rows_by_id["img-1"]["tags"] == ["x", "y"]
    assert label_stats["content_mismatch_warnings"] == 1


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
    ordered_ids = [str(row["image_id"]) for row in load_order_cache(order_cache_path)]

    assert row_ids_by_id["img-1"] == [0, 2]
    assert row_ids_by_id["img-2"] == [1]
    assert row_ids_by_id["img-3"] == [3]
    assert ordered_ids == ["img-1", "img-2", "img-3"]

    ds = lance.dataset(str(image_labels_path))
    taken = ds.take(row_ids_by_id["img-1"], columns=["id"]).to_pylist()
    assert [row["id"] for row in taken] == ["img-1", "img-1"]
