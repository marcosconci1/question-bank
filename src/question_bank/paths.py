"""Bank root resolution shared by every entry point.

The bank (questions, assets, corrections, answer logs, raw sources) lives
outside the engine repo. Resolution order:

1. ``QUESTION_BANK_ROOT`` (explicit override; what the Study profile sets)
2. ``$XDG_DATA_HOME/question-bank`` (default bank location)
"""
import os
from pathlib import Path


def default_bank_root() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return (Path(data_home) / "question-bank").resolve()


def resolve_bank_root() -> Path:
    env = os.environ.get("QUESTION_BANK_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return default_bank_root()