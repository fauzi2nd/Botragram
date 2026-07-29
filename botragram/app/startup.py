"""
Botragram

Description:
    Startup helper functions for initializing components.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.utils.logger import setup_logger

logger = logging.getLogger(__name__)


# =============================================================================
# Functions
# =============================================================================
def initialize_logging() -> logging.Logger:
    """Initialize root application logger.

    Returns:
        Configured Logger instance.
    """
    app_logger = setup_logger(name="botragram", level=logging.INFO)
    logger.info("Logging infrastructure initialized")
    return app_logger
