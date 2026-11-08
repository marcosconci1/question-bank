"""Small protocol shared by source-specific ingestion adapters."""

from collections.abc import Iterable
from typing import Any, Protocol

from .manifest import Source


class SourceAdapter(Protocol):
    """Read one configured source and yield bank-shaped candidate records.

    Adapters only transform source data. Validation, duplicate handling, and
    writes are owned by the ingestion pipeline.
    """

    def read(self, source: Source) -> Iterable[dict[str, Any]]:
        """Yield candidate question dictionaries for ``source``."""
