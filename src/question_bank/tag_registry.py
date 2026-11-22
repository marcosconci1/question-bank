"""Locate the bank's tag registry or the default included in the package."""

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path


def bundled_tags() -> Traversable:
    return files("question_bank").joinpath("tags.md")


def resolve_tags(root: Path) -> Traversable:
    bank_tags = root / "docs" / "tags.md"
    return bank_tags if bank_tags.is_file() else bundled_tags()
