from __future__ import annotations

import json
import sys
from pathlib import Path

import lance
import pyarrow as pa
import pytest
from dcd_cli.pipe import PipeContext

PIPE_PARENT = Path(__file__).resolve().parents[2]
if str(PIPE_PARENT) not in sys.path:
    sys.path.insert(0, str(PIPE_PARENT))

from stage1_5_merge_datasets_zero_copy import ingest  # noqa: E402


TEXT_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("info", pa.string()),
    pa.field("data", pa.large_string()),
    pa.field("tags", pa.list_(pa.string())),
])

IMAGES_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("image_bytes", pa.large_binary()),
    pa.field("sha256", pa.string()),
])

IMAGE_LABELS_SCHEMA = pa.schema([
    pa.field("id", pa.string()),
    pa.field("info", pa.string()),
    pa.field("data", pa.string()),
    pa.field("tags", pa.list_(pa.string())),
])


def _write_table(path: Path, schema: pa.Schema, rows: list[dict[str, object]], **kwargs) -> None:
    table = pa.Table.from_pydict(
        {field.name: [row.get(field.name) for row in rows] for field in schema},
        schema=schema,
    )
    lance.write_dataset(table, str(path), data_storage_version="2.1", **kwargs)


def _make_dataset(root: Path, *, text_ids: list[str], image_ids: list[str]) -> None:
    root.mkdir(parents=True)
    _write_table(
        root / "text.lance",
        TEXT_SCHEMA,
        [
            {"id": text_id, "info": "{}", "data": f"<p>{text_id}</p>", "tags": []}
            for text_id in text_ids
        ],
    )
    _write_table(
        root / "images.lance",
        IMAGES_SCHEMA,
        [
            {"id": image_id, "image_bytes": f"bytes-{image_id}".encode(), "sha256": image_id}
            for image_id in image_ids
        ],
        max_rows_per_file=10,
    )
    _write_table(
        root / "image_labels.lance",
        IMAGE_LABELS_SCHEMA,
        [
            {"id": image_id, "info": json.dumps({"source": root.name}), "data": "{}", "tags": []}
            for image_id in image_ids
        ],
    )


def _run_merge(output_dir: Path, *dataset_paths: Path) -> Path:
    ctx = PipeContext(
        dataset=output_dir.name,
        pipe_name="stage1_5_merge_datasets_zero_copy",
        pipe_version=1,
        output_dir=output_dir,
        config={
            "dataset_paths": json.dumps([str(path) for path in dataset_paths]),
            "compact_tables": "",
        },
    )
    result = ingest(ctx)
    assert result == output_dir
    return output_dir


def test_zero_copy_merge_with_partial_duplicate_fragment(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    out = tmp_path / "out"
    _make_dataset(first, text_ids=["t1"], image_ids=["a", "b"])
    _make_dataset(second, text_ids=["t2"], image_ids=["b", "c"])

    _run_merge(out, first, second)

    images = lance.dataset(str(out / "images.lance")).to_table().to_pydict()
    assert images["id"] == ["a", "b", "c"]
    assert images["image_bytes"] == [b"bytes-a", b"bytes-b", b"bytes-c"]
    assert not (out / "images.lance" / "data").exists()
    assert list((out / "images.lance" / "_deletions").glob("*.arrow"))

    labels = lance.dataset(str(out / "image_labels.lance")).to_table().to_pydict()
    assert labels["id"] == ["a", "b", "c"]
    assert json.loads(labels["info"][1])["source"] == "first"


def test_schema_mismatch_fails(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    out = tmp_path / "out"
    _make_dataset(first, text_ids=["t1"], image_ids=["a"])
    _make_dataset(second, text_ids=["t2"], image_ids=["b"])

    binary_schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("image_bytes", pa.binary()),
        pa.field("sha256", pa.string()),
    ])
    shutil_path = second / "images.lance"
    import shutil

    shutil.rmtree(shutil_path)
    _write_table(
        shutil_path,
        binary_schema,
        [{"id": "b", "image_bytes": b"bytes-b", "sha256": "b"}],
    )

    with pytest.raises(TypeError, match="schema mismatch"):
        _run_merge(out, first, second)
