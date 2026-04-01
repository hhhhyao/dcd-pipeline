"""Metadata extraction subpackage."""

from .page import PageMeta, extract_meta
from .wiki import extract_wiki_meta

__all__ = [
    "PageMeta",
    "extract_meta",
    "extract_wiki_meta",
]
