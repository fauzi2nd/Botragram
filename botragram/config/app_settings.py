"""
Botragram

Description:
    Application configuration settings model.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library
# =============================================================================
from dataclasses import dataclass
from pathlib import Path

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants import APP_NAME, APP_VERSION
from botragram.enums import Environment, TradeMode

__all__ = [
    "AppSettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class AppSettings:
    """Application-wide environment and runtime settings."""

    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    environment: Environment = Environment.DEVELOPMENT
    trade_mode: TradeMode = TradeMode.PAPER
    database_path: Path = Path("data") / "botragram.db"

    @property
    def debug(self) -> bool:
        return self.environment in (
            Environment.DEVELOPMENT,
            Environment.TESTING,
        )
