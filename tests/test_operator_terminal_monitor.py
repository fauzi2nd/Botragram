"""Operator terminal event formatting regressions."""

from __future__ import annotations

from botragram.app.operator_terminal_monitor import TerminalMonitor


def test_humanizes_multi_position_heartbeat() -> None:
    """Present multi-position liveness without raw key/value telemetry."""
    rendered = TerminalMonitor._format_compact_event(
        "Runtime heartbeat: state=RUNNING context_count=5 "
        "active_batch_context_count=0 stream=MULTI"
    )

    assert rendered == "Runtime RUNNING | 5 positions | stream MULTI"
    assert "context_count" not in rendered


def test_humanizes_live_protection_verification() -> None:
    """Present verified protection as concise symbol and trigger prices."""
    rendered = TerminalMonitor._format_compact_event(
        "Live position protection verified: symbol=NILUSDT "
        "stop_loss=0.058200 take_profit=0.056000"
    )

    assert rendered == "Protection NILUSDT | SL 0.058200 | TP 0.056000"
    assert "stop_loss=" not in rendered
    assert "take_profit=" not in rendered


def test_humanizes_live_entry_completion() -> None:
    """Present a safely completed entry without raw order key syntax."""
    rendered = TerminalMonitor._format_compact_event(
        "Live Futures entry completed safely: symbol=GALAUSDT order_id=4718358487"
    )

    assert rendered == "Entry GALAUSDT confirmed | order 4718358487"
    assert "order_id=" not in rendered


def test_humanizes_submitted_live_order() -> None:
    """Present order execution and protection without snake-case fields."""
    rendered = TerminalMonitor._format_compact_event(
        "Trading cycle submitted an order: symbol=GALAUSDT order_id=4718358487 "
        "position=LONG reason=executed_and_protected risk_amount=0.01 "
        "stop_loss=0.001772 take_profit=0.001775"
    )

    assert rendered == (
        "Order GALAUSDT LONG | LIVE | risk 0.01 | "
        "SL 0.001772 | TP 0.001775"
    )
    assert "executed_and_protected" not in rendered
    assert "risk_amount=" not in rendered
