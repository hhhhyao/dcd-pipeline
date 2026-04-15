"""Merge Stage1 wiki datasets with zero-copy image-byte Lance manifests."""

from __future__ import annotations

import json
import logging
import shutil
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import lance
import pyarrow as pa
import pyarrow.ipc as ipc
import yaml
from lance import DatasetBasePath, LanceOperation
from lance.fragment import DataFile, DeletionFile, FragmentMetadata

try:
    from dcd_cli.pipe import PipeContext
except ImportError:  # pragma: no cover - used only outside pipe runtime
    PipeContext = Any  # type: ignore[misc,assignment]


LOG = logging.getLogger(__name__)

TEXT_TABLE = "text.lance"
IMAGES_TABLE = "images.lance"
IMAGE_LABELS_TABLE = "image_labels.lance"

IMAGE_BYTES_FIELD = "image_bytes"
ID_FIELD = "id"
TAGS_FIELD = "tags"

DEFAULT_BATCH_SIZE = 2048
DEFAULT_PROGRESS_EVERY = 5000


def _parse_dataset_paths(raw: Any) -> list[Path]:
    if isinstance(raw, (list, tuple)):
        values = list(raw)
    elif isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            raise ValueError("config 'dataset_paths' is required")
        try:
            parsed = json.loads(stripped)
            values = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            values = [part.strip() for part in stripped.replace("\n", ",").split(",") if part.strip()]
    else:
        raise ValueError("config 'dataset_paths' must be a JSON list or delimited string")

    paths: list[Path] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("path") or value.get("dataset_path") or value.get("name")
        if value is None:
            continue
        path = Path(str(value)).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"dataset path not found: {path}")
        for table_name in (TEXT_TABLE, IMAGES_TABLE, IMAGE_LABELS_TABLE):
            if not (path / table_name).is_dir():
                raise FileNotFoundError(f"missing {table_name} under {path}")
        paths.append(path)

    if not paths:
        raise ValueError("config 'dataset_paths' did not contain any usable paths")
    return paths


def _prepare_output_dir(output_dir: Path, overwrite: bool) -> None:
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"output directory already exists: {output_dir}")
        for child in output_dir.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def _ensure_compatible_schemas(dataset_paths: list[Path]) -> dict[str, pa.Schema]:
    first: dict[str, pa.Schema] = {}
    for table_name in (TEXT_TABLE, IMAGES_TABLE, IMAGE_LABELS_TABLE):
        first[table_name] = lance.dataset(str(dataset_paths[0] / table_name)).schema

    image_bytes_type = first[IMAGES_TABLE].field(IMAGE_BYTES_FIELD).type
    if not image_bytes_type.equals(pa.large_binary()):
        raise TypeError(
            f"{dataset_paths[0] / IMAGES_TABLE} has {IMAGE_BYTES_FIELD}: {image_bytes_type}; "
            "rerun Stage0/Stage1 with image_bytes: large_binary before zero-copy merge"
        )

    for dataset_path in dataset_paths[1:]:
        for table_name, expected_schema in first.items():
            schema = lance.dataset(str(dataset_path / table_name)).schema
            if not schema.equals(expected_schema, check_metadata=False):
                raise TypeError(
                    f"schema mismatch for {table_name}: {dataset_path / table_name} has "
                    f"{schema}, expected {expected_schema}"
                )
    return first


def _scanner_batches(dataset_path: Path, *, batch_size: int) -> Iterable[pa.RecordBatch]:
    ds = lance.dataset(str(dataset_path))
    yield from ds.scanner(batch_size=batch_size).to_batches()


def _write_stream_once(
    output_path: Path,
    schema: pa.Schema,
    batches: Iterable[pa.RecordBatch],
    *,
    tmp_dir: Path,
) -> int:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    stream_path = tmp_dir / f"{output_path.stem}_{uuid.uuid4().hex}.arrowstream"
    rows = 0
    with pa.OSFile(str(stream_path), "wb") as sink:
        with ipc.new_stream(sink, schema) as writer:
            for batch in batches:
                if batch.num_rows <= 0:
                    continue
                if not batch.schema.equals(schema, check_metadata=False):
                    batch = batch.cast(schema)
                writer.write_batch(batch)
                rows += batch.num_rows
    if rows == 0:
        empty = pa.Table.from_arrays(
            [pa.array([], type=field.type) for field in schema],
            schema=schema,
        )
        lance.write_dataset(empty, str(output_path), schema=schema, mode="create", data_storage_version="2.1")
    else:
        reader = ipc.open_stream(str(stream_path))
        lance.write_dataset(reader, str(output_path), schema=schema, mode="create", data_storage_version="2.1")
    stream_path.unlink(missing_ok=True)
    return rows


