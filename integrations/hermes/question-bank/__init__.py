"""Study-profile question-bank plugin and bundled practice skill."""

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
    ctx.register_skill(
        "question-practice",
        Path(__file__).resolve().parent / "skills" / "question-practice" / "SKILL.md",
    )
