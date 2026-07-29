"""
Botragram

Description:
    Startup helpers for creating the application instance.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.app.application import Application


def create_application() -> Application:
    """Create a configured application instance."""
    return Application()
