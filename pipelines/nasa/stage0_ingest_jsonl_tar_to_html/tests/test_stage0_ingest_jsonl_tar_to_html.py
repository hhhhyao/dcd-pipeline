from __future__ import annotations

import io
import json
import os
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import lance
from PIL import Image

PIPE_PARENT = Path(__file__).resolve().parents[2]
PIPE_PARENT_REL = os.path.relpath(PIPE_PARENT, Path.cwd())
if PIPE_PARENT_REL not in sys.path:
    sys.path.insert(0, PIPE_PARENT_REL)

import stage0_ingest_jsonl_tar_to_html as pipe_module  # noqa: E402

build_image_ref = pipe_module.build_image_ref
build_image_ref_id = pipe_module.build_image_ref_id
build_image_info = pipe_module.build_image_info
build_text_info = pipe_module.build_text_info
run_streaming = pipe_module.run_streaming
ingest = pipe_module.ingest
_materialize_raw_source = pipe_module._materialize_raw_source


def _write_one_article_fixture(src_dir: Path) -> tuple[bytes, dict[str, object]]:
    src_dir.mkdir()
    image = Image.new("RGB", (2, 3), color=(255, 0, 0))
    image_buf = io.BytesIO()
    image.save(image_buf, format="JPEG")
    image_bytes = image_buf.getvalue()

    image_file = "article_hash/image_hash.jpg"
    image_url_ori = "https://www.nasa.gov/wp-content/uploads/example.jpg"
    entry: dict[str, object] = {
        "html": "<html><head><title>Example | NASA</title></head><body>hello</body></html>",
        "url": "https://www.nasa.gov/news-release/raw/",
        "final_url": "https://www.nasa.gov/news-release/example/",
        "crawl_time": "123",
        "page_type": ["NASA_PAGE"],
        "images": [
            {
                "image_file": image_file,
                "image_url": image_url_ori,
                "image_url_ori": image_url_ori,
                "caption_text": "Caption",
                "image_md5": "md5-value",
            },
        ],
    }
    (src_dir / "part000.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    with tarfile.open(src_dir / "part000.tar", "w") as tf:
        info = tarfile.TarInfo(image_file)
        info.size = len(image_bytes)
        tf.addfile(info, io.BytesIO(image_bytes))
    return image_bytes, entry


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
        image_refs_for_article={"img_1_ref": {"caption_text": "caption"}},
    )
    assert info["url"] == "https://example.com/final"
    assert info["final_url"] == "https://example.com/final"
    assert info["original_url"] == "https://example.com/raw"
    assert info["crawl_time"] == "123"
    assert info["extra_key"] == "extra-value"
    assert info["__defined__"]["links"]["images"] == [{"id": "img_1"}]
    assert info["image_refs"] == {"img_1_ref": {"caption_text": "caption"}}
    assert "page_type" not in info
    assert "html" not in info
    assert "images" not in info


def test_image_metadata_split_between_text_refs_and_label_info() -> None:
    img_meta = {
        "image_file": "part/hash/a.jpg",
        "image_url": "https://upload.wikimedia.org/a.jpg",
        "image_url_ori": "https://upload.wikimedia.org/a.jpg",
        "caption_title": "Title",
        "caption_text": "Caption",
        "image_md5": "abc",
    }
    image_record = {
        "image_bytes": b"fake-image-bytes",
        "sha256": "image-sha",
        "width": 100,
        "height": 200,
        "channel": "RGB",
    }
    label_info = build_image_info(img_meta, image_record=image_record, text_id="text-1")
    assert label_info == {
        "image_md5": "abc",
        "width": 100,
        "height": 200,
        "channel": "RGB",
        "size_bytes": len(b"fake-image-bytes"),
        "__defined__": {"links": {"text": [{"id": "text-1"}]}},
    }

    image_ref = build_image_ref(img_meta)
    assert image_ref == {
        "caption_text": "Caption",
        "image_url": "https://upload.wikimedia.org/a.jpg",
        "image_url_ori": "https://upload.wikimedia.org/a.jpg",
        "image_file": "part/hash/a.jpg",
        "caption_title": "Title",
    }
    assert build_image_ref_id("image-sha", img_meta["image_url_ori"]).startswith("image-sha_")


