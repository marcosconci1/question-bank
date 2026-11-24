"""Installed-wheel regression coverage for built-in import profiles."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, f"Command failed: {command!r}\n{result.stdout}\n{result.stderr}"
    return result


def test_built_wheel_contains_and_loads_builtin_profiles(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required for the installed-wheel regression test"

    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["UV_CACHE_DIR"] = str(tmp_path / "uv-cache")
    source_dir = tmp_path / "source"
    shutil.copytree(REPOSITORY_ROOT / "src", source_dir / "src")
    for filename in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(REPOSITORY_ROOT / filename, source_dir / filename)

    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    _run(
        [
            sys.executable,
            "-c",
            "import sys; from setuptools.build_meta import build_wheel; build_wheel(sys.argv[1])",
            str(wheel_dir),
        ],
        cwd=source_dir,
        env=env,
    )
    wheels = list(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1

    environment_dir = tmp_path / "installed"
    _run([uv, "venv", "--python", sys.executable, str(environment_dir)], cwd=tmp_path, env=env)
    interpreter = environment_dir / "bin" / "python"
    if sys.platform == "win32":
        interpreter = environment_dir / "Scripts" / "python.exe"
    _run(
        [uv, "pip", "install", "--offline", "--no-deps", "--python", str(interpreter), str(wheels[0])],
        cwd=tmp_path,
        env=env,
    )

    script = r'''
import csv
from pathlib import Path
from tempfile import TemporaryDirectory

from question_bank.ingest.csv_adapter import CsvAdapter
from question_bank.ingest.manifest import Source
from question_bank.ingest.profiles import list_profiles, load_profile

expected = ["cesgranrio", "enade", "fcpc", "fgv", "iades", "poscomp"]
actual = list_profiles()
assert actual == expected, actual
for name in expected:
    assert load_profile(name).name == name
assert load_profile("poscomp.toml").name == "poscomp"

profile = load_profile("poscomp")
with TemporaryDirectory() as directory:
    root = Path(directory)
    custom = root / "custom.toml"
    custom.write_text('name = "custom"\nkind = "csv"\nexam = "custom"\n', encoding="utf-8")
    custom_dir = root / "profiles"
    custom_dir.mkdir()
    (custom_dir / "only-here.toml").write_text(
        'name = "only-here"\nkind = "json"\nexam = "custom"\n', encoding="utf-8"
    )
    assert load_profile(custom).name == "custom"
    assert list_profiles(custom_dir) == ["only-here"]
    assert load_profile("only-here", profiles_dir=custom_dir).name == "only-here"
    assert load_profile("only-here.toml", profiles_dir=custom_dir).name == "only-here"
    missing_dir = root / "missing-profiles"
    assert list_profiles(missing_dir) == []
    try:
        load_profile("poscomp", profiles_dir=missing_dir)
    except ValueError as error:
        assert "Unknown import profile" in str(error) and "available: none" in str(error)
    else:
        raise AssertionError("built-in profile unexpectedly bypassed the override directory")
    try:
        load_profile("missing-profile", profiles_dir=custom_dir)
    except ValueError as error:
        assert "Unknown import profile" in str(error)
    else:
        raise AssertionError("unknown profile was accepted")

    malformed = root / "malformed.toml"
    malformed.write_text('name = "broken"\nkind = [\n', encoding="utf-8")
    try:
        load_profile(malformed)
    except ValueError as error:
        assert "Could not parse profile" in str(error)
    else:
        raise AssertionError("malformed custom TOML was accepted")

    csv_path = root / "poscomp.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "number", "stem", "options", "key", "knowledge_area", "area", "subarea"])
        writer.writerow([
            "fixture-1", 1, "Which structure maps keys to values?",
            repr(["A) List", "B) Hash table", "C) Stack", "D) Queue", "E) Tree"]),
            "B", "Computer Science", "Data Structures", "Hashing",
        ])
    source = Source(
        id="poscomp-fixture",
        kind=profile.kind,
        path=csv_path,
        exam=profile.exam,
        year=2024,
        options=profile.options,
    )
    rows = list(CsvAdapter().read(source))
    assert len(rows) == 1
    assert rows[0]["id"] == "poscomp-fixture-1"
    assert rows[0]["answer"] == "B"
    assert rows[0]["options"][1] == "Hash table"
'''
    _run([str(interpreter), "-c", script], cwd=tmp_path, env=env)
