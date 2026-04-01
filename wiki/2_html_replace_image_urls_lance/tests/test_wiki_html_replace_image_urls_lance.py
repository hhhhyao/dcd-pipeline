from __future__ import annotations

import json
import sys
import types
from pathlib import Path


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
    alias="test_2_html_replace_image_urls_lance_pkg",
)
_build_match_map = pipe_module._build_match_map
_rewrite_html_with_match_map = pipe_module._rewrite_html_with_match_map
pipe_map = pipe_module.map


def test_rewrite_html_with_match_map_rewrites_only_matched_and_strips_srcset() -> None:
    html = (
        '<img src="https://upload.wikimedia.org/a.jpg" srcset="x 1x">'
        '<img src="https://example.com/b.jpg">'
    )
    matches = [
        {"image_url_raw": "https://upload.wikimedia.org/a.jpg", "matched_image_id": "img_a"},
        {"image_url_raw": "https://example.com/b.jpg", "matched_image_id": None},
    ]
    match_map, conflict_count = _build_match_map(matches)
    out, used_image_ids = _rewrite_html_with_match_map(html, match_map)
    assert conflict_count == 0
    assert 'src="images/img_a"' in out
    assert "srcset=" not in out
    assert 'src="https://example.com/b.jpg"' in out
    assert used_image_ids == ["img_a"]


def test_map_rewrites_html_and_updates_image_ids() -> None:
    batch = {
        "id": ["1"],
        "data": ['<img src="https://a/1.jpg"><img src="https://a/2.jpg"><img src="https://a/1.jpg">'],
        "info": [json.dumps({
            "format": "html",
            "html_images": [
                {"image_url_raw": "https://a/1.jpg", "matched_image_id": "img_1"},
                {"image_url_raw": "https://a/2.jpg", "matched_image_id": None},
                {"image_url_raw": "https://a/1.jpg", "matched_image_id": "img_1"},
            ],
        })],
        "tags": [[]],
    }
    out = pipe_map(batch, PipeContext())
    info = json.loads(out["info"][0])
    assert info["image_ids"] == ["img_1"]
    assert "html_images" not in info
    assert 'src="images/img_1"' in out["data"][0]
    assert 'src="https://a/2.jpg"' in out["data"][0]


def test_map_logs_warning_and_keeps_first_match_on_conflict(caplog) -> None:
    batch = {
        "id": ["1"],
        "data": ['<img src="https://a/1.jpg">'],
        "info": [json.dumps({
            "format": "html",
            "html_images": [
                {"image_url_raw": "https://a/1.jpg", "matched_image_id": "img_1"},
                {"image_url_raw": "https://a/1.jpg", "matched_image_id": "img_conflict"},
            ],
        })],
        "tags": [[]],
    }
    with caplog.at_level("WARNING"):
        out = pipe_map(batch, PipeContext())
    info = json.loads(out["info"][0])
    assert info["image_ids"] == ["img_1"]
    assert 'src="images/img_1"' in out["data"][0]
    assert any("raw-url conflict" in message for message in caplog.messages)
