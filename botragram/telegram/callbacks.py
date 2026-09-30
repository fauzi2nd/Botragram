"""
Botragram

Description:
    Compatibility entry point for Telegram callback query routing.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.telegram.callback_routes.callbacks import handle_callback_query

__all__ = ["handle_callback_query"]
