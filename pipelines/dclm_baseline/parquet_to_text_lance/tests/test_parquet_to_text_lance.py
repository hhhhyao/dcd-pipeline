from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import lance
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipelines.dclm_baseline.parquet_to_text_lance import main as pipe
from pipelines.dclm_baseline.run_local.parquet_to_text_lance import run


class FakeCtx:
    def __init__(self, source_dir: Path, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.volumes = {"source": source_dir}
        self.progress: list[tuple[int, int, str]] = []

    def set_progress(self, completed: int, total: int = 0, message: str = "") -> None:
        self.progress.append((completed, total, message))


def _write_dclm(path: Path, rows: list[dict[str, Any]]) -> None:
    table = pa.table(
        {
            "text": [row.get("text") for row in rows],
            "url": [row.get("url") for row in rows],
            "id": [row.get("id") for row in rows],
            "language": [row.get("language") for row in rows],
            "language_score": [row.get("language_score") for row in rows],
            "fasttext_score": [row.get("fasttext_score") for row in rows],
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def _text_rows_from_prefixed_batches(batches: list[pa.RecordBatch]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for batch in batches:
        assert batch.schema.names == ["text/id", "text/data", "text/info", "text/tags"]
        data = batch.to_pydict()
        for idx in range(batch.num_rows):
            rows.append({
                "id": data["text/id"][idx],
                "data": data["text/data"][idx],
                "info": json.loads(data["text/info"][idx]),
                "tags": data["text/tags"][idx],
            })
    return rows


def test_ingest_yields_prefixed_text_batches_with_metadata_and_fallback_ids(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_dclm(
        source / "part-b.parquet",
        [
            {
                "text": "second",
                "url": "https://example.com/2",
                "id": "",
                "language": "en",
                "language_score": 0.98,
                "fasttext_score": 0.25,
            },
        ],
    )
    _write_dclm(
        source / "part-a.parquet",
        [
            {
                "text": "first",
                "url": "https://example.com/1",
                "id": "doc-1",
                "language": "en",
                "language_score": 0.99,
                "fasttext_score": 0.5,
            },
        ],
    )
    ctx = FakeCtx(source, {"batch_rows": 1})

    rows = _text_rows_from_prefixed_batches(list(pipe.ingest(ctx)))

    assert [row["data"] for row in rows] == ["first", "second"]
    assert rows[0]["id"] == "doc-1"
    assert rows[1]["id"].startswith("dclm-baseline-")
    assert rows[0]["info"] == {
        "source_file": "part-a.parquet",
        "url": "https://example.com/1",
        "language": "en",
        "language_score": 0.99,
        "fasttext_score": 0.5,
    }
    assert rows[1]["tags"] == ["dclm-baseline", "en"]


def test_local_runner_writes_lance_in_sorted_file_order_with_max_rows(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_dclm(
        source / "z.parquet",
        [
            {"text": "z0", "url": "u-z0", "id": "z0", "language": "en", "language_score": 1.0, "fasttext_score": 0.1},
            {"text": "z1", "url": "u-z1", "id": "z1", "language": "en", "language_score": 1.0, "fasttext_score": 0.1},
        ],
    )
    _write_dclm(
        source / "a.parquet",
        [
            {"text": "a0", "url": "u-a0", "id": "a0", "language": "en", "language_score": 1.0, "fasttext_score": 0.1},
            {"text": "a1", "url": "u-a1", "id": "a1", "language": "en", "language_score": 1.0, "fasttext_score": 0.1},
        ],
    )
    output = tmp_path / "out"

    run(
        source_dir=source,
        output_dir=output,
        workers=2,
        batch_rows=1,
        max_rows=3,
        overwrite=True,
        prepare=False,
    )

    ds = lance.dataset(str(output / "text.lance"))
    rows = ds.to_table().to_pylist()
    assert [row["id"] for row in rows] == ["a0", "a1", "z0"]
    assert [row["data"] for row in rows] == ["a0", "a1", "z0"]
