from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path


PIPE_PARENT = Path(__file__).resolve().parents[2]
PIPE_PARENT_REL = os.path.relpath(PIPE_PARENT, Path.cwd())
if PIPE_PARENT_REL not in sys.path:
    sys.path.insert(0, PIPE_PARENT_REL)

pipe_mod = types.ModuleType("dcd_cli.pipe")


class PipeContext:
    def __init__(self, dataset="demo", config=None, volumes=None) -> None:
        self.dataset = dataset
        self.config = config or {}
        self.volumes = volumes

    def set_progress(self, _value: int) -> None:
        return None


pipe_mod.PipeContext = PipeContext
pipe_mod.Batch = dict
pipe_mod.MultimodalBatch = dict
dcd_cli_mod = types.ModuleType("dcd_cli")
dcd_cli_mod.pipe = pipe_mod
sys.modules.setdefault("dcd_cli", dcd_cli_mod)
sys.modules.setdefault("dcd_cli.pipe", pipe_mod)

import stage4_filter_images as pipe_module  # noqa: E402


def _payload(content):
    return json.dumps([{"role": "user", "content": content}], ensure_ascii=False)


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
            "label_data": [
                json.dumps({
                    "id": "keep.jpg",
                    "info": {"width": 100, "height": 100, "text_ids": ["1"]},
                }),
                json.dumps({
                    "id": "drop.jpg",
                    "info": {"width": 10, "height": 10, "text_ids": ["1"]},
                }),
            ],
        },
    }

    out = pipe_module.map(
        batch,
        PipeContext(config={"min_image_width": 20, "min_image_height": 20}),
    )

    content = json.loads(out["data"][0])[0]["content"]
    info = json.loads(out["info"][0])
    assert content == [
        {"type": "text", "text": "A"},
        {"type": "image_url", "image_url": {"url": "images/keep.jpg"}},
        {"type": "text", "text": "B"},
    ]
    assert info["image_ids"] == ["keep.jpg"]
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
            "label_data": [
                json.dumps({
                    "id": "other.jpg",
                    "info": {"width": 10, "height": 10, "text_ids": ["other"]},
                }),
            ],
        },
    }

    out = pipe_module.map(
        batch,
        PipeContext(config={"min_image_width": 20, "min_image_height": 20}),
    )

    content = json.loads(out["data"][0])[0]["content"]
    info = json.loads(out["info"][0])
    assert content == [{"type": "image_url", "image_url": {"url": "images/unknown.jpg"}}]
    assert info["image_ids"] == ["unknown.jpg"]
    assert "filtered_small_images" not in info


def test_filter_images_drops_image_ids_when_no_images_remain() -> None:
    batch = {
        "text": {
            "id": ["1"],
            "data": [_payload([{"type": "image_url", "image_url": {"url": "images/drop.jpg"}}])],
            "info": ['{"format":"openai","image_ids":["drop.jpg"]}'],
        },
        "image": {
            "label_data": [
                json.dumps({
                    "id": "drop.jpg",
                    "info": {"width": 10, "height": 10, "text_ids": ["1"]},
                }),
            ],
        },
    }

    out = pipe_module.map(
        batch,
        PipeContext(config={"min_image_width": 20, "min_image_height": 20}),
    )

    content = json.loads(out["data"][0])[0]["content"]
    info = json.loads(out["info"][0])
    assert content == []
    assert "image_ids" not in info
    assert info["filtered_small_images"] == 1


def test_filter_images_reads_label_data_records_with_json_info() -> None:
    batch = {
        "text": {
            "id": ["1"],
            "data": [
                _payload([
                    {"type": "image_url", "image_url": {"url": "images/drop.jpg"}},
                ]),
            ],
            "info": ['{"format":"openai","image_ids":["drop.jpg"]}'],
        },
        "image": {
            "label_data": [
                json.dumps({
                    "id": "drop.jpg",
                    "info": json.dumps({"width": 10, "height": 10}),
                }),
            ],
        },
    }

    out = pipe_module.map(
        batch,
        PipeContext(config={"min_image_width": 20, "min_image_height": 20}),
    )

    content = json.loads(out["data"][0])[0]["content"]
    info = json.loads(out["info"][0])
    assert content == []
    assert "image_ids" not in info
    assert info["filtered_small_images"] == 1
