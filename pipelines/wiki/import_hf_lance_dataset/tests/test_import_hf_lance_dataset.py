from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import lance
import pyarrow as pa

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipelines.wiki import stage0_5_import_hf_lance_dataset as pipe


class FakeCtx:
    def __init__(self, root: Path, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.dataset_root = root
        self.secrets: dict[str, str] = {}
        self.progress: list[tuple[int, int, str]] = []

    def set_progress(self, completed: int, total: int, message: str = "") -> None:
        self.progress.append((completed, total, message))


def _write_stage_dataset(
    root: Path,
    *,
    image_ids: list[str],
    label_ids: list[str],
    image_sha256: list[str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    text = pa.table(
        {
            "id": ["text-1"],
            "data": ["<html></html>"],
            "info": ["{}"],
            "tags": [["wiki"]],
        },
        schema=pa.schema([
            pa.field("id", pa.string()),
            pa.field("data", pa.large_string()),
            pa.field("info", pa.string()),
            pa.field("tags", pa.list_(pa.string())),
        ]),
    )
    lance.write_dataset(text, str(root / pipe.TEXT_TABLE), mode="overwrite")

    image_sha256 = image_sha256 or list(image_ids)
    images = pa.table(
        {
            "id": image_ids,
            "image_bytes": [f"bytes-{image_id}-{idx}".encode() for idx, image_id in enumerate(image_ids)],
            "sha256": image_sha256,
        },
        schema=pa.schema([
            pa.field("id", pa.string()),
            pa.field("image_bytes", pa.large_binary()),
            pa.field("sha256", pa.string()),
        ]),
    )
    lance.write_dataset(images, str(root / pipe.IMAGES_TABLE), mode="overwrite")

    labels = pa.table(
        {
            "id": label_ids,
            "data": [f'{{"label": "{image_id}"}}' for image_id in label_ids],
            "info": [f'{{"source": "{idx}"}}' for idx, _ in enumerate(label_ids)],
            "tags": [["image"] for _ in label_ids],
        },
        schema=pa.schema([
            pa.field("id", pa.string()),
            pa.field("data", pa.string()),
            pa.field("info", pa.string()),
            pa.field("tags", pa.list_(pa.string())),
        ]),
    )
    lance.write_dataset(labels, str(root / pipe.IMAGE_LABELS_TABLE), mode="overwrite")
    return root


def _patch_dataset_root(monkeypatch: Any, root: Path) -> None:
    monkeypatch.setattr(pipe, "_resolve_dataset_root", lambda _ctx: root)


def _flatten_images(batches: list[dict[str, Any]]) -> dict[str, list[Any]]:
    out = {"id": [], "image_bytes": [], "data": [], "info": [], "tags": []}
    for batch in batches:
        if "image" not in batch:
            continue
        image = batch["image"]
        for key in out:
            out[key].extend(image[key])
    return out


def test_row_order_preserves_duplicate_rows(tmp_path: Path, monkeypatch: Any) -> None:
    root = _write_stage_dataset(
        tmp_path / "stage",
        image_ids=["img-a", "img-a", "img-b"],
        label_ids=["img-a", "img-a", "img-b"],
        image_sha256=["sha-a", "sha-a", "sha-b"],
    )
    _patch_dataset_root(monkeypatch, root)
    ctx = FakeCtx(root, {"image_pairing_mode": "row_order", "image_batch_rows": 10})

    image = _flatten_images(list(pipe.ingest(ctx)))  # type: ignore[arg-type]

    assert image["id"] == ["img-a", "img-a", "img-b"]
    assert image["image_bytes"] == [b"bytes-img-a-0", b"bytes-img-a-1", b"bytes-img-b-2"]


def test_id_join_uses_label_order_and_allows_deduped_labels(tmp_path: Path, monkeypatch: Any) -> None:
    root = _write_stage_dataset(
        tmp_path / "stage",
        image_ids=["img-a", "img-a", "img-b"],
        label_ids=["img-b", "img-a"],
        image_sha256=["sha-a", "sha-a", "sha-b"],
    )
    _patch_dataset_root(monkeypatch, root)
    ctx = FakeCtx(root, {"image_pairing_mode": "id_join", "image_batch_rows": 10})

    image = _flatten_images(list(pipe.ingest(ctx)))  # type: ignore[arg-type]

    assert image["id"] == ["img-b", "img-a"]
    assert image["image_bytes"] == [b"bytes-img-b-2", b"bytes-img-a-0"]


def test_row_order_rejects_mismatched_counts(tmp_path: Path, monkeypatch: Any) -> None:
    root = _write_stage_dataset(
        tmp_path / "stage",
        image_ids=["img-a", "img-b"],
        label_ids=["img-a"],
    )
    _patch_dataset_root(monkeypatch, root)
    ctx = FakeCtx(root, {"image_pairing_mode": "row_order"})

    try:
        list(pipe.ingest(ctx))  # type: ignore[arg-type]
    except ValueError as exc:
        assert "row counts to match" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_id_join_rejects_missing_image_id(tmp_path: Path, monkeypatch: Any) -> None:
    root = _write_stage_dataset(
        tmp_path / "stage",
        image_ids=["img-a"],
        label_ids=["missing"],
    )
    _patch_dataset_root(monkeypatch, root)
    ctx = FakeCtx(root, {"image_pairing_mode": "id_join"})

    try:
        list(pipe.ingest(ctx))  # type: ignore[arg-type]
    except KeyError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("expected KeyError")


def test_id_join_rejects_duplicate_image_sha_conflict(tmp_path: Path, monkeypatch: Any) -> None:
    root = _write_stage_dataset(
        tmp_path / "stage",
        image_ids=["img-a", "img-a"],
        label_ids=["img-a"],
        image_sha256=["sha-a", "sha-other"],
    )
    _patch_dataset_root(monkeypatch, root)
    ctx = FakeCtx(root, {"image_pairing_mode": "id_join"})

    try:
        list(pipe.ingest(ctx))  # type: ignore[arg-type]
    except ValueError as exc:
        assert "conflicting sha256" in str(exc)
    else:
        raise AssertionError("expected ValueError")
