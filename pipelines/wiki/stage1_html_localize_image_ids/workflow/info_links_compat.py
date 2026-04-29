"""Compatibility wrapper for DCD canonical cross-modality info links."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

try:
    from dcd_cli.pipe import get_links, iter_link_modalities, set_links
except ImportError:  # pragma: no cover - older local dcd package fallback

    _LEGACY_ROOTS = {
        "images": "image",
        "videos": "video",
        "pdfs": "pdf",
        "folders": "folder",
        "meshes": "mesh",
        "point_clouds": "point_cloud",
    }

    def _legacy_key(modality: str) -> str:
        return f"{_LEGACY_ROOTS.get(modality, modality)}_ids"

    def _coerce_entry(item: Any) -> dict[str, Any] | None:
        if isinstance(item, dict):
            raw_id = item.get("id")
            if raw_id is None:
                return None
            entry = dict(item)
            entry["id"] = str(raw_id)
            return entry
        if item is None:
            return None
        return {"id": str(item)}

    def _coerce_entries(items: Any) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            return []
        entries: list[dict[str, Any]] = []
        for item in items:
            entry = _coerce_entry(item)
            if entry is not None:
                entries.append(entry)
        return entries

    def get_links(info: dict[str, Any] | None, modality: str) -> list[dict[str, Any]]:
        if not info:
            return []
        defined = info.get("__defined__")
        if isinstance(defined, dict):
            links = defined.get("links")
            if isinstance(links, dict):
                entries = _coerce_entries(links.get(modality))
                if entries:
                    return entries
        legacy = info.get(_legacy_key(modality))
        return _coerce_entries(legacy)

    def set_links(info: dict[str, Any], modality: str, items: list[Any]) -> None:
        entries = [entry for item in items if (entry := _coerce_entry(item)) is not None]
        defined = info.setdefault("__defined__", {})
        if not isinstance(defined, dict):
            defined = {}
            info["__defined__"] = defined
        links = defined.setdefault("links", {})
        if not isinstance(links, dict):
            links = {}
            defined["links"] = links
        if entries:
            links[modality] = entries
        else:
            links.pop(modality, None)
            if not links:
                defined.pop("links", None)
                if not defined:
                    info.pop("__defined__", None)

    def iter_link_modalities(
        info: dict[str, Any] | None,
    ) -> Iterator[tuple[str, list[dict[str, Any]]]]:
        if not info:
            return
        seen: set[str] = set()
        defined = info.get("__defined__")
        if isinstance(defined, dict):
            links = defined.get("links")
            if isinstance(links, dict):
                for modality, raw_entries in links.items():
                    entries = _coerce_entries(raw_entries)
                    if entries:
                        seen.add(str(modality))
                        yield str(modality), entries
        for modality in [
            "images",
            "videos",
            "pdfs",
            "folders",
            "meshes",
            "point_clouds",
            "text",
            "audio",
            "rgbd",
            "pano",
        ]:
            if modality in seen:
                continue
            entries = _coerce_entries(info.get(_legacy_key(modality)))
            if entries:
                yield modality, entries
