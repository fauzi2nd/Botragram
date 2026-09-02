"""Operator terminal event formatting regressions."""

from __future__ import annotations

from botragram.app.operator_terminal_monitor import TerminalMonitor


class _TestTerminalMonitor(TerminalMonitor):
    """Expose terminal event formatting through a typed test seam."""

    @classmethod
    def format_compact_event(cls, message: str) -> str:
        """Format one event using the inherited terminal behavior."""
        return cls._format_compact_event(message)


def test_humanizes_multi_position_heartbeat() -> None:
    """Present multi-position liveness without raw key/value telemetry."""
    rendered = _TestTerminalMonitor.format_compact_event(
        "Runtime heartbeat: state=RUNNING context_count=5 "
        "active_batch_context_count=0 stream=MULTI"
    )

    assert rendered == "Runtime RUNNING | 5 positions | stream MULTI"
    assert "context_count" not in rendered


def test_humanizes_live_protection_verification() -> None:
    """Present verified protection as concise symbol and trigger prices."""
    rendered = _TestTerminalMonitor.format_compact_event(
        "Live position protection verified: symbol=NILUSDT "
        "stop_loss=0.058200 take_profit=0.056000"
    )

    assert rendered == "Protection NILUSDT | SL 0.0582 | TP 0.056"
    assert "stop_loss=" not in rendered
    assert "take_profit=" not in rendered


def test_humanizes_live_entry_completion() -> None:
    """Present a safely completed entry without raw order key syntax."""
    rendered = _TestTerminalMonitor.format_compact_event(
        "Live Futures entry completed safely: symbol=GALAUSDT order_id=4718358487"
    )

    assert rendered == "Entry GALAUSDT confirmed | order 4718358487"
    assert "order_id=" not in rendered


def test_humanizes_submitted_live_order() -> None:
    """Present order execution and protection without snake-case fields."""
    rendered = _TestTerminalMonitor.format_compact_event(
        "Trading cycle submitted an order: symbol=GALAUSDT order_id=4718358487 "
        "position=LONG reason=executed_and_protected "
        "risk_amount=0.2000000000000000000000000000 "
        "stop_loss=0.00177200 take_profit=0.00177500"
    )

    assert rendered == (
        "Order GALAUSDT LONG | LIVE | risk 0.20 | SL 0.001772 | TP 0.001775"
    )
    assert "executed_and_protected" not in rendered
    assert "risk_amount=" not in rendered


def test_humanizes_generic_runtime_recovery_telemetry() -> None:
    """Remove raw structured fields from recovery diagnostics across services."""
    rendered = _TestTerminalMonitor.format_compact_event(
        "LIVE portfolio recovery is unsafe: reason=orphan_protection symbol=NILUSDT"
    )

    assert rendered == (
        "LIVE portfolio recovery is unsafe | reason ORPHAN PROTECTION | symbol NILUSDT"
    )
    assert "reason=" not in rendered
    assert "symbol=" not in rendered
    assert "orphan_protection" not in rendered


def test_humanizes_generic_outage_heartbeat_telemetry() -> None:
    """Present fail-closed outage state without implementation field names."""
    rendered = _TestTerminalMonitor.format_compact_event(
        "Runtime heartbeat: state=PAUSED reason=binance_connectivity_unavailable "
        "outage_seconds=12.5 next_retry_seconds=1.000 positions_known=5 "
        "positions_state=known_non_authoritative entry_enabled=false"
    )

    assert rendered == (
        "Runtime heartbeat | state PAUSED | reason BINANCE CONNECTIVITY UNAVAILABLE | "
        "outage 12.5 | next retry 1.000 | positions known 5 | "
        "positions state KNOWN NON AUTHORITATIVE | entry OFF"
    )
    assert "=" not in rendered
    assert "_" not in rendered


def test_humanizes_generic_entry_synchronization_telemetry() -> None:
    """Keep useful entry facts while removing raw field syntax."""
    rendered = _TestTerminalMonitor.format_compact_event(
        "Live Futures entry position synchronized: symbol=ACEUSDT quantity=52 "
        "entry_price=0.1896"
    )

    assert rendered == (
        "Live Futures entry position synchronized | symbol ACEUSDT | "
        "qty 52 | entry 0.1896"
    )
    assert "quantity=" not in rendered
    assert "entry_price=" not in rendered


def test_generic_humanizer_preserves_unstructured_message() -> None:
    """Do not reinterpret arbitrary prose that only happens to contain equals."""
    message = "Exchange response detail x=y remains diagnostic prose"

    rendered = _TestTerminalMonitor.format_compact_event(message)

    assert rendered == message
