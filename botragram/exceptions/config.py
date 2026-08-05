"""
Botragram

Description:
    Configuration-related exception classes.

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
from botragram.exceptions.base import BotragramError

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigKeyError",
    "ConfigTypeError",
    "ConfigValidationError",
]


# =============================================================================
# Exceptions
# =============================================================================
class ConfigError(BotragramError):
    """Base exception for configuration-related errors."""


class ConfigFileNotFoundError(ConfigError):
    """Raised when a configuration file cannot be found."""


class ConfigKeyError(ConfigError):
    """Raised when a required configuration key is missing."""


class ConfigTypeError(ConfigError):
    """Raised when a configuration value has an invalid type."""


class ConfigValidationError(ConfigError):
    """Raised when a configuration value fails validation."""
