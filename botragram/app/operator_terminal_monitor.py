"""Operator-focused terminal event presentation."""

from __future__ import annotations

import re
from typing import Final

from botragram.app.responsive_terminal_monitor import TerminalMonitor as ResponsiveTerminalMonitor

__all__ = ["TerminalMonitor"]

_MULTI_HEARTBEAT_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Runtime heartbeat: state=(?P<state>\S+) context_count=(?P<context_count>\d+) "
    r"active_batch_context_count=(?P<active_count>\d+) stream=MULTI"
)
_PROTECTION_VERIFIED_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Live position protection verified: symbol=(?P<symbol>\S+) "
    r"stop_loss=(?P<stop_loss>\S+) take_profit=(?P<take_profit>\S+)"
)
_ENTRY_COMPLETED_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Live Futures entry completed safely: symbol=(?P<symbol>\S+) "
    r"order_id=(?P<order_id>\S+)"
)
_ORDER_SUBMITTED_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"Trading cycle submitted an order: symbol=(?P<symbol>\S+) "
    r"order_id=(?P<order_id>\S+) position=(?P<position>\S+) "
    r"reason=(?P<reason>\S+) risk_amount=(?P<risk_amount>\S+) "
    r"stop_loss=(?P<stop_loss>\S+) take_profit=(?P<take_profit>\S+)"
)


class TerminalMonitor(ResponsiveTerminalMonitor):
    """Add concise operator wording for high-frequency LIVE runtime events."""

    @classmethod
    def _format_compact_event(cls, message: str) -> str:
        """Humanize common LIVE events before using the responsive fallback."""
        heartbeat = _MULTI_HEARTBEAT_PATTERN.fullmatch(message)
        if heartbeat is not None:
            context_count = int(heartbeat["context_count"])
            position_label = "position" if context_count == 1 else "positions"
            rendered = (
                f"Runtime {heartbeat['state']} | {context_count} {position_label} | "
                "stream MULTI"
            )
            active_count = int(heartbeat["active_count"])
            if active_count:
                rendered += f" | active batch {active_count}"
            return rendered

        protection = _PROTECTION_VERIFIED_PATTERN.fullmatch(message)
        if protection is not None:
            return (
                f"Protection {protection['symbol']} | "
                f"SL {protection['stop_loss']} | TP {protection['take_profit']}"
            )

        entry = _ENTRY_COMPLETED_PATTERN.fullmatch(message)
        if entry is not None:
            return f"Entry {entry['symbol']} confirmed | order {entry['order_id']}"

        submitted = _ORDER_SUBMITTED_PATTERN.fullmatch(message)
        if submitted is not None:
            result = cls._format_candidate_result(submitted["reason"])
            return (
                f"Order {submitted['symbol']} {submitted['position']} | {result} | "
                f"risk {submitted['risk_amount']} | SL {submitted['stop_loss']} | "
                f"TP {submitted['take_profit']}"
            )

        return super()._format_compact_event(message)
