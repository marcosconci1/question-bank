import json
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_versions_are_consistent():
    with (ROOT / "pyproject.toml").open("rb") as file:
        project_version = tomllib.load(file)["project"]["version"]

    with (ROOT / "uv.lock").open("rb") as file:
        lock_data = tomllib.load(file)
    search_package = next(
        package for package in lock_data["package"] if package["name"] == "question-search"
    )

    claude_version = json.loads(
        (ROOT / "integrations/claude/.claude-plugin/plugin.json").read_text()
    )["version"]
    hermes_text = (ROOT / "integrations/hermes/question-bank/plugin.yaml").read_text()
    hermes_version = re.search(r"^version:\s*(\S+)\s*$", hermes_text, re.MULTILINE).group(1)
    changelog_version = re.search(
        r"^##\s+(\S+)", (ROOT / "CHANGELOG.md").read_text(), re.MULTILINE
    ).group(1)

    versions = {
        "pyproject.toml": project_version,
        "uv.lock question-search": search_package["version"],
        "Claude plugin": claude_version,
        "Hermes plugin": hermes_version,
        "CHANGELOG": changelog_version,
    }
    assert len(set(versions.values())) == 1, versions
