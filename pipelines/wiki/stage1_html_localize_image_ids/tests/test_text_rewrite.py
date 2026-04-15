from __future__ import annotations

import json
from pathlib import Path

import lance

from ops.cache_io import JsonlShardWriter
from plugins.wikimedia_production import (
    extract_img_urls_from_html,
    format_image_ref,
    normalize_image_url,
    rewrite_html as plugin_rewrite_html,
)
from tests.helpers import TEXT_SCHEMA, write_dataset
from workflow.core import rewrite_text_dataset


def test_rewrite_text_dataset_uses_inline_image_refs(tmp_path) -> None:
    text_path = tmp_path / "text.lance"
    output_path = tmp_path / "text_out.lance"
    cache_dir = tmp_path / "cache"

    write_dataset(
        text_path,
        TEXT_SCHEMA,
        [
            {
                "id": "text-1",
                "info": json.dumps({
                    "url": "https://page/1",
                    "image_ids": ["img-1", "img-2", "img-1"],
                    "image_refs": {
                        "img-1_hasha": {
                            "image_url_ori": "//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg",
                        },
                        "img-2_hashb": {
                            "image_url_ori": "https://upload.wikimedia.org/wikipedia/commons/f/f1/Bar.jpg",
                        },
                    },
                }, ensure_ascii=False),
                "data": (
                    '<img src="//upload.wikimedia.org/wikipedia/commons/thumb/e/e2/Foo.jpg/250px-Foo.jpg">'
                    '<img src="https://missing.example/x.jpg">'
                ),
                "tags": ["a"],
            }
        ],
    )

    missing_writer = JsonlShardWriter(cache_dir, "missing", flush_rows=1)
    warning_writer = JsonlShardWriter(cache_dir, "warnings", flush_rows=1)
    stats = rewrite_text_dataset(
        text_path,
        output_path,
        extract_urls=extract_img_urls_from_html,
        normalize_url=normalize_image_url,
        format_image_ref=format_image_ref,
        rewrite_html=plugin_rewrite_html,
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        missing_writer=missing_writer,
        warning_writer=warning_writer,
        temp_dir=cache_dir,
    )
    missing_writer.finalize(tmp_path / "missing.jsonl")
    warning_writer.finalize(tmp_path / "warning.jsonl")

    out_row = lance.dataset(str(output_path)).to_table().to_pylist()[0]
    info = json.loads(out_row["info"])
    assert 'src="images/img-1"' in out_row["data"]
    assert '_image_ref_id="img-1_hasha"' in out_row["data"]
    assert info["image_ids"] == ["img-1"]
    assert set(info["image_refs"]) == {"img-1_hasha", "img-2_hashb"}
    assert info["image_refs"]["img-1_hasha"]["image_url_ori"].startswith("//upload")
    assert stats["missing_urls"] == 1
    assert stats["unmatched_image_refs"] == 1
    warning_records = [
        json.loads(line)
        for line in Path(tmp_path / "warning.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(warning_records) == 1
    assert warning_records[0]["type"] == "image_ref_id_not_matched_to_html_url"
    assert warning_records[0]["image_ref_id"] == "img-2_hashb"
    assert warning_records[0]["image_id"] == "img-2"


def test_rewrite_text_dataset_uses_passed_extractor_for_rewrite_semantics(tmp_path) -> None:
    text_path = tmp_path / "text_extractor_semantics.lance"
    output_path = tmp_path / "text_extractor_semantics_out.lance"
    cache_dir = tmp_path / "cache_extractor_semantics"

    write_dataset(
        text_path,
        TEXT_SCHEMA,
        [
            {
                "id": "text-extractor",
                "info": json.dumps({
                    "url": "https://page/extractor",
                    "image_ids": ["img-a", "img-b"],
                    "image_refs": {
                        "img-a_hasha": {"image_url_ori": "https://example.com/a.jpg"},
                        "img-b_hashb": {"image_url_ori": "https://example.com/b.jpg"},
                    },
                }, ensure_ascii=False),
                "data": '<img src="https://example.com/a.jpg"><img src="https://example.com/b.jpg">',
                "tags": [],
            }
        ],
    )

    def extract_only_first(_html: str) -> list[str]:
        return ["https://example.com/a.jpg"]

    rewrite_calls: list[dict[str, list[dict[str, str] | None]]] = []

    def record_rewriter(html: str, replacements_by_raw_url: dict[str, list[dict[str, str] | None]]) -> str:
        rewrite_calls.append(replacements_by_raw_url)
        return plugin_rewrite_html(html, replacements_by_raw_url)

    missing_writer = JsonlShardWriter(cache_dir, "missing", flush_rows=1)
    warning_writer = JsonlShardWriter(cache_dir, "warnings", flush_rows=1)
    stats = rewrite_text_dataset(
        text_path,
        output_path,
        extract_urls=extract_only_first,
        normalize_url=lambda url: url,
        format_image_ref=format_image_ref,
        rewrite_html=record_rewriter,
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        missing_writer=missing_writer,
        warning_writer=warning_writer,
        temp_dir=cache_dir,
    )
    missing_writer.finalize(tmp_path / "missing_extractor_semantics.jsonl")
    warning_writer.finalize(tmp_path / "warning_extractor_semantics.jsonl")

    out_row = lance.dataset(str(output_path)).to_table().to_pylist()[0]
    assert out_row["data"] == (
        '<img src="images/img-a" _image_ref_id="img-a_hasha"><img src="https://example.com/b.jpg">'
    )
    assert rewrite_calls == [{
        "https://example.com/a.jpg": [{"src": "images/img-a", "image_ref_id": "img-a_hasha"}],
    }]
    warning_records = [
        json.loads(line)
        for line in Path(tmp_path / "warning_extractor_semantics.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert stats["unmatched_image_refs"] == 1
    assert len(warning_records) == 1
    assert warning_records[0]["image_ref_id"] == "img-b_hashb"
    assert warning_records[0]["type"] == "image_ref_id_not_matched_to_html_url"


def test_rewrite_text_dataset_marks_missing_candidate_urls_with_type(tmp_path) -> None:
    text_path = tmp_path / "text_missing_candidates.lance"
    output_path = tmp_path / "text_missing_candidates_out.lance"
    cache_dir = tmp_path / "cache_missing_candidates"

    write_dataset(
        text_path,
        TEXT_SCHEMA,
        [
            {
                "id": "text-2",
                "info": json.dumps({
                    "url": "https://page/2",
                    "image_ids": ["img-3"],
                    "image_refs": {
                        "img-3_hashc": {"caption_text": "no image url"},
                    },
                }, ensure_ascii=False),
                "data": '<img src="https://missing.example/y.jpg">',
                "tags": [],
            }
        ],
    )

    missing_writer = JsonlShardWriter(cache_dir, "missing", flush_rows=1)
    warning_writer = JsonlShardWriter(cache_dir, "warnings", flush_rows=1)
    stats = rewrite_text_dataset(
        text_path,
        output_path,
        extract_urls=extract_img_urls_from_html,
        normalize_url=normalize_image_url,
        format_image_ref=format_image_ref,
        rewrite_html=plugin_rewrite_html,
        batch_size=8,
        write_flush_rows=8,
        progress_every=0,
        missing_writer=missing_writer,
        warning_writer=warning_writer,
        temp_dir=cache_dir,
    )
    missing_writer.finalize(tmp_path / "missing_missing_candidates.jsonl")
    warning_writer.finalize(tmp_path / "warning_missing_candidates.jsonl")

    assert stats["unmatched_image_refs"] == 1
    warning_records = [
        json.loads(line)
        for line in Path(tmp_path / "warning_missing_candidates.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(warning_records) == 1
    assert warning_records[0]["type"] == "image_ref_id_no_candidate_urls"
    assert warning_records[0]["image_ref_id"] == "img-3_hashc"
    assert warning_records[0]["image_id"] == "img-3"
    assert warning_records[0]["candidate_urls_raw"] == []
    assert warning_records[0]["candidate_urls_normalized"] == []
