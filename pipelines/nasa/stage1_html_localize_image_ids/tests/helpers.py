from __future__ import annotations

from pathlib import Path

import lance
import pyarrow as pa


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


def write_dataset(path: Path, schema: pa.Schema, rows: list[dict[str, object]]) -> None:
    table = pa.Table.from_pydict(
        {field.name: [row.get(field.name) for row in rows] for field in schema},
        schema=schema,
    )
    lance.write_dataset(table, str(path), data_storage_version="2.1")

