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

    def __post_init__(self) -> None:
        """Validate logging output and rotation settings."""
        if not self.filename.strip():
            raise ValueError("Log filename must not be empty")

        filename_path = Path(self.filename)

        if filename_path.is_absolute() or filename_path.name != self.filename:
            raise ValueError("Log filename must not contain a directory path")

        if self.max_file_size_mb <= 0:
            raise ValueError("Maximum log file size must be greater than zero")

        if self.backup_count < 0:
            raise ValueError("Log backup count must not be negative")
