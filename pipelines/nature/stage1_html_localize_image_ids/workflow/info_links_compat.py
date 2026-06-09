"""Compatibility wrapper for DCD canonical cross-modality info links."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

try:  # pragma: no cover - depends on the server-side DCD SDK version
    from dcd_cli.pipe import get_links as _dcd_get_links
    from dcd_cli.pipe import iter_link_modalities as _dcd_iter_link_modalities
    from dcd_cli.pipe import set_links as _dcd_set_links
except ImportError:  # pragma: no cover - older local dcd package fallback
    _dcd_get_links = None
    _dcd_iter_link_modalities = None
    _dcd_set_links = None


_LEGACY_ROOTS = {
    "images": "image",
    "videos": "video",
    "pdfs": "pdf",
    "folders": "folder",
    "meshes": "mesh",
    "point_clouds": "point_cloud",
}
_ALIASES = {
    "images": "image",
    "image": "images",
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


def _links_dict(info: dict[str, Any] | None) -> dict[str, Any]:
    if not info:
        return {}
    defined = info.get("__defined__")
    if not isinstance(defined, dict):
        return {}
    links = defined.get("links")
    return links if isinstance(links, dict) else {}


def get_links(info: dict[str, Any] | None, modality: str) -> list[dict[str, Any]]:
    if not info:
        return []
    if _dcd_get_links is not None:
        entries = _coerce_entries(_dcd_get_links(info, modality))
        if entries:
            return entries
    links = _links_dict(info)
    for key in (modality, _ALIASES.get(modality, "")):
        entries = _coerce_entries(links.get(key))
        if entries:
            return entries
    legacy = info.get(_legacy_key(modality))
    return _coerce_entries(legacy)


def set_links(info: dict[str, Any], modality: str, items: list[Any]) -> None:
    entries = [entry for item in items if (entry := _coerce_entry(item)) is not None]
    if _dcd_set_links is not None:
        updated = _dcd_set_links(info, modality, entries)
        if isinstance(updated, dict) and updated is not info:
            info.clear()
            info.update(updated)

    defined = info.setdefault("__defined__", {})
    if not isinstance(defined, dict):
        defined = {}
        info["__defined__"] = defined
    links = defined.setdefault("links", {})
    if not isinstance(links, dict):
        links = {}
        defined["links"] = links

    keys = [modality]
    alias = _ALIASES.get(modality)
    if alias:
        keys.append(alias)
    for key in keys:
        if entries:
            links[key] = entries
        else:
            links.pop(key, None)

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
    if _dcd_iter_link_modalities is not None:
        for modality, raw_entries in _dcd_iter_link_modalities(info):
            entries = _coerce_entries(raw_entries)
            if entries:
                seen.add(str(modality))
                yield str(modality), entries
    for modality, raw_entries in _links_dict(info).items():
        if modality in seen:
            continue
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
