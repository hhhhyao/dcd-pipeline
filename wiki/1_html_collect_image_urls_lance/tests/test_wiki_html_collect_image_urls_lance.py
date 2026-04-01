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
    alias="test_1_html_collect_image_urls_lance_pkg",
)
_extract_html_image_urls = pipe_module._extract_html_image_urls
_pick_image_id = pipe_module._pick_image_id
pipe_map = pipe_module.map


def test_extract_html_image_urls_preserves_order_and_duplicates() -> None:
    html = (
        '<img src="https://a/1.jpg">'
        '<div></div>'
        '<img alt="x" src="https://a/2.jpg">'
        '<img src="https://a/1.jpg">'
    )
    assert _extract_html_image_urls(html) == [
        "https://a/1.jpg",
        "https://a/2.jpg",
        "https://a/1.jpg",
    ]


def test_pick_image_id_prefers_existing_row_image_ids() -> None:
    candidates = ["img_b", "img_a", "img_c"]
    preferred = ["img_x", "img_a", "img_b"]
    assert _pick_image_id(candidates, preferred) == "img_a"


def test_map_writes_html_images() -> None:
    batch = {
        "id": ["1"],
        "data": ['<img src="https://upload.wikimedia.org/a.jpg"><img src="https://x/b.jpg">'],
        "info": ['{"format":"html","image_ids":["img_local_2","img_local_1"]}'],
        "tags": [[]],
    }
    lookup = {
        "upload.wikimedia.org/a.jpg": ["img_local_1", "img_local_2"],
    }
    with patch.object(pipe_module, "_load_image_url_candidates", return_value=lookup):
        out = pipe_map(
            batch,
            PipeContext(dataset_dir=".", config={"dataset_dir": "."}),
        )
    info = json.loads(out["info"][0])
    assert info["html_images"] == [
        {
            "image_url_raw": "https://upload.wikimedia.org/a.jpg",
            "image_url_normalized": "upload.wikimedia.org/a.jpg",
            "matched": True,
            "matched_image_id": "img_local_2",
        },
        {
            "image_url_raw": "https://x/b.jpg",
            "image_url_normalized": "x/b.jpg",
            "matched": False,
            "matched_image_id": None,
        },
    ]
