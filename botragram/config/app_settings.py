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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants.app import APP_NAME, APP_VERSION
from botragram.enums.trade_mode import TradeMode


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(slots=True)
class AppSettings:
    """Application-wide environment and runtime settings."""

    app_name: str = APP_NAME
    version: str = APP_VERSION
    environment: str = "development"
    debug: bool = True
    trade_mode: TradeMode = TradeMode.PAPER
