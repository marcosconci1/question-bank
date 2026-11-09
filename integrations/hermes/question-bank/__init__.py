"""Portable native question-bank plugin and bundled practice skills."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_tools():
    tools_path = Path(__file__).resolve().parent / "tools.py"
    spec = spec_from_file_location("question_bank_native_tools", tools_path)
    if spec is None or spec.loader is None:
        raise ImportError("Unable to load the question-bank tool adapter")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tools = _load_tools()


def register(ctx):
    tools.register(ctx)
    for name in ("question-practice", "exercise-list"):
        ctx.register_skill(name, Path(__file__).resolve().parent / "skills" / name / "SKILL.md")
