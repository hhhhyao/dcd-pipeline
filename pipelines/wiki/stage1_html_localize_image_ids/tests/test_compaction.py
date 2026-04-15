from __future__ import annotations

import json

import lance

from ops.lance_ops import compact_selected_tables, normalize_compact_tables
from tests.helpers import IMAGE_LABELS_SCHEMA, IMAGES_SCHEMA, TEXT_SCHEMA, write_dataset


def test_compact_selected_tables_creates_expected_indices(tmp_path) -> None:
    write_dataset(
        tmp_path / "text.lance",
        TEXT_SCHEMA,
        [{"id": "t1", "info": json.dumps({"image_ids": []}), "data": "<p>x</p>", "tags": ["a"]}],
    )
    write_dataset(
        tmp_path / "images.lance",
        IMAGES_SCHEMA,
        [{"id": "i1", "image_bytes": b"a", "sha256": "sha-a"}],
    )
    write_dataset(
        tmp_path / "image_labels.lance",
        IMAGE_LABELS_SCHEMA,
        [{"id": "i1", "info": "{}", "data": "", "tags": ["a"]}],
    )

    compact_selected_tables(tmp_path, ["text", "image_labels"])

    text_ds = lance.dataset(str(tmp_path / "text.lance"))
    image_labels_ds = lance.dataset(str(tmp_path / "image_labels.lance"))
    images_ds = lance.dataset(str(tmp_path / "images.lance"))
    assert "id_idx" in {idx["name"] for idx in text_ds.list_indices()}
    assert "tags_idx" in {idx["name"] for idx in image_labels_ds.list_indices()}
    assert not images_ds.list_indices()


def test_normalize_compact_tables_skips_images() -> None:
    assert normalize_compact_tables(None) == ["text", "image_labels"]
    assert normalize_compact_tables(["text", "image_labels", "images"]) == ["text", "image_labels"]
