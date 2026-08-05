"""
Botragram

Description:
    Logging configuration settings.

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
from botragram.enums import LogLevel

__all__ = [
    "LoggingSettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class LoggingSettings:
    """Application logging settings."""

    level: LogLevel = LogLevel.INFO

    console_enabled: bool = True
    file_enabled: bool = True

    directory: Path = Path("logs")
    filename: str = "botragram.log"

    max_file_size_mb: int = 10
    backup_count: int = 5
