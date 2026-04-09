from __future__ import annotations

import json
from types import SimpleNamespace

import lance

import stage1_html_localize_image_ids as pipe_module
from workflow.core import PipelineArgs, run_pipeline
from tests.helpers import IMAGE_LABELS_SCHEMA, IMAGES_SCHEMA, TEXT_SCHEMA, write_dataset


def test_end_to_end_pipeline(tmp_path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    write_dataset(
        input_dir / "text.lance",
        TEXT_SCHEMA,
        [
            {
                "id": "text-1",
                "info": json.dumps({"url": "https://page/1", "image_ids": ["img-1", "img-2"]}, ensure_ascii=False),
                "data": (
                    '<img src="//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg">'
                    '<img src="https://not-found.example/x.jpg">'
                ),
                "tags": ["a"],
            }
        ],
    )
    write_dataset(
        input_dir / "images.lance",
        IMAGES_SCHEMA,
        [
            {"id": "img-2", "image_bytes": b"b", "sha256": "sha-b"},
            {"id": "img-1", "image_bytes": b"a", "sha256": "sha-a"},
            {"id": "img-1", "image_bytes": b"a", "sha256": "sha-a"},
        ],
    )
    write_dataset(
        input_dir / "image_labels.lance",
        IMAGE_LABELS_SCHEMA,
        [
            {
                "id": "img-1",
                "info": json.dumps({
                    "caption_text": "first",
                    "image_url_ori": "//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg",
                }, ensure_ascii=False),
                "data": "",
                "tags": ["x"],
            },
            {
                "id": "img-1",
                "info": json.dumps({
                    "caption_text": "second",
                    "image_url_ori": "https://upload.wikimedia.org/wikipedia/commons/e/e2/Foo.jpg",
                }, ensure_ascii=False),
                "data": "",
                "tags": ["y"],
            },
            {
                "id": "img-2",
                "info": json.dumps({"caption_text": "other", "image_url_ori": "https://upload.wikimedia.org/wikipedia/commons/f/f1/Bar.jpg"}, ensure_ascii=False),
                "data": "",
                "tags": [],
            },
        ],
    )

    output_dir = tmp_path / "output"
    args = PipelineArgs(
        input_dir=str(input_dir),
        output_dir=str(output_dir),
        text_db_name="text.lance",
        images_db_name="images.lance",
        image_labels_db_name="image_labels.lance",
        cache_dir=None,
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        extractor="plugins.wikimedia_production:extract_img_urls_from_html",
        normalizer="plugins.wikimedia_production:normalize_image_url",
        formatter="plugins.wikimedia_production:format_image_ref",
        rewriter="plugins.wikimedia_production:rewrite_html",
        compact_tables=[],
        overwrite=True,
    )
    result = run_pipeline(args, [])

    text_row = lance.dataset(str(output_dir / "text.lance")).to_table().to_pylist()[0]
    text_info = json.loads(text_row["info"])
    image_rows = lance.dataset(str(output_dir / "images.lance")).to_table().to_pylist()
    label_rows = lance.dataset(str(output_dir / "image_labels.lance")).to_table().to_pylist()
    missing_lines = (output_dir / "image_url_missing.jsonl").read_text(encoding="utf-8").strip().splitlines()
    warning_lines = (output_dir / "image_id_unmatched_warning.jsonl").read_text(encoding="utf-8").strip().splitlines()
    warning_records = [json.loads(line) for line in warning_lines]

    assert 'src="images/img-1"' in text_row["data"]
    assert text_info["image_ids"] == ["img-1", "img-2"]
    assert len(image_rows) == 2
    assert len(label_rows) == 2
    assert len(missing_lines) == 1
    assert len(warning_lines) == 1
    assert warning_records[0]["type"] == "image_id_not_matched_to_html_url"
    assert result["image_label_stats"]["info_conflicts"] == 1
    assert "scan_images_cache_seconds" in result["timings"]
    assert "scan_image_labels_cache_seconds" in result["timings"]


def test_pipe_ingest_uses_dataset_volume_and_compact_table_string(tmp_path) -> None:
    input_dir = tmp_path / "input_from_volume"
    input_dir.mkdir()
    write_dataset(
        input_dir / "text.lance",
        TEXT_SCHEMA,
        [
            {
                "id": "text-1",
                "info": json.dumps({"url": "https://page/1", "image_ids": ["img-1"]}, ensure_ascii=False),
                "data": '<img src="//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg">',
                "tags": [],
            }
        ],
    )
    write_dataset(
        input_dir / "images.lance",
        IMAGES_SCHEMA,
        [{"id": "img-1", "image_bytes": b"a", "sha256": "sha-a"}],
    )
    write_dataset(
        input_dir / "image_labels.lance",
        IMAGE_LABELS_SCHEMA,
        [
            {
                "id": "img-1",
                "info": json.dumps({"image_url_ori": "//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg"}, ensure_ascii=False),
                "data": "",
                "tags": [],
            }
        ],
    )

    output_dir = tmp_path / "output_from_volume"
    ctx = SimpleNamespace(
        dataset="",
        volumes={"dataset": str(input_dir)},
        config={
            "overwrite": True,
            "progress_every": 0,
            "write_flush_rows": 8,
            "batch_size": 8,
            "compact_tables": "text,image_labels",
        },
        output_dir=output_dir,
    )

    result_path = pipe_module.ingest(ctx)

    assert result_path == output_dir
    assert (output_dir / "text.lance").is_dir()
    assert (output_dir / "image_labels.lance").is_dir()
    assert (output_dir / "images.lance").is_dir()


def test_pipe_ingest_uses_named_dataset_under_datasets(tmp_path, monkeypatch) -> None:
    datasets_root = tmp_path / "datasets"
    dataset_name = "wiki_named"
    input_dir = datasets_root / dataset_name
    input_dir.mkdir(parents=True)
    write_dataset(
        input_dir / "text.lance",
        TEXT_SCHEMA,
        [
            {
                "id": "text-1",
                "info": json.dumps({"url": "https://page/1", "image_ids": []}, ensure_ascii=False),
                "data": "",
                "tags": [],
            }
        ],
    )
    write_dataset(
        input_dir / "images.lance",
        IMAGES_SCHEMA,
        [{"id": "img-1", "image_bytes": b"a", "sha256": "sha-a"}],
    )
    write_dataset(
        input_dir / "image_labels.lance",
        IMAGE_LABELS_SCHEMA,
        [{"id": "img-1", "info": json.dumps({"caption_text": "seed"}, ensure_ascii=False), "data": "", "tags": []}],
    )

    real_path = pipe_module.Path
    monkeypatch.setattr(pipe_module, "Path", lambda raw="": datasets_root if str(raw) == "/datasets" else real_path(raw))

    output_dir = tmp_path / "output_from_name"
    ctx = SimpleNamespace(
        dataset=dataset_name,
        volumes={},
        config={"overwrite": True, "progress_every": 0, "compact_tables": ""},
        output_dir=output_dir,
    )

    result_path = pipe_module.ingest(ctx)

    assert result_path == output_dir
    assert (output_dir / "text.lance").is_dir()


def test_pipe_ingest_requires_dataset_context(tmp_path) -> None:
    ctx = SimpleNamespace(
        dataset="",
        volumes={},
        config={"overwrite": True},
        output_dir=tmp_path / "output_missing_dataset",
    )

    try:
        pipe_module.ingest(ctx)
    except ValueError as exc:
        assert "Input dataset could not be resolved" in str(exc)
    else:
        raise AssertionError("Expected ingest(ctx) to fail without dataset context")
