"""Public module exports for the ingest pipe."""

from __future__ import annotations

import importlib.util
from pathlib import Path

try:
    from .main import (
        DEFAULT_LOG_INTERVAL,
        IMAGE_LABELS_SCHEMA,
        IMAGES_SCHEMA,
        TEXT_SCHEMA,
        build_image_info,
        build_image_ref,
        build_image_ref_id,
        build_text_info,
        compact_lance,
        extract_html_meta,
        ingest,
        main,
        normalize_url,
        rewrite_html_images,
        run_streaming,
    )
except ImportError:  # pragma: no cover - pytest package collection fallback
    _main_path = Path(__file__).with_name("main.py")
    _spec = importlib.util.spec_from_file_location(
        "stage0_ingest_main_fallback",
        _main_path,
    )
    if _spec is None or _spec.loader is None:
        raise
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)

    DEFAULT_LOG_INTERVAL = _mod.DEFAULT_LOG_INTERVAL
    IMAGE_LABELS_SCHEMA = _mod.IMAGE_LABELS_SCHEMA
    IMAGES_SCHEMA = _mod.IMAGES_SCHEMA
    TEXT_SCHEMA = _mod.TEXT_SCHEMA
    build_image_info = _mod.build_image_info
    build_image_ref = _mod.build_image_ref
    build_image_ref_id = _mod.build_image_ref_id
    build_text_info = _mod.build_text_info
    compact_lance = _mod.compact_lance
    extract_html_meta = _mod.extract_html_meta
    ingest = _mod.ingest
    main = _mod.main
    normalize_url = _mod.normalize_url
    rewrite_html_images = _mod.rewrite_html_images
    run_streaming = _mod.run_streaming

__all__ = ["ingest"]
