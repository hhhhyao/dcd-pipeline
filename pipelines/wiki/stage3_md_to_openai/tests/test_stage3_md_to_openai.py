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
dcd_cli_mod = types.ModuleType("dcd_cli")
dcd_cli_mod.pipe = pipe_mod
sys.modules.setdefault("dcd_cli", dcd_cli_mod)
sys.modules.setdefault("dcd_cli.pipe", pipe_mod)

import stage3_md_to_openai as pipe_module  # noqa: E402

_extract_image_ids = pipe_module._extract_image_ids
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

    parts, dropped = _md_to_openai_content_parts(md)

    assert dropped == 2
    assert [block["type"] for block in parts] == ["text", "image_url", "text"]
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

    parts, dropped = _md_to_openai_content_parts(md)

    assert dropped == 0
    assert parts == [
        {"type": "text", "text": "A"},
        {"type": "image_url", "image_url": {"url": "images/part/hash/local.jpg"}},
        {"type": "text", "text": "B"},
    ]


def test_md_to_openai_content_parts_keeps_tiny_local_images() -> None:
    parts, dropped = _md_to_openai_content_parts("A![tiny](images/tiny.png)B")

    assert dropped == 0
    assert parts == [
        {"type": "text", "text": "A"},
        {"type": "image_url", "image_url": {"url": "images/tiny.png"}},
        {"type": "text", "text": "B"},
    ]


def test_extract_image_ids_uses_emitted_part_order() -> None:
    parts = [
        {"type": "text", "text": "A"},
        {"type": "image_url", "image_url": {"url": "images/one.png"}},
        {"type": "image_url", "image_url": {"url": "./images/two.png"}},
        {"type": "text", "text": "B"},
    ]

    assert _extract_image_ids(parts) == ["one.png", "two.png"]


def test_map_updates_info_format_counters_and_image_ids() -> None:
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
        "info": [
            json.dumps(
                {
                    "format": "md",
                    "title": "Keep Me",
                    "image_ids": ["stale"],
                    "image_refs": {"stale_ref": {}},
                    "filtered_small_images": 9,
                },
            ),
        ],
        "tags": [[]],
    }

    out = pipe_map(
        batch,
        PipeContext(
            dataset="demo",
            config={"message_role": "user"},
        ),
    )

    payload = json.loads(out["data"][0])
    info = json.loads(out["info"][0])

    assert info["format"] == "openai"
    assert info["title"] == "Keep Me"
    assert info["image_ids"] == [
        "part/hash/local.jpg",
        "tiny.png",
        "part/hash/wrapped.jpg",
    ]
    assert "image_refs" not in info
    assert "filtered_small_images" not in info
    assert info["dropped_nonlocal_images"] == 2
    assert isinstance(payload, list)
    assert payload[0]["role"] == "user"
    parts = payload[0]["content"]
    assert [block["image_url"]["url"] for block in parts if block["type"] == "image_url"] == [
        "images/part/hash/local.jpg",
        "images/tiny.png",
        "images/part/hash/wrapped.jpg",
    ]
    assert "title:" not in parts[0]["text"]
    assert "local" not in "".join(
        block.get("text", "") for block in parts if block["type"] == "text"
    )
    assert "Done" in parts[-1]["text"]


def test_map_drops_empty_image_ids_when_no_local_images_survive() -> None:
    batch = {
        "id": ["1"],
        "data": ["![remote](https://example.com/remote.jpg)"],
        "info": ['{"format": "md", "image_ids": ["stale"], "image_refs": {"stale": {}}}'],
        "tags": [[]],
    }

    out = pipe_map(batch, PipeContext())
    info = json.loads(out["info"][0])

    assert "image_ids" not in info
    assert "image_refs" not in info
    assert info["dropped_nonlocal_images"] == 1
