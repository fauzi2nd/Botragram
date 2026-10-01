"""
Botragram

Description:
    Guard service and engine dependency direction against higher layers.

Python:
    3.14+
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__: list[str] = []

_SERVICE_ROOT = Path(__file__).resolve().parents[1] / "botragram" / "services"
_ENGINE_ROOT = Path(__file__).resolve().parents[1] / "botragram" / "engine"
_APP_PACKAGE = "botragram.app"
_ENGINE_FORBIDDEN_PACKAGES = ("botragram.services", "botragram.storage")


def test_services_do_not_import_application_composition() -> None:
    """Services must depend on contracts rather than app-owned implementations."""
    assert (
        _find_import_violations(
            source_root=_SERVICE_ROOT,
            forbidden_packages=(_APP_PACKAGE,),
        )
        == []
    )


def test_engines_do_not_import_services_or_storage() -> None:
    """Backtest and trading engines must not construct higher-layer dependencies."""
    assert (
        _find_import_violations(
            source_root=_ENGINE_ROOT,
            forbidden_packages=_ENGINE_FORBIDDEN_PACKAGES,
        )
        == []
    )


def _find_import_violations(
    *,
    source_root: Path,
    forbidden_packages: tuple[str, ...],
) -> list[str]:
    """Return locations importing a forbidden package or one of its children."""
    violations: list[str] = []
    for source in source_root.rglob("*.py"):
        syntax = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(syntax):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(
                    module == package or module.startswith(f"{package}.")
                    for package in forbidden_packages
                ):
                    violations.append(
                        f"{source.relative_to(source_root)}:{node.lineno}"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(
                        alias.name == package or alias.name.startswith(f"{package}.")
                        for package in forbidden_packages
                    ):
                        violations.append(
                            f"{source.relative_to(source_root)}:{node.lineno}"
                        )

    return violations
