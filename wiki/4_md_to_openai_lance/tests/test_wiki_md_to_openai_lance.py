from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pipe_mod = types.ModuleType("dcd_cli.pipe")


class PipeContext:
    def __init__(self, dataset_dir=None, config=None) -> None:
        self.dataset_dir = dataset_dir
        self.config = config or {}

    def set_progress(self, _value: int) -> None:
        return None


pipe_mod.PipeContext = PipeContext
dcd_cli_mod = types.ModuleType("dcd_cli")
dcd_cli_mod.pipe = pipe_mod
sys.modules.setdefault("dcd_cli", dcd_cli_mod)
sys.modules.setdefault("dcd_cli.pipe", pipe_mod)

from wiki._module_loader import load_pipe_package  # noqa: E402

pipe_module = load_pipe_package(
    Path(__file__).resolve().parents[1],
    alias="test_4_md_to_openai_lance_pkg",
)
_md_to_openai_content_parts = pipe_module._md_to_openai_content_parts
_parse_local_image_id = pipe_module._parse_local_image_id
_strip_front_matter = pipe_module._strip_front_matter
pipe_map = pipe_module.map


def test_strip_front_matter_removes_only_leading_block() -> None:
    md = (
        "---\n"
        "title: Demo\n"
        "url: https://example.com\n"
        "---\n\n"
        "Body\n\n"
        "---\n"
        "Still body\n"
    )

    assert _strip_front_matter(md) == "Body\n\n---\nStill body\n"


def test_parse_local_image_id_keeps_nested_image_path() -> None:
    href = "./images/part2026-03-20-00000/hash/file.jpg?width=100#frag"
    assert _parse_local_image_id(href) == "part2026-03-20-00000/hash/file.jpg"


def test_md_to_openai_content_parts_handles_wrapped_local_and_drops_remote() -> None:
    md = (
        "---\n"
        "title: Demo\n"
        "---\n\n"
        "Alpha\n"
        "[![wrapped](images/part/hash/local.jpg)](https://example.com/page)\n"
        "Beta\n"
        "![remote](https://example.com/remote.jpg)\n"
        "[![remote2](//upload.wikimedia.org/x.png)](https://example.com/file)\n"
        "Omega\n"
    )

    parts, filtered, dropped = _md_to_openai_content_parts(
        md,
        max_small_area=0,
        label_sizes={},
    )

    assert filtered == 0
    assert dropped == 2
    assert [b["type"] for b in parts] == ["text", "image_url", "text"]
    assert parts[0]["text"].startswith("Alpha\n")
    assert "title:" not in parts[0]["text"]
    assert parts[1] == {
        "type": "image_url",
        "image_url": {"url": "images/part/hash/local.jpg"},
    }
    assert "Omega" in parts[2]["text"]


def test_md_to_openai_content_parts_handles_wrapped_local_with_parentheses_in_outer_url() -> None:
    md = (
        "A"
        "[![wrapped](images/part/hash/local.jpg)]"
        "(https://en.wikipedia.org/wiki/File:Name_(Author)_09.jpg)"
        "B"
    )

    parts, filtered, dropped = _md_to_openai_content_parts(
        md,
        max_small_area=0,
        label_sizes={},
    )

    assert filtered == 0
    assert dropped == 0
    assert parts == [
        {"type": "text", "text": "A"},
        {"type": "image_url", "image_url": {"url": "images/part/hash/local.jpg"}},
        {"type": "text", "text": "B"},
    ]


def test_md_to_openai_content_parts_filters_small_local_images() -> None:
    parts, filtered, dropped = _md_to_openai_content_parts(
        "A![tiny](images/tiny.png)B",
        max_small_area=100,
        label_sizes={"tiny.png": (10, 10)},
    )

    assert filtered == 1
    assert dropped == 0
    assert parts == [{"type": "text", "text": "AB"}]


def test_map_updates_info_format_and_counters() -> None:
    batch = {
        "id": ["1"],
        "data": [
            "---\n"
            "title: Demo\n"
            "---\n\n"
            "Intro\n"
            "![local](images/part/hash/local.jpg)\n"
            "![tiny](images/tiny.png)\n"
            "![remote](https://example.com/remote.jpg)\n"
            "[![wrapped](images/part/hash/wrapped.jpg)](https://example.com/page)\n"
            "[![remote2](//upload.wikimedia.org/x.png)](https://example.com/file)\n"
            "Done\n"
        ],
        "info": ['{"format": "md", "title": "Keep Me", "image_ids": ["x"]}'],
        "tags": [[]],
    }

    with patch.object(
        pipe_module,
        "_load_label_sizes",
        return_value={"tiny.png": (10, 10)},
    ):
        out = pipe_map(
            batch,
            PipeContext(
                dataset_dir=".",
                config={
                    "max_small_area": 100,
                    "dataset_dir": ".",
                },
            ),
        )

    payload = json.loads(out["data"][0])
    info = json.loads(out["info"][0])

    assert info["format"] == "openai"
    assert info["title"] == "Keep Me"
    assert info["image_ids"] == ["x"]
    assert info["filtered_small_images"] == 1
    assert info["dropped_nonlocal_images"] == 2
    assert list(payload) == ["messages"]
    assert payload["messages"][0]["role"] == "user"
    parts = payload["messages"][0]["content"]
    assert [b["image_url"]["url"] for b in parts if b["type"] == "image_url"] == [
        "images/part/hash/local.jpg",
        "images/part/hash/wrapped.jpg",
    ]
    assert "title:" not in parts[0]["text"]
    assert "Done" in parts[-1]["text"]
