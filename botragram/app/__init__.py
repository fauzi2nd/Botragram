"""
Botragram

Description:
    Application package initialization.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.application import Application
from botragram.app.dependency_provider import DependencyProvider
from botragram.app.lifecycle import ApplicationLifecycle
from botragram.app.shutdown import shutdown_application
from botragram.app.startup import startup_application

__all__ = [
    "Application",
    "ApplicationLifecycle",
    "DependencyProvider",
    "shutdown_application",
    "startup_application",
]
