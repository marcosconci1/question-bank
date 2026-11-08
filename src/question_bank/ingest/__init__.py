"""Generic ingestion adapters and pipeline for question sources."""

from .adapter import SourceAdapter
from .manifest import Source, load_manifest

__all__ = ["Source", "SourceAdapter", "load_manifest"]
