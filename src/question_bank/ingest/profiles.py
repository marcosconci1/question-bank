"""Declarative TOML import profiles for exam boards and tabular dumps."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .manifest import Source, normalize_board_options

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "profiles" / "examples"
VALID_KINDS = frozenset({"csv", "json", "pdf-board", "pdf-llm"})


@dataclass(frozen=True)
class IngestProfile:
    """Declarative ingestion profile parsed from a TOML file."""

    name: str
    kind: str
    exam: str
    description: str = ""
    options: dict[str, Any] = field(default_factory=dict)


def list_profiles(profiles_dir: Path | None = None) -> list[str]:
    """Return available built-in profile names in sorted order."""
    if profiles_dir is not None:
        if not profiles_dir.is_dir():
            return []
        return sorted(path.stem for path in profiles_dir.glob("*.toml"))
    return sorted(
        resource.name.removesuffix(".toml")
        for resource in resources.files(__package__).joinpath("profiles").iterdir()
        if resource.is_file() and resource.name.endswith(".toml")
    )


def resolve_profile_path(name_or_path: str, profiles_dir: Path | None = None) -> Path:
    """Resolve an explicit TOML path or a named built-in profile (or override in profiles_dir)."""
    candidate = Path(name_or_path).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    filename = name_or_path if name_or_path.endswith(".toml") else f"{name_or_path}.toml"
    if profiles_dir is not None:
        named = profiles_dir / filename
    else:
        named = Path(str(resources.files(__package__).joinpath("profiles", filename)))
    if named.is_file():
        return named.resolve()
    available = ", ".join(list_profiles(profiles_dir)) or "none"
    raise ValueError(f"Unknown import profile {name_or_path!r} (available: {available})")


def load_profile(name_or_path: str | Path, profiles_dir: Path | None = None) -> IngestProfile:
    """Load and validate a TOML import profile."""
    path = (
        name_or_path.expanduser().resolve()
        if isinstance(name_or_path, Path)
        else resolve_profile_path(name_or_path, profiles_dir=profiles_dir)
    )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Could not parse profile {path}: {exc}") from exc

    name = raw.get("name")
    kind = raw.get("kind")
    exam = raw.get("exam")
    description = raw.get("description", "")
    options = raw.get("options", {})

    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Profile {path} requires a non-empty string 'name'")
    if kind not in VALID_KINDS:
        raise ValueError(f"Profile {path} has unsupported kind {kind!r}")
    if not isinstance(exam, str) or not exam.strip():
        raise ValueError(f"Profile {path} requires a non-empty string 'exam'")
    if not isinstance(description, str):
        raise ValueError(f"Profile {path} 'description' must be a string")
    if not isinstance(options, dict):
        raise ValueError(f"Profile {path} '[options]' must be a table")

    return IngestProfile(
        name=name.strip(),
        kind=kind,
        exam=exam.strip().lower(),
        description=description.strip(),
        options=dict(options),
    )


def build_source_from_profile(
    profile: IngestProfile,
    source_path: Path,
    *,
    year: int,
    exam: str | None = None,
    source_id: str | None = None,
    extra_options: dict[str, Any] | None = None,
) -> Source:
    """Build a pipeline ``Source`` by combining a TOML profile with CLI overrides."""
    profile_options = profile.options
    if profile.kind == "pdf-board":
        profile_options = normalize_board_options(profile_options)
    merged_options = {**profile_options, **(extra_options or {})}
    resolved_exam = (exam or profile.exam).strip().lower()
    resolved_id = (source_id or f"{profile.name}-{source_path.stem}").strip()
    return Source(
        id=resolved_id,
        kind=profile.kind,
        path=source_path.expanduser().resolve(),
        exam=resolved_exam,
        year=year,
        options=merged_options,
    )
