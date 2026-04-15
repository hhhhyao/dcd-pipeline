from __future__ import annotations

import json

import lance
import pyarrow as pa

from tools.pipe_performance.fingerprint import compare_fingerprints, jsonl_fingerprint, lance_table_fingerprint
from tools.pipe_performance.lance_io import StreamOnceLanceWriter, scan_columns, write_record_batches_once
from tools.pipe_performance.profiling import TimingProfile, time_block
from tools.pipe_performance.reports import leaderboard, write_csv, write_html_report, write_json
from tools.pipe_performance.workspace import copy_code_snapshot, create_run_dir, write_manifest


def test_timing_profile_writes_json(tmp_path) -> None:
    profile = TimingProfile("smoke")
    with time_block(profile, "stage_a"):
        pass
    with time_block(profile, "hotspot_a", kind="hotspot"):
        pass
    profile.add_counter("rows", 3)
    profile.write_json(tmp_path / "profile.json")

    payload = json.loads((tmp_path / "profile.json").read_text(encoding="utf-8"))
    assert payload["run_name"] == "smoke"
    assert payload["counters"]["rows"] == 3
    assert "stage_a" in payload["stages"]
    assert "hotspot_a" in payload["hotspots"]


def test_stream_once_writer_and_lance_fingerprint(tmp_path) -> None:
    schema = pa.schema([pa.field("id", pa.string()), pa.field("value", pa.int64())])
    writer = StreamOnceLanceWriter(tmp_path / "table.lance", schema)
    writer.write_table(pa.table({"id": ["b", "a"], "value": [2, 1]}, schema=schema))
    stats = writer.finish()

    assert stats.rows_written == 2
    rows = lance.dataset(str(tmp_path / "table.lance")).to_table().to_pylist()
    assert rows == [{"id": "b", "value": 2}, {"id": "a", "value": 1}]
    batches = list(scan_columns(tmp_path / "table.lance", columns=["id"], batch_size=1))
    assert sum(batch.num_rows for batch in batches) == 2

    first = lance_table_fingerprint(tmp_path / "table.lance", columns=["id", "value"], sort_by=["id"])
    second = lance_table_fingerprint(tmp_path / "table.lance", columns=["id", "value"], sort_by=["id"])
    assert compare_fingerprints(first, second)["match"]

    write_record_batches_once(
        tmp_path / "table_copy.lance",
        schema,
        pa.table({"id": ["c"], "value": [3]}, schema=schema).to_batches(),
    )
    assert lance.dataset(str(tmp_path / "table_copy.lance")).count_rows() == 1


def test_jsonl_fingerprint_workspace_and_reports(tmp_path) -> None:
    jsonl = tmp_path / "records.jsonl"
    jsonl.write_text('{"b":2}\n{"a":1}\n', encoding="utf-8")
    fp = jsonl_fingerprint(jsonl, sort_lines=True)
    assert fp["rows"] == 2

    run_dir = create_run_dir(tmp_path / "workspace", group="smoke", run_name="r1")
    assert (run_dir / "code").is_dir()
    source = tmp_path / "source"
    source.mkdir()
    (source / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "x.pyc").write_text("bad", encoding="utf-8")
    copy_code_snapshot(source, run_dir / "code")
    assert (run_dir / "code" / "main.py").is_file()
    assert not (run_dir / "code" / "__pycache__").exists()
    write_manifest(run_dir / "run_manifest.yaml", {"run_name": "r1"})

    profiles = [
        {"run_name": "base", "total_seconds": 10.0},
        {"run_name": "fast", "total_seconds": 5.0},
    ]
    rows = leaderboard(profiles, baseline_name="base")
    assert rows[0]["run_name"] == "fast"
    write_json(tmp_path / "report.json", {"leaderboard": rows})
    write_csv(tmp_path / "report.csv", rows)
    write_html_report(tmp_path / "report.html", rows)
    assert (tmp_path / "report.json").is_file()
    assert (tmp_path / "report.csv").is_file()
    assert (tmp_path / "report.html").is_file()