def _write_text(
    dataset_paths: list[Path],
    output_path: Path,
    schema: pa.Schema,
    *,
    batch_size: int,
    tmp_dir: Path,
    allow_duplicates: bool,
    progress_every: int,
) -> int:
    seen: set[str] = set()

    def batches() -> Iterable[pa.RecordBatch]:
        processed = 0
        for dataset_path in dataset_paths:
            for batch in _scanner_batches(dataset_path / TEXT_TABLE, batch_size=batch_size):
                if not allow_duplicates:
                    ids = [str(value) for value in batch.column(ID_FIELD).to_pylist()]
                    duplicates = [value for value in ids if value in seen]
                    if duplicates:
                        raise ValueError(f"duplicate text ids encountered; sample={duplicates[:10]}")
                    seen.update(ids)
                processed += batch.num_rows
                if progress_every > 0 and processed % progress_every < batch.num_rows:
                    LOG.info("text merge progress: %s rows", f"{processed:,}")
                yield batch

    return _write_stream_once(output_path, schema, batches(), tmp_dir=tmp_dir)


def _write_image_labels(
    dataset_paths: list[Path],
    output_path: Path,
    schema: pa.Schema,
    *,
    batch_size: int,
    tmp_dir: Path,
    progress_every: int,
) -> tuple[int, int]:
    seen: set[str] = set()
    duplicates = 0

    def batches() -> Iterable[pa.RecordBatch]:
        nonlocal duplicates
        processed = 0
        for dataset_path in dataset_paths:
            for batch in _scanner_batches(dataset_path / IMAGE_LABELS_TABLE, batch_size=batch_size):
                ids = [str(value) for value in batch.column(ID_FIELD).to_pylist()]
                mask_values: list[bool] = []
                for image_id in ids:
                    keep = image_id not in seen
                    mask_values.append(keep)
                    if keep:
                        seen.add(image_id)
                    else:
                        duplicates += 1
                mask = pa.array(mask_values, type=pa.bool_())
                filtered = batch.filter(mask)
                processed += batch.num_rows
                if progress_every > 0 and processed % progress_every < batch.num_rows:
                    LOG.info(
                        "image_labels merge progress: %s rows, unique=%s, duplicates=%s",
                        f"{processed:,}",
                        f"{len(seen):,}",
                        f"{duplicates:,}",
                    )
                if filtered.num_rows > 0:
                    yield filtered

    rows = _write_stream_once(output_path, schema, batches(), tmp_dir=tmp_dir)
    return rows, duplicates


def _clone_data_file(data_file: DataFile, *, base_id: int) -> DataFile:
    return DataFile(
        path=data_file.path,
        fields=data_file.fields,
        column_indices=data_file.column_indices,
        file_major_version=data_file.file_major_version,
        file_minor_version=data_file.file_minor_version,
        file_size_bytes=data_file.file_size_bytes,
        base_id=base_id,
    )


def _clone_fragment(
    metadata: FragmentMetadata,
    *,
    fragment_id: int,
    base_id: int,
    deletion_file: DeletionFile | None,
) -> FragmentMetadata:
    return FragmentMetadata(
        id=fragment_id,
        files=[_clone_data_file(data_file, base_id=base_id) for data_file in metadata.files],
        physical_rows=metadata.physical_rows,
        deletion_file=deletion_file,
        row_id_meta=metadata.row_id_meta,
        created_at_version_meta=metadata.created_at_version_meta,
        last_updated_at_version_meta=metadata.last_updated_at_version_meta,
    )


