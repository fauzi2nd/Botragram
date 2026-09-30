"""
Botragram

Description:
    Guard service dependency direction against application-layer imports.

Python:
    3.14+
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__: list[str] = []

_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "botragram" / "services"
_APP_PACKAGE = "botragram.app"


def test_services_do_not_import_application_composition() -> None:
    """Services must depend on contracts rather than app-owned implementations."""
    violations: list[str] = []
    for source in _SERVICE_ROOT.rglob("*.py"):
        syntax = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(syntax):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == _APP_PACKAGE or module.startswith(f"{_APP_PACKAGE}."):
                    violations.append(
                        f"{source.relative_to(_SERVICE_ROOT)}:{node.lineno}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == _APP_PACKAGE or alias.name.startswith(
                        f"{_APP_PACKAGE}."
                    ):
                        violations.append(
                            f"{source.relative_to(_SERVICE_ROOT)}:{node.lineno}"
                        )

    assert violations == []
