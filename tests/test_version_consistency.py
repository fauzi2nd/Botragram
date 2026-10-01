"""Keep the operator-visible application version aligned with package metadata."""

from __future__ import annotations

import tomllib
from pathlib import Path

from botragram.constants.app import APP_VERSION

__all__: list[str] = []


def test_application_version_matches_package_version() -> None:
    """Prevent the Telegram and runtime version from drifting behind releases."""
    project_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
    metadata = tomllib.loads(project_file.read_text(encoding="utf-8"))
    package_version: str = metadata["project"]["version"]
    assert APP_VERSION == package_version
