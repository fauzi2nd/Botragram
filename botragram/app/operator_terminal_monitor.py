"""Operator-focused terminal event presentation."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Final

from botragram.app.responsive_terminal_monitor import (
    TerminalMonitor as ResponsiveTerminalMonitor,
)

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
_KEY_VALUE_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?P<key>[a-z][a-z0-9_]*)=(?P<value>\S+)"
)
_KEY_LABELS: Final[dict[str, str]] = {
    "active_batch_context_count": "active batch",
    "attempt": "attempt",
    "candle_limit": "candle limit",
    "client_order_id": "client order",
    "context_count": "contexts",
    "count": "count",
    "delay_seconds": "delay",
    "entry_enabled": "entry",
    "entry_price": "entry",
    "error_type": "error",
    "interval": "interval",
    "mark_price": "mark",
    "mode": "mode",
    "monitors": "monitors",
    "next_retry_seconds": "next retry",
    "order_id": "order",
    "outage_seconds": "outage",
    "position": "position",
    "positions_known": "positions known",
    "positions_state": "positions state",
    "quantity": "qty",
    "reason": "reason",
    "reporting_interval": "report every",
    "risk_amount": "risk",
    "side": "side",
    "stop_loss": "SL",
    "strategy": "strategy",
    "streams": "streams",
    "symbol": "symbol",
    "take_profit": "TP",
    "timeout_seconds": "timeout",
}
_ENUM_VALUE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "mode",
        "position",
        "positions_state",
        "reason",
        "side",
        "strategy",
    }
)


def _format_decimal_str(value: str) -> str:
    """Format decimal numbers cleanly, removing excessive precision trailing zeros."""
    try:
        dec = Decimal(value)
        raw = f"{dec:f}"
        if "." in raw:
            int_part, frac_part = raw.split(".", 1)
            frac_trimmed = frac_part.rstrip("0")
            if not frac_trimmed:
                return f"{int_part}.00"
            if len(frac_trimmed) < 2:
                frac_trimmed = frac_trimmed.ljust(2, "0")
            return f"{int_part}.{frac_trimmed}"
        return raw
    except Exception:
        return value


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
                f"SL {_format_decimal_str(protection['stop_loss'])} | "
                f"TP {_format_decimal_str(protection['take_profit'])}"
            )

        entry = _ENTRY_COMPLETED_PATTERN.fullmatch(message)
        if entry is not None:
            return f"Entry {entry['symbol']} confirmed | order {entry['order_id']}"

        submitted = _ORDER_SUBMITTED_PATTERN.fullmatch(message)
        if submitted is not None:
            result = cls._format_candidate_result(submitted["reason"])
            return (
                f"Order {submitted['symbol']} {submitted['position']} | {result} | "
                f"risk {_format_decimal_str(submitted['risk_amount'])} | "
                f"SL {_format_decimal_str(submitted['stop_loss'])} | "
                f"TP {_format_decimal_str(submitted['take_profit'])}"
            )

        responsive = super()._format_compact_event(message)
        if responsive != message.replace("_", " "):
            return responsive

        generic = cls._format_generic_key_value_event(message)
        if generic is not None:
            return generic
        return responsive

    @classmethod
    def _format_generic_key_value_event(cls, message: str) -> str | None:
        """Humanize project-wide structured telemetry without changing logging."""
        matches = tuple(_KEY_VALUE_TOKEN_PATTERN.finditer(message))
        if not matches:
            return None

        first = matches[0]
        prefix = message[: first.start()].rstrip(" :")
        cursor = first.start()
        rendered_fields: list[str] = []
        for match in matches:
            gap = message[cursor : match.start()]
            if gap.strip():
                return None
            key = match["key"]
            value = cls._format_generic_value(key=key, value=match["value"])
            label = _KEY_LABELS.get(key, key.replace("_", " "))
            rendered_fields.append(f"{label} {value}")
            cursor = match.end()

        if message[cursor:].strip():
            return None
        if not prefix:
            return " | ".join(rendered_fields)
        return " | ".join((prefix, *rendered_fields))

    @staticmethod
    def _format_generic_value(*, key: str, value: str) -> str:
        """Normalize common telemetry values for operator readability."""
        normalized = value.strip()
        lowered = normalized.lower()
        if key.endswith("_enabled"):
            if lowered == "true":
                return "ON"
            if lowered == "false":
                return "OFF"
        if lowered == "none":
            return "N/A"
        if key in _ENUM_VALUE_KEYS:
            return normalized.replace("_", " ").upper()
        if key in {
            "risk_amount",
            "stop_loss",
            "take_profit",
            "entry_price",
            "mark_price",
        }:
            return _format_decimal_str(normalized)
        return normalized.replace("_", " ")
