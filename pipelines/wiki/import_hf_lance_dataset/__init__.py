"""Import a wiki text+image Lance dataset from Hugging Face."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
import tempfile
from typing import Any

import lance
import pyarrow as pa
from dcd_cli.pipe import PipeContext
from dcd_cli.pipe.spec import MultimodalBatch

TEXT_TABLE = "text.lance"
IMAGES_TABLE = "images.lance"
IMAGE_LABELS_TABLE = "image_labels.lance"

TEXT_COLUMNS = ["id", "data", "info", "tags"]
IMAGE_COLUMNS = ["id", "image_bytes"]
IMAGE_LABEL_COLUMNS = ["id", "data", "info", "tags"]
IMAGE_SHA_COLUMNS = ["id", "sha256"]
PAIRING_MODES = {"row_order", "id_join"}


def _cfg_str(config: dict[str, Any], key: str, default: str = "") -> str:
    return str(config.get(key, default) or "").strip()


def _cfg_int(config: dict[str, Any], key: str, default: int) -> int:
    try:
        value = int(config.get(key, default) or default)
    except (TypeError, ValueError):
        value = default
    return max(0, value)


def _cfg_bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _required_dir(path: Path, label: str) -> None:
    if not path.is_dir():
        raise FileNotFoundError(f"required {label} directory not found: {path}")


def _safe_path_fragment(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return safe[:80] or "dataset"


def _allow_patterns(dataset_subdir: str) -> list[str]:
    prefix = f"{dataset_subdir.strip('/')}/" if dataset_subdir.strip("/") else ""
    return [
        f"{prefix}{TEXT_TABLE}/**",
        f"{prefix}{IMAGES_TABLE}/**",
        f"{prefix}{IMAGE_LABELS_TABLE}/**",
    ]


def _check_lance_module() -> None:
    if not hasattr(lance, "dataset"):
        raise ImportError(
            "The Lance Python module does not provide lance.dataset(). "
            "Install the 'pylance' package, not the unrelated 'lance' package.",
        )


def _check_columns(ds: Any, table_name: str, columns: list[str]) -> None:
    names = set(ds.schema.names)
    missing = [col for col in columns if col not in names]
    if missing:
        raise ValueError(f"{table_name} is missing required columns: {missing}")


def _resolve_dataset_root(ctx: PipeContext) -> Path:
    config = ctx.config or {}
    hf_repo = _cfg_str(config, "hf_repo")
    if not hf_repo:
        raise ValueError("config 'hf_repo' is required")

    revision = _cfg_str(config, "revision", "main") or "main"
    token = (ctx.secrets or {}).get("HF_TOKEN") or None
    subdir = _cfg_str(config, "dataset_subdir").strip("/")

    from huggingface_hub import snapshot_download

    local_dir = Path(
        tempfile.mkdtemp(
            prefix=f"hf_lance_{_safe_path_fragment(hf_repo)}_",
            dir="/tmp",
        ),
    )
    download_root = Path(
        snapshot_download(
            repo_id=hf_repo,
            repo_type="dataset",
            revision=revision,
            token=token,
            allow_patterns=_allow_patterns(subdir),
            force_download=True,
            local_dir=str(local_dir),
        ),
    )
    print(
        f"Downloaded HF dataset {hf_repo}@{revision} to {download_root}",
        flush=True,
    )
    return download_root / subdir if subdir else download_root


def _open_dataset(root: Path, *, include_text: bool, include_images: bool) -> tuple[Any | None, Any | None, Any | None]:
    _check_lance_module()

    text_ds = images_ds = image_labels_ds = None
    if include_text:
        text_path = root / TEXT_TABLE
        _required_dir(text_path, TEXT_TABLE)
        text_ds = lance.dataset(str(text_path))
        _check_columns(text_ds, TEXT_TABLE, TEXT_COLUMNS)

    if include_images:
        images_path = root / IMAGES_TABLE
        image_labels_path = root / IMAGE_LABELS_TABLE
        _required_dir(images_path, IMAGES_TABLE)
        _required_dir(image_labels_path, IMAGE_LABELS_TABLE)
        images_ds = lance.dataset(str(images_path))
        image_labels_ds = lance.dataset(str(image_labels_path))
        _check_columns(images_ds, IMAGES_TABLE, IMAGE_COLUMNS)
        _check_columns(image_labels_ds, IMAGE_LABELS_TABLE, IMAGE_LABEL_COLUMNS)

    return text_ds, images_ds, image_labels_ds


def _limited_count(total: int, limit: int) -> int:
    return min(total, limit) if limit > 0 else total


def _scanner_batches(
    ds: Any,
    *,
    columns: list[str],
    batch_size: int,
) -> Iterator[pa.RecordBatch]:
    yield from ds.scanner(columns=columns, batch_size=max(1, batch_size)).to_batches()


def _yield_text_batches(
    text_ds: Any,
    *,
    batch_rows: int,
    max_rows: int,
    ctx: PipeContext,
    progress_offset: int,
    progress_total: int,
) -> Iterator[MultimodalBatch]:
    emitted = 0
    for batch in _scanner_batches(text_ds, columns=TEXT_COLUMNS, batch_size=batch_rows):
        if max_rows > 0 and emitted >= max_rows:
            break
        if max_rows > 0 and emitted + batch.num_rows > max_rows:
            batch = batch.slice(0, max_rows - emitted)
        if batch.num_rows == 0:
            continue

        data = batch.to_pydict()
        emitted += batch.num_rows
        ctx.set_progress(
            progress_offset + emitted,
            progress_total,
            f"text rows: {emitted}",
        )
        yield {"text": {col: data[col] for col in TEXT_COLUMNS}}


def _row_iter(ds: Any, columns: list[str], batch_size: int) -> Iterator[dict[str, Any]]:
    for batch in _scanner_batches(ds, columns=columns, batch_size=batch_size):
        cols = batch.to_pydict()
        for idx in range(batch.num_rows):
            yield {col: cols[col][idx] for col in columns}


def _flush_image_batch(
    ids: list[str],
    image_bytes: list[bytes],
    data: list[str],
    info: list[str],
    tags: list[list[str]],
) -> MultimodalBatch:
    return {
        "image": {
            "id": list(ids),
            "image_bytes": list(image_bytes),
            "data": list(data),
            "info": list(info),
            "tags": [list(value) for value in tags],
        },
    }


def _append_image_row(
    *,
    image_row: dict[str, Any],
    label_row: dict[str, Any],
    ids: list[str],
    image_bytes: list[bytes],
    data: list[str],
    info: list[str],
    tags: list[list[str]],
    row_number: int,
) -> int:
    raw_bytes = image_row["image_bytes"]
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise TypeError(f"image_bytes must be bytes for image row {row_number}")
    label_id = str(label_row["id"])
    image_id = str(image_row["id"])
    if image_id != label_id:
        raise ValueError(
            "images.lance and image_labels.lance ids differ for paired row "
            f"{row_number}: {image_id!r} != {label_id!r}",
        )

    ids.append(label_id)
    image_bytes.append(bytes(raw_bytes))
    data.append(str(label_row.get("data") or ""))
    info.append(str(label_row.get("info") or ""))
    row_tags = label_row.get("tags") or []
    tags.append([str(tag) for tag in row_tags])
    return len(raw_bytes)


def _yield_row_order_image_batches(
    images_ds: Any,
    image_labels_ds: Any,
    *,
    batch_rows: int,
    batch_bytes: int,
    max_rows: int,
    ctx: PipeContext,
    progress_offset: int,
    progress_total: int,
) -> Iterator[MultimodalBatch]:
    image_rows = int(images_ds.count_rows())
    image_label_rows = int(image_labels_ds.count_rows())
    if image_rows != image_label_rows:
        raise ValueError(
            "row_order mode requires images.lance and image_labels.lance "
            f"row counts to match: {image_rows} != {image_label_rows}",
        )

    image_iter = _row_iter(images_ds, IMAGE_COLUMNS, batch_rows)
    label_iter = _row_iter(image_labels_ds, IMAGE_LABEL_COLUMNS, batch_rows)

    ids: list[str] = []
    image_bytes_list: list[bytes] = []
    data_list: list[str] = []
    info_list: list[str] = []
    tags_list: list[list[str]] = []
    buffered_bytes = 0
    emitted = 0

    for row_number, (image_row, label_row) in enumerate(zip(image_iter, label_iter, strict=True)):
        if max_rows > 0 and emitted >= max_rows:
            break
        buffered_bytes += _append_image_row(
            image_row=image_row,
            label_row=label_row,
            ids=ids,
            image_bytes=image_bytes_list,
            data=data_list,
            info=info_list,
            tags=tags_list,
            row_number=row_number,
        )
        emitted += 1

        if len(ids) >= batch_rows or buffered_bytes >= batch_bytes:
            ctx.set_progress(progress_offset + emitted, progress_total, f"image rows: {emitted}")
            yield _flush_image_batch(ids, image_bytes_list, data_list, info_list, tags_list)
            ids.clear()
            image_bytes_list.clear()
            data_list.clear()
            info_list.clear()
            tags_list.clear()
            buffered_bytes = 0

    if ids:
        ctx.set_progress(progress_offset + emitted, progress_total, f"image rows: {emitted}")
        yield _flush_image_batch(ids, image_bytes_list, data_list, info_list, tags_list)


def _build_image_id_index(
    images_ds: Any,
    *,
    batch_rows: int,
    validate_duplicate_image_ids: bool,
) -> dict[str, int]:
    schema_names = set(images_ds.schema.names)
    columns = ["id"]
    if validate_duplicate_image_ids and "sha256" in schema_names:
        columns.append("sha256")

    first_row_by_id: dict[str, int] = {}
    sha_by_id: dict[str, str] = {}
    row_pos = 0
    for batch in _scanner_batches(images_ds, columns=columns, batch_size=batch_rows):
        data = batch.to_pydict()
        ids = data["id"]
        shas = data.get("sha256")
        for idx, raw_id in enumerate(ids):
            image_id = str(raw_id)
            if image_id not in first_row_by_id:
                first_row_by_id[image_id] = row_pos
            if shas is not None:
                sha = str(shas[idx] or "")
                previous_sha = sha_by_id.setdefault(image_id, sha)
                if previous_sha != sha:
                    raise ValueError(
                        "duplicate image id has conflicting sha256 values: "
                        f"{image_id!r}",
                    )
            row_pos += 1
    return first_row_by_id


def _labels_batch_to_rows(batch: pa.RecordBatch) -> list[dict[str, Any]]:
    data = batch.to_pydict()
    return [
        {col: data[col][idx] for col in IMAGE_LABEL_COLUMNS}
        for idx in range(batch.num_rows)
    ]


def _yield_id_join_image_batches(
    images_ds: Any,
    image_labels_ds: Any,
    *,
    batch_rows: int,
    batch_bytes: int,
    max_rows: int,
    ctx: PipeContext,
    progress_offset: int,
    progress_total: int,
    validate_duplicate_image_ids: bool,
) -> Iterator[MultimodalBatch]:
    first_row_by_id = _build_image_id_index(
        images_ds,
        batch_rows=batch_rows,
        validate_duplicate_image_ids=validate_duplicate_image_ids,
    )

    ids: list[str] = []
    image_bytes_list: list[bytes] = []
    data_list: list[str] = []
    info_list: list[str] = []
    tags_list: list[list[str]] = []
    buffered_bytes = 0
    emitted = 0

    for label_batch in _scanner_batches(
        image_labels_ds,
        columns=IMAGE_LABEL_COLUMNS,
        batch_size=batch_rows,
    ):
        if max_rows > 0 and emitted >= max_rows:
            break
        if max_rows > 0 and emitted + label_batch.num_rows > max_rows:
            label_batch = label_batch.slice(0, max_rows - emitted)
        if label_batch.num_rows == 0:
            continue

        label_rows = _labels_batch_to_rows(label_batch)
        row_ids: list[int] = []
        for label_row in label_rows:
            image_id = str(label_row["id"])
            row_id = first_row_by_id.get(image_id)
            if row_id is None:
                raise KeyError(f"image id from image_labels.lance not found in images.lance: {image_id}")
            row_ids.append(row_id)

        image_rows = images_ds.take(row_ids, columns=IMAGE_COLUMNS).to_pylist()
        for image_row, label_row in zip(image_rows, label_rows, strict=True):
            buffered_bytes += _append_image_row(
                image_row=image_row,
                label_row=label_row,
                ids=ids,
                image_bytes=image_bytes_list,
                data=data_list,
                info=info_list,
                tags=tags_list,
                row_number=emitted,
            )
            emitted += 1

            if len(ids) >= batch_rows or buffered_bytes >= batch_bytes:
                ctx.set_progress(progress_offset + emitted, progress_total, f"image rows: {emitted}")
                yield _flush_image_batch(ids, image_bytes_list, data_list, info_list, tags_list)
                ids.clear()
                image_bytes_list.clear()
                data_list.clear()
                info_list.clear()
                tags_list.clear()
                buffered_bytes = 0

    if ids:
        ctx.set_progress(progress_offset + emitted, progress_total, f"image rows: {emitted}")
        yield _flush_image_batch(ids, image_bytes_list, data_list, info_list, tags_list)


def _yield_image_batches(
    images_ds: Any,
    image_labels_ds: Any,
    *,
    pairing_mode: str,
    batch_rows: int,
    batch_bytes: int,
    max_rows: int,
    ctx: PipeContext,
    progress_offset: int,
    progress_total: int,
    validate_duplicate_image_ids: bool,
) -> Iterator[MultimodalBatch]:
    if pairing_mode == "row_order":
        yield from _yield_row_order_image_batches(
            images_ds,
            image_labels_ds,
            batch_rows=batch_rows,
            batch_bytes=batch_bytes,
            max_rows=max_rows,
            ctx=ctx,
            progress_offset=progress_offset,
            progress_total=progress_total,
        )
        return
    if pairing_mode == "id_join":
        yield from _yield_id_join_image_batches(
            images_ds,
            image_labels_ds,
            batch_rows=batch_rows,
            batch_bytes=batch_bytes,
            max_rows=max_rows,
            ctx=ctx,
            progress_offset=progress_offset,
            progress_total=progress_total,
            validate_duplicate_image_ids=validate_duplicate_image_ids,
        )
        return
    raise ValueError(f"unsupported image_pairing_mode: {pairing_mode!r}")


def ingest(ctx: PipeContext) -> Iterator[MultimodalBatch]:
    """Download a wiki Lance dataset from HF and stream it to DCD."""
    config = ctx.config or {}
    pairing_mode = _cfg_str(config, "image_pairing_mode", "id_join") or "id_join"
    if pairing_mode not in PAIRING_MODES:
        raise ValueError(f"image_pairing_mode must be one of {sorted(PAIRING_MODES)}")

    include_text = _cfg_bool(config, "include_text", True)
    include_images = _cfg_bool(config, "include_images", True)
    if not include_text and not include_images:
        raise ValueError("at least one of include_text or include_images must be true")

    root = _resolve_dataset_root(ctx)
    text_ds, images_ds, image_labels_ds = _open_dataset(
        root,
        include_text=include_text,
        include_images=include_images,
    )

    text_batch_rows = max(1, _cfg_int(config, "text_batch_rows", 1024))
    image_batch_rows = max(1, _cfg_int(config, "image_batch_rows", 256))
    image_batch_bytes = max(1, _cfg_int(config, "image_batch_bytes_mb", 256)) * 1024 * 1024
    max_text_rows = _cfg_int(config, "max_text_rows", 0)
    max_image_rows = _cfg_int(config, "max_image_rows", 0)
    validate_duplicate_image_ids = _cfg_bool(config, "validate_duplicate_image_ids", True)

    text_total = _limited_count(int(text_ds.count_rows()), max_text_rows) if text_ds is not None else 0
    image_total = (
        _limited_count(int(image_labels_ds.count_rows()), max_image_rows)
        if image_labels_ds is not None
        else 0
    )
    progress_total = text_total + image_total

    if text_ds is not None:
        yield from _yield_text_batches(
            text_ds,
            batch_rows=text_batch_rows,
            max_rows=max_text_rows,
            ctx=ctx,
            progress_offset=0,
            progress_total=progress_total,
        )
    if images_ds is not None and image_labels_ds is not None:
        yield from _yield_image_batches(
            images_ds,
            image_labels_ds,
            pairing_mode=pairing_mode,
            batch_rows=image_batch_rows,
            batch_bytes=image_batch_bytes,
            max_rows=max_image_rows,
            ctx=ctx,
            progress_offset=text_total,
            progress_total=progress_total,
            validate_duplicate_image_ids=validate_duplicate_image_ids,
        )