def _write_deletion_file(path: Path, row_ids: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([pa.field("row_id", pa.uint32(), nullable=False)])
    table = pa.Table.from_arrays([pa.array(row_ids, type=pa.uint32())], schema=schema)
    with ipc.new_file(str(path), schema) as writer:
        writer.write_table(table)


def _write_zero_copy_images(
    dataset_paths: list[Path],
    output_path: Path,
    schema: pa.Schema,
    *,
    progress_every: int,
) -> dict[str, int]:
    seen: set[str] = set()
    fragments: list[FragmentMetadata] = []
    bases: list[DatasetBasePath] = []
    rows_kept = 0
    rows_deleted = 0
    fragments_partial = 0
    fragments_skipped = 0
    next_fragment_id = 0

    for source_index, dataset_path in enumerate(dataset_paths, start=1):
        images_path = dataset_path / IMAGES_TABLE
        ds = lance.dataset(str(images_path))
        base_id = source_index
        bases.append(
            DatasetBasePath(
                path=str((images_path / "data").resolve()),
                name=f"source_{source_index}_images_data",
                id=base_id,
            ),
        )
        for fragment in ds.get_fragments():
            metadata = fragment.metadata
            if metadata.deletion_file is not None:
                raise ValueError(
                    f"source fragment already has a deletion file; compact before zero-copy merge: {images_path}"
                )
            table = fragment.to_table(columns=[ID_FIELD])
            ids = [str(value) for value in table.column(ID_FIELD).to_pylist()]
            delete_offsets: list[int] = []
            keep_count = 0
            for row_offset, image_id in enumerate(ids):
                if image_id in seen:
                    delete_offsets.append(row_offset)
                else:
                    seen.add(image_id)
                    keep_count += 1
            if keep_count == 0:
                fragments_skipped += 1
                rows_deleted += len(delete_offsets)
                continue

            deletion_file = None
            if delete_offsets:
                fragments_partial += 1
                rows_deleted += len(delete_offsets)
                delete_id = uuid.uuid4().int & ((1 << 63) - 1)
                deletion_file = DeletionFile(1, delete_id, "array", len(delete_offsets), None)
                _write_deletion_file(output_path / deletion_file.path(next_fragment_id), delete_offsets)

            fragments.append(
                _clone_fragment(
                    metadata,
                    fragment_id=next_fragment_id,
                    base_id=base_id,
                    deletion_file=deletion_file,
                ),
            )
            next_fragment_id += 1
            rows_kept += keep_count
            if progress_every > 0 and rows_kept % progress_every < keep_count:
                LOG.info("images zero-copy progress: %s unique rows", f"{rows_kept:,}")

    if not fragments:
        raise ValueError("zero-copy image merge produced no fragments")

    lance.LanceDataset.commit(
        str(output_path),
        LanceOperation.Overwrite(schema, fragments, initial_bases=bases),
        enable_v2_manifest_paths=True,
    )
    return {
        "rows": rows_kept,
        "duplicate_rows": rows_deleted,
        "fragments": len(fragments),
        "partial_fragments": fragments_partial,
        "skipped_fragments": fragments_skipped,
    }


def _safe_create_index(dataset_path: Path, column: str, index_type: str) -> None:
    ds = lance.dataset(str(dataset_path))
    if column not in ds.schema.names:
        return
    existing_names = {idx.get("name") for idx in ds.list_indices()}
    name = f"{column}_idx"
    if name in existing_names:
        return
    ds.create_scalar_index(column, index_type=index_type)


def _compact_and_index(output_dir: Path, compact_tables: set[str]) -> None:
    for table_name in (TEXT_TABLE, IMAGE_LABELS_TABLE, IMAGES_TABLE):
        path = output_dir / table_name
        if not path.is_dir():
            continue
        if table_name in compact_tables:
            if table_name == IMAGES_TABLE:
                LOG.warning("Skipping images.lance compaction to preserve zero-copy image storage")
            else:
                LOG.info("Compacting %s", table_name)
                lance.dataset(str(path)).optimize.compact_files()
        _safe_create_index(path, ID_FIELD, "BTREE")
        if table_name != IMAGES_TABLE:
            _safe_create_index(path, TAGS_FIELD, "LABEL_LIST")
        try:
            lance.dataset(str(path)).optimize.optimize_indices()
        except Exception as exc:
            LOG.warning("index optimization skipped for %s: %s", table_name, exc)


def _parse_compact_tables(raw: Any) -> set[str]:
    if raw is None:
        return {IMAGE_LABELS_TABLE}
    if isinstance(raw, str):
        names = [item.strip() for item in raw.split(",") if item.strip()]
    else:
        names = [str(item).strip() for item in raw if str(item).strip()]
    out: set[str] = set()
    for name in names:
        if name in {"text", TEXT_TABLE}:
            out.add(TEXT_TABLE)
        elif name in {"image_labels", IMAGE_LABELS_TABLE}:
            out.add(IMAGE_LABELS_TABLE)
        elif name in {"images", IMAGES_TABLE}:
            out.add(IMAGES_TABLE)
        else:
            raise ValueError(f"unknown compact table: {name}")
    return out


def _write_dataset_yaml(
    output_dir: Path,
    dataset_paths: list[Path],
    *,
    output_name: str,
    stats: dict[str, Any],
) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "name": output_name or output_dir.name,
        "description": "Zero-copy merged wiki Stage1 dataset",
        "tags": ["wiki", "stage1_5", "zero-copy", "lance"],
        "created_at": now,
        "updated_at": now,
        "source": {
            "upstream": [
                {
                    "name": path.name,
                    "path": str(path),
                    "relationship": "merged_from",
                }
                for path in dataset_paths
            ],
        },
        "pipeline": {
            "steps": [
                {
                    "name": "stage1_5_merge_datasets_zero_copy",
                    "operation": "ingest",
                    "stats": stats,
                },
            ],
        },
    }
    (output_dir / "dataset.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")


