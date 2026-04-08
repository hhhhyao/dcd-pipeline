from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch


PIPE_PARENT = Path(__file__).resolve().parents[2]
PIPE_PARENT_REL = os.path.relpath(PIPE_PARENT, Path.cwd())
if PIPE_PARENT_REL not in sys.path:
    sys.path.insert(0, PIPE_PARENT_REL)

pipe_mod = types.ModuleType("dcd_cli.pipe")


class PipeContext:
    def __init__(self, dataset="demo", dataset_dir=None, config=None, volumes=None) -> None:
        self.dataset = dataset
        self.dataset_dir = dataset_dir
        self.config = config or {}
        self.volumes = volumes

    def set_progress(self, _value: int) -> None:
        return None


pipe_mod.PipeContext = PipeContext
dcd_cli_mod = types.ModuleType("dcd_cli")
dcd_cli_mod.pipe = pipe_mod
sys.modules.setdefault("dcd_cli", dcd_cli_mod)
sys.modules.setdefault("dcd_cli.pipe", pipe_mod)

import stage1_html_localize_image_ids as pipe_module  # noqa: E402

_build_match_map = pipe_module._build_match_map
_rewrite_html_with_match_map = pipe_module._rewrite_html_with_match_map
pipe_map = pipe_module.map


def test_build_match_map_uses_image_ids_order_for_conflicts() -> None:
    raw_url_to_image_id, conflict_count = _build_match_map(
        ["img_b", "img_a"],
        {
            "img_a": ["upload.wikimedia.org/shared.jpg"],
            "img_b": ["upload.wikimedia.org/shared.jpg"],
        },
    )
    assert raw_url_to_image_id == {
        "upload.wikimedia.org/shared.jpg": "img_b",
    }
    assert conflict_count == 1


def test_rewrite_html_with_match_map_normalizes_src_and_strips_srcset() -> None:
    html = (
        '<img src="https://upload.wikimedia.org/thumb/a/b/c.jpg/120px-c.jpg" srcset="x 1x">'
        '<img src="https://example.com/keep.jpg">'
    )
    out, used_image_ids = _rewrite_html_with_match_map(
        html,
        {"upload.wikimedia.org/a/b/c.jpg": "img_c"},
    )
    assert 'src="images/img_c"' in out
    assert "srcset=" not in out
    assert 'src="https://example.com/keep.jpg"' in out
    assert used_image_ids == ["img_c"]


def test_map_rewrites_only_existing_image_ids_without_supplementing() -> None:
    batch = {
        "id": ["1"],
        "data": [
            (
                '<img src="https://upload.wikimedia.org/a.jpg">'
                '<img src="https://upload.wikimedia.org/b.jpg">'
            ),
        ],
        "info": [json.dumps({
            "format": "html",
            "title": "Example",
            "image_ids": ["img_a"],
            "html_images": [{"stale": True}],
        })],
        "tags": [[]],
    }
    with patch.object(
        pipe_module,
        "_get_image_id_to_urls",
        return_value={
            "img_a": ["upload.wikimedia.org/a.jpg"],
            "img_b": ["upload.wikimedia.org/b.jpg"],
        },
    ):
        out = pipe_map(batch, PipeContext())

    info = json.loads(out["info"][0])
    assert info["format"] == "html"
    assert info["title"] == "Example"
    assert info["image_ids"] == ["img_a"]
    assert "html_images" not in info
    assert 'src="images/img_a"' in out["data"][0]
    assert 'src="https://upload.wikimedia.org/b.jpg"' in out["data"][0]


def test_map_drops_image_ids_when_no_html_image_was_rewritten() -> None:
    batch = {
        "id": ["1"],
        "data": ['<img src="https://upload.wikimedia.org/not-found.jpg">'],
        "info": [json.dumps({
            "format": "html",
            "image_ids": ["img_a"],
        })],
        "tags": [[]],
    }
    with patch.object(
        pipe_module,
        "_get_image_id_to_urls",
        return_value={"img_a": ["upload.wikimedia.org/a.jpg"]},
    ):
        out = pipe_map(batch, PipeContext())

    info = json.loads(out["info"][0])
    assert "image_ids" not in info
    assert 'src="https://upload.wikimedia.org/not-found.jpg"' in out["data"][0]
