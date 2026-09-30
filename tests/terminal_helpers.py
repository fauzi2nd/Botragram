"""
Botragram

Description:
    Deterministic Rich consoles for terminal presentation tests.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Standard Library Imports
# =============================================================================
from typing import Final, TextIO

# =============================================================================
# Third-Party Imports
# =============================================================================
from rich.console import Console

__all__ = ["create_terminal_console"]

_DEFAULT_TERMINAL_HEIGHT: Final[int] = 60


def create_terminal_console(
    *,
    file: TextIO,
    width: int,
    height: int = _DEFAULT_TERMINAL_HEIGHT,
    force_terminal: bool = False,
) -> Console:
    """Create a console whose dimensions do not depend on the host terminal.

    Rich falls back to 80x25 under TERM=dumb when either dimension is omitted.
    Explicit dimensions and disabled legacy Windows mode preserve test widths.

    Args:
        file: Output stream used to capture the rendered dashboard.
        width: Exact terminal width in columns.
        height: Exact terminal height in rows.
        force_terminal: Whether to emit terminal control sequences.

    Returns:
        A Rich console with deterministic dimensions on every test host.
    """
    return Console(
        file=file,
        width=width,
        height=height,
        force_terminal=force_terminal,
        legacy_windows=False,
    )