def test_run_streaming_writes_v2_image_refs(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()

    image = Image.new("RGB", (2, 3), color=(255, 0, 0))
    image_buf = io.BytesIO()
    image.save(image_buf, format="JPEG")
    image_bytes = image_buf.getvalue()

    image_file = "article_hash/image_hash.jpg"
    image_url_ori = "https://upload.wikimedia.org/wikipedia/commons/a/a0/example.jpg"
    entry = {
        "html": "<html><head><title>Example - Wikipedia</title></head><body>hello</body></html>",
        "url": "https://example.com/raw",
        "final_url": "https://example.com/final",
        "crawl_time": "123",
        "page_type": ["ENCYCLOPEDIA_PAGE"],
        "images": [
            {
                "image_file": image_file,
                "image_url": "https://upload.wikimedia.org/thumb/example.jpg",
                "image_url_ori": image_url_ori,
                "caption_text": "Caption",
                "caption_title": "Title",
                "image_md5": "md5-value",
            },
            {
                "image_file": image_file,
                "caption_text": "No original URL",
                "image_md5": "md5-value",
            },
        ],
    }
    (src_dir / "part000.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    with tarfile.open(src_dir / "part000.tar", "w") as tf:
        info = tarfile.TarInfo(image_file)
        info.size = len(image_bytes)
        tf.addfile(info, io.BytesIO(image_bytes))

    run_streaming(src_dir, dst_dir, log_interval=1000)

    text_row = lance.dataset(str(dst_dir / "text.lance")).to_table().to_pylist()[0]
    text_info = json.loads(text_row["info"])
    image_id = text_info["__defined__"]["links"]["images"][0]["id"]
    assert text_row["tags"] == ["ENCYCLOPEDIA_PAGE"]
    assert text_info["__defined__"]["links"]["images"] == [{"id": image_id}]
    assert list(text_info["image_refs"]) == [build_image_ref_id(image_id, image_url_ori)]
    assert text_info["image_refs"][build_image_ref_id(image_id, image_url_ori)]["caption_text"] == "Caption"
    assert "page_type" not in text_info

    label_rows = lance.dataset(str(dst_dir / "image_labels.lance")).to_table().to_pylist()
    assert len(label_rows) == 2
    label_info = json.loads(label_rows[0]["info"])
    assert label_info["image_md5"] == "md5-value"
    assert label_info["width"] == 2
    assert label_info["height"] == 3
    assert label_info["channel"] == "RGB"
    assert label_info["size_bytes"] == len(image_bytes)
    assert label_info["__defined__"]["links"]["text"] == [{"id": text_row["id"]}]
    for moved_key in ("caption_text", "caption_title", "image_url", "image_url_ori", "image_file"):
        assert moved_key not in label_info

    images_schema = lance.dataset(str(dst_dir / "images.lance")).schema
    assert str(images_schema.field("image_bytes").type) == "large_binary"


def test_run_streaming_append_parts_strategy(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    (src_dir / "part000.jsonl").write_text(
        json.dumps({
            "html": "<html><body>no images</body></html>",
            "page_type": "NO_IMAGE_PAGE",
            "images": [],
        })
        + "\n",
        encoding="utf-8",
    )
    with tarfile.open(src_dir / "part000.tar", "w"):
        pass

    run_streaming(src_dir, dst_dir, log_interval=1000, write_strategy="append_parts")

    text_rows = lance.dataset(str(dst_dir / "text.lance")).to_table().to_pylist()
    assert len(text_rows) == 1
    assert text_rows[0]["tags"] == ["NO_IMAGE_PAGE"]


def test_run_streaming_preserves_svg_images(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()

    svg_bytes = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="9">'
        b'<rect width="12" height="9" /></svg>'
    )
    image_file = "article_hash/image_hash.svg"
    entry = {
        "html": (
            "<html><head><title>NASA SVG</title></head>"
            '<body><img src="https://www.nasa.gov/wp-content/uploads/example.svg"></body></html>'
        ),
        "url": "https://www.nasa.gov/news-release/example/",
        "final_url": "https://www.nasa.gov/news-release/example/",
        "crawl_time": "123",
        "page_type": ["NASA_PAGE"],
        "images": [
            {
                "image_file": image_file,
                "image_url": "https://www.nasa.gov/wp-content/uploads/example.svg",
                "image_url_ori": "https://www.nasa.gov/wp-content/uploads/example.svg",
                "content_type": "image/svg+xml",
                "image_md5": "md5-value",
            },
        ],
    }
    (src_dir / "part000.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    with tarfile.open(src_dir / "part000.tar", "w") as tf:
        info = tarfile.TarInfo(image_file)
        info.size = len(svg_bytes)
        tf.addfile(info, io.BytesIO(svg_bytes))

    run_streaming(src_dir, dst_dir, log_interval=1000)

    image_rows = lance.dataset(str(dst_dir / "images.lance")).to_table().to_pylist()
    assert len(image_rows) == 1
    assert image_rows[0]["image_bytes"] == svg_bytes

    label_info = json.loads(
        lance.dataset(str(dst_dir / "image_labels.lance")).to_table().to_pylist()[0]["info"],
    )
    assert label_info["width"] == 12
    assert label_info["height"] == 9
    assert label_info["channel"] == "SVG"
    assert label_info["content_type"] == "image/svg+xml"


def test_materialize_raw_source_from_reader(tmp_path: Path) -> None:
    class FakeReader:
        name = "nasa_raw"
        version_num = 1

        def file_paths(self) -> list[str]:
            return ["metadata.json", "part000.jsonl"]

        def read_file(self, rel: str, target: Path) -> None:
            target.write_text(f"content:{rel}", encoding="utf-8")

    progress: list[tuple[int, int, str]] = []
    ctx = SimpleNamespace(
        io=SimpleNamespace(require_raw_input=lambda slot: FakeReader()),
        set_progress=lambda done, total, msg="": progress.append((done, total, msg)),
    )

    out = _materialize_raw_source(ctx, tmp_path)

    assert (out / "metadata.json").read_text(encoding="utf-8") == "content:metadata.json"
    assert (out / "part000.jsonl").read_text(encoding="utf-8") == "content:part000.jsonl"
    assert progress[-1] == (2, 2, "materialized raw file part000.jsonl")


def test_ingest_without_output_dir_yields_remote_batches(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    image_bytes, _entry = _write_one_article_fixture(src_dir)
    ctx = SimpleNamespace(
        config={
            "source_dir": str(src_dir),
            "remote_batch_size": 1,
            "log_interval": 1000,
        },
    )

    batches = list(ingest(ctx))

    assert len(batches) == 1
    batch = batches[0]
    assert batch["text"]["data"] == [
        "<html><head><title>Example | NASA</title></head><body>hello</body></html>",
    ]
    assert batch["text"]["tags"] == [["NASA_PAGE"]]
    text_info = json.loads(batch["text"]["info"][0])
    assert text_info["url"] == "https://www.nasa.gov/news-release/example/"
    assert text_info["title"] == "Example"
    assert batch["image"]["image_bytes"] == [image_bytes]
    image_info = json.loads(batch["image"]["info"][0])
    assert image_info["image_md5"] == "md5-value"
    assert image_info["__defined__"]["links"]["text"] == [{"id": batch["text"]["id"][0]}]
