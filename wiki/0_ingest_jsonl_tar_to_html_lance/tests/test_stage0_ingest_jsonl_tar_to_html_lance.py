from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wiki._module_loader import load_pipe_package  # noqa: E402

pipe_module = load_pipe_package(
    ROOT / "wiki" / "0_ingest_jsonl_tar_to_html_lance",
    alias="test_stage0_ingest_jsonl_tar_to_html_lance_pkg",
)
build_image_info = pipe_module.build_image_info
build_text_info = pipe_module.build_text_info


def test_build_text_info_preserves_raw_page_fields() -> None:
    entry = {
        "url": "https://example.com/raw",
        "final_url": "https://example.com/final",
        "crawl_time": "123",
        "crawl_type": "PC",
        "page_type": ["ENCYCLOPEDIA_PAGE"],
        "part": "part-x",
        "image_status": "complete",
        "html": "<html></html>",
        "images": [],
        "extra_key": "extra-value",
    }
    info = build_text_info(
        entry,
        url="https://example.com/final",
        title="Example",
        image_ids_for_article=["img_1"],
    )
    assert info["url"] == "https://example.com/final"
    assert info["final_url"] == "https://example.com/final"
    assert info["original_url"] == "https://example.com/raw"
    assert info["crawl_time"] == "123"
    assert info["extra_key"] == "extra-value"
    assert "html" not in info
    assert "images" not in info


def test_build_image_info_preserves_raw_image_fields() -> None:
    img_meta = {
        "image_file": "part/hash/a.jpg",
        "image_url": "https://upload.wikimedia.org/a.jpg",
        "image_url_ori": "https://upload.wikimedia.org/a.jpg",
        "width": 100,
        "height": 200,
        "caption_title": "Title",
        "caption_text": "Caption",
        "image_md5": "abc",
    }
    info = build_image_info(img_meta, article_id="00001")
    assert info["text_ids"] == ["00001"]
    assert info["image_file"] == "part/hash/a.jpg"
    assert info["image_url"] == "https://upload.wikimedia.org/a.jpg"
    assert info["image_url_ori"] == "https://upload.wikimedia.org/a.jpg"
    assert info["caption_text"] == "Caption"
    assert info["url"] == "https://upload.wikimedia.org/a.jpg"
    assert info["caption"] == "Caption"
