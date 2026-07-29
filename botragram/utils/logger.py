"""
Botragram

Description:
    Structured logging configuration utility.

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
import logging
import sys


# =============================================================================
# Utility Functions
# =============================================================================
def setup_logger(
    name: str = "botragram",
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure structured logger with stdout handler.

    Args:
        name: Logger name identifier.
        level: Logging level (e.g. logging.INFO).

    Returns:
        Configured Logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
