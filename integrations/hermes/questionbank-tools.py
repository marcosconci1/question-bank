"""Compatibility loader for the self-contained question-bank plugin tools."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_TOOLS_PATH = Path(__file__).resolve().parent / "question-bank" / "tools.py"
_SPEC = spec_from_file_location("question_bank_native_tools_compat", _TOOLS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("Unable to load the question-bank tool adapter")
_IMPLEMENTATION = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_IMPLEMENTATION)


def __getattr__(name):
    return getattr(_IMPLEMENTATION, name)
