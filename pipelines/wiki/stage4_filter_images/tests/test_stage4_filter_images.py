from __future__ import annotations

import json
import os
import sys
from pathlib import Path


PIPE_PARENT = Path(__file__).resolve().parents[2]
PIPE_PARENT_REL = os.path.relpath(PIPE_PARENT, Path.cwd())
if PIPE_PARENT_REL not in sys.path:
    sys.path.insert(0, PIPE_PARENT_REL)

REPO_ROOT = Path(__file__).resolve().parents[4]
DCD_CLI_ROOT = REPO_ROOT / "reference_repo" / "dcd-cli"
if DCD_CLI_ROOT.is_dir() and str(DCD_CLI_ROOT) not in sys.path:
    sys.path.insert(0, str(DCD_CLI_ROOT))

from dcd_cli.pipe import PipeContext  # noqa: E402
from dcd_cli.pipe.run import call_fn, multimodal_from_dict  # noqa: E402
import stage4_filter_images as pipe_module  # noqa: E402


def _payload(content):
    return json.dumps([{"role": "user", "content": content}], ensure_ascii=False)


def _run_map(batch, config=None):
    rb = multimodal_from_dict(batch)
    ctx = PipeContext(
        dataset="demo",
        pipe_name="stage4_filter_images",
        pipe_version=1,
        config=config or {},
    )
    out = call_fn(pipe_module.map, rb, ctx, "dict")
    return out.to_pydict()


def test_filter_images_drops_small_known_images_and_updates_info() -> None:
    batch = {
        "text": {
            "id": ["1"],
            "data": [
                _payload(
                    [
                        {"type": "text", "text": "A"},
                        {"type": "image_url", "image_url": {"url": "images/keep.jpg"}},
                        {"type": "image_url", "image_url": {"url": "images/drop.jpg"}},
                        {"type": "text", "text": "B"},
                    ],
                ),
            ],
            "info": ['{"format":"openai","image_ids":["keep.jpg","drop.jpg"]}'],
        },
        "image": {
            "id": [["keep.jpg", "drop.jpg"]],
            "info": [[
                json.dumps({"width": 100, "height": 100, "text_ids": ["1"]}),
                json.dumps({"width": 10, "height": 10, "text_ids": ["1"]}),
            ]],
        },
    }

    out = _run_map(
        batch,
        {"min_image_width": 20, "min_image_height": 20},
    )

    content = json.loads(out["data"][0])[0]["content"]
    info = json.loads(out["info"][0])
    assert content == [
        {"type": "text", "text": "A"},
        {"type": "image_url", "image_url": {"url": "images/keep.jpg"}},
        {"type": "text", "text": "B"},
    ]
    assert info["__defined__"]["links"]["images"] == [{"id": "keep.jpg"}]
    assert "image_ids" not in info
    assert info["filtered_small_images"] == 1
    assert info["format"] == "openai"


def test_filter_images_keeps_unknown_size_images() -> None:
    batch = {
        "text": {
            "id": ["1"],
            "data": [
                _payload(
                    [
                        {"type": "image_url", "image_url": {"url": "images/unknown.jpg"}},
                    ],
                ),
            ],
            "info": ['{"format":"openai","image_ids":["unknown.jpg"]}'],
        },
        "image": {
            "id": [["other.jpg"]],
            "info": [[json.dumps({"width": 10, "height": 10, "text_ids": ["other"]})]],
        },
    }

    out = _run_map(
        batch,
        {"min_image_width": 20, "min_image_height": 20},
    )

    content = json.loads(out["data"][0])[0]["content"]
    info = json.loads(out["info"][0])
    assert content == [{"type": "image_url", "image_url": {"url": "images/unknown.jpg"}}]
    assert info["__defined__"]["links"]["images"] == [{"id": "unknown.jpg"}]
    assert "image_ids" not in info
    assert "filtered_small_images" not in info


def test_filter_images_drops_image_ids_when_no_images_remain() -> None:
    batch = {
        "text": {
            "id": ["1"],
            "data": [_payload([{"type": "image_url", "image_url": {"url": "images/drop.jpg"}}])],
            "info": ['{"format":"openai","image_ids":["drop.jpg"]}'],
        },
        "image": {
            "id": [["drop.jpg"]],
            "info": [[json.dumps({"width": 10, "height": 10, "text_ids": ["1"]})]],
        },
    }

    out = _run_map(
        batch,
        {"min_image_width": 20, "min_image_height": 20},
    )

    content = json.loads(out["data"][0])[0]["content"]
    info = json.loads(out["info"][0])
    assert content == []
    assert "image_ids" not in info
    assert "__defined__" not in info or "links" not in info.get("__defined__", {})
    assert info["filtered_small_images"] == 1


def test_filter_images_uses_per_text_row_secondary_image_info() -> None:
    batch = {
        "text": {
            "id": ["1", "2"],
            "data": [
                _payload([{"type": "image_url", "image_url": {"url": "images/drop.jpg"}}]),
                _payload([{"type": "image_url", "image_url": {"url": "images/keep.jpg"}}]),
            ],
            "info": [
                '{"format":"openai","image_ids":["drop.jpg"]}',
                '{"format":"openai","image_ids":["keep.jpg"]}',
            ],
        },
        "image": {
            "id": [["drop.jpg"], ["keep.jpg"]],
            "info": [[
                json.dumps({"width": 10, "height": 10}),
            ], [
                json.dumps({"width": 100, "height": 100}),
            ]],
        },
    }

    out = _run_map(
        batch,
        {"min_image_width": 20, "min_image_height": 20},
    )

    first_content = json.loads(out["data"][0])[0]["content"]
    first_info = json.loads(out["info"][0])
    second_content = json.loads(out["data"][1])[0]["content"]
    second_info = json.loads(out["info"][1])

    assert first_content == []
    assert "image_ids" not in first_info
    assert "__defined__" not in first_info or "links" not in first_info.get("__defined__", {})
    assert first_info["filtered_small_images"] == 1

    assert second_content == [{"type": "image_url", "image_url": {"url": "images/keep.jpg"}}]
    assert second_info["__defined__"]["links"]["images"] == [{"id": "keep.jpg"}]
    assert "image_ids" not in second_info
