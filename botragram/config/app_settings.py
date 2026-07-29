"""
Botragram

Description:
    Application settings model.

Python:
    3.14+
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AppSettings:
    """Application-wide settings."""

    app_name: str = "Botragram"
    environment: str = "development"
    debug: bool = True