def ingest(ctx: PipeContext) -> Path | None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    output_dir = Path(str(ctx.output_dir))
    config = ctx.config or {}
    dataset_paths = _parse_dataset_paths(config.get("dataset_paths", ""))
    batch_size = max(1, int(config.get("batch_size", DEFAULT_BATCH_SIZE)))
    progress_every = max(0, int(config.get("progress_every", DEFAULT_PROGRESS_EVERY)))
    overwrite = bool(config.get("overwrite", True))
    allow_text_id_duplicates = bool(config.get("allow_text_id_duplicates", True))
    output_name = str(config.get("output_name", "") or "")
    compact_tables = _parse_compact_tables(config.get("compact_tables", IMAGE_LABELS_TABLE))

    _prepare_output_dir(output_dir, overwrite)
    tmp_dir = output_dir / "tmp"
    schemas = _ensure_compatible_schemas(dataset_paths)
    total_t0 = time.perf_counter()

    LOG.info("Merging %d dataset(s) into %s", len(dataset_paths), output_dir)
    text_rows = _write_text(
        dataset_paths,
        output_dir / TEXT_TABLE,
        schemas[TEXT_TABLE],
        batch_size=batch_size,
        tmp_dir=tmp_dir,
        allow_duplicates=allow_text_id_duplicates,
        progress_every=progress_every,
    )
    label_rows, label_duplicates = _write_image_labels(
        dataset_paths,
        output_dir / IMAGE_LABELS_TABLE,
        schemas[IMAGE_LABELS_TABLE],
        batch_size=batch_size,
        tmp_dir=tmp_dir,
        progress_every=progress_every,
    )
    image_stats = _write_zero_copy_images(
        dataset_paths,
        output_dir / IMAGES_TABLE,
        schemas[IMAGES_TABLE],
        progress_every=progress_every,
    )
    _compact_and_index(output_dir, compact_tables)
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    stats = {
        "text_rows": text_rows,
        "image_label_rows": label_rows,
        "image_label_duplicate_rows": label_duplicates,
        "image_rows": image_stats["rows"],
        "image_duplicate_rows": image_stats["duplicate_rows"],
        "image_fragments": image_stats["fragments"],
        "image_partial_fragments": image_stats["partial_fragments"],
        "image_skipped_fragments": image_stats["skipped_fragments"],
        "seconds": round(time.perf_counter() - total_t0, 3),
        "image_storage": "zero_copy_lance_manifest_bases",
    }
    _write_dataset_yaml(output_dir, dataset_paths, output_name=output_name, stats=stats)
    LOG.info("Stage1.5 merge complete: %s", stats)
    return output_dir


if __name__ == "__main__":
    from dcd_cli.pipe import PipeContext as RuntimePipeContext

    if len(sys.argv) < 4:
        raise SystemExit(
            "usage: python main.py OUTPUT_DIR DATASET_PATH [DATASET_PATH ...]"
        )
    out = Path(sys.argv[1])
    ingest(
        RuntimePipeContext(
            dataset=out.name,
            pipe_name="stage1_5_merge_datasets_zero_copy",
            pipe_version=1,
            output_dir=out,
            config={"dataset_paths": json.dumps(sys.argv[2:])},
        ),
    )
