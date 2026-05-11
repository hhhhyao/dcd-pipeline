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

from pipelines.fineweb_edu.parquet_to_text_lance import main as pipe
from pipelines.fineweb_edu.run_local.parquet_to_text_lance import run


class FakeCtx:
    def __init__(self, source_dir: Path, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.volumes = {"source": source_dir}
        self.progress: list[tuple[int, int, str]] = []

    def set_progress(self, completed: int, total: int = 0, message: str = "") -> None:
        self.progress.append((completed, total, message))


def _write_fineweb(path: Path, rows: list[dict[str, Any]], *, include_date: bool = False) -> None:
    data: dict[str, list[Any]] = {
        "text": [row.get("text") for row in rows],
        "id": [row.get("id") for row in rows],
        "dump": [row.get("dump") for row in rows],
        "url": [row.get("url") for row in rows],
        "file_path": [row.get("file_path") for row in rows],
        "language": [row.get("language") for row in rows],
        "language_score": [row.get("language_score") for row in rows],
        "token_count": [row.get("token_count") for row in rows],
        "score": [row.get("score") for row in rows],
        "int_score": [row.get("int_score") for row in rows],
    }
    if include_date:
        data["date"] = [row.get("date") for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(data), path)


def _rows_from_prefixed_batches(batches: list[pa.RecordBatch]) -> list[dict[str, Any]]:
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


def test_ingest_preserves_optional_date_and_dump_tags(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_fineweb(
        source / "2013" / "data" / "CC-MAIN-2013-20" / "train.parquet",
        [
            {
                "text": "without date",
                "id": "fw-1",
                "dump": "CC-MAIN-2013-20",
                "url": "https://example.com/1",
                "file_path": "s3://bucket/a.warc.gz",
                "language": "en",
                "language_score": 0.9,
                "token_count": 12,
                "score": 3.5,
                "int_score": 4,
            },
        ],
    )
    _write_fineweb(
        source / "2024" / "data" / "CC-MAIN-2024-51" / "000.parquet",
        [
            {
                "text": "with date",
                "id": None,
                "dump": "CC-MAIN-2024-51",
                "url": "https://example.com/2",
                "date": "2024-12-01",
                "file_path": "s3://bucket/b.warc.gz",
                "language": "en",
                "language_score": 0.95,
                "token_count": 34,
                "score": 4.5,
                "int_score": 5,
            },
        ],
        include_date=True,
    )
    ctx = FakeCtx(source, {"batch_rows": 10})

    rows = _rows_from_prefixed_batches(list(pipe.ingest(ctx)))

    assert [row["data"] for row in rows] == ["without date", "with date"]
    assert rows[0]["tags"] == ["fineweb-edu", "en", "CC-MAIN-2013-20"]
    assert rows[1]["tags"] == ["fineweb-edu", "en", "CC-MAIN-2024-51"]
    assert rows[1]["id"].startswith("fineweb-edu-")
    assert rows[1]["info"]["date"] == "2024-12-01"
    assert rows[0]["info"]["source_file"] == "2013/data/CC-MAIN-2013-20/train.parquet"


def test_local_runner_writes_lance_with_multiple_workers(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_fineweb(
        source / "b.parquet",
        [
            {"text": "b0", "id": "b0", "dump": "dump-b", "url": "u-b0", "file_path": "f-b0", "language": "en", "language_score": 1.0, "token_count": 1, "score": 1.0, "int_score": 1},
        ],
    )
    _write_fineweb(
        source / "a.parquet",
        [
            {"text": "a0", "id": "a0", "dump": "dump-a", "url": "u-a0", "file_path": "f-a0", "language": "en", "language_score": 1.0, "token_count": 1, "score": 1.0, "int_score": 1},
            {"text": "a1", "id": "a1", "dump": "dump-a", "url": "u-a1", "file_path": "f-a1", "language": "en", "language_score": 1.0, "token_count": 1, "score": 1.0, "int_score": 1},
        ],
    )
    output = tmp_path / "out"

    run(
        source_dir=source,
        output_dir=output,
        workers=2,
        batch_rows=1,
        max_rows=0,
        overwrite=True,
        prepare=False,
    )

    rows = lance.dataset(str(output / "text.lance")).to_table().to_pylist()
    assert [row["id"] for row in rows] == ["a0", "a1", "b0"]
    assert json.loads(rows[0]["info"])["dump"] == "dump-a"
