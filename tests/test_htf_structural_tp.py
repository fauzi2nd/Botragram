"""
Botragram

Description:
    Unit tests for Fase 1 Multi-TF Structural Target (Barriers & TP).

Python:
    3.14+
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from botragram.enums import Interval, SignalType
from botragram.models import Candle
from botragram.strategies.price_action.pinbar_engulfing_ema_rsi import (
    PinbarEngulfingEmaRsiStrategy,
)

_NOW = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)


def _make_15m_candle(
    *,
    index: int,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
    volume: Decimal = Decimal("100.0"),
) -> Candle:
    open_time = _NOW + timedelta(minutes=15 * index)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M15,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=15),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
    )


def test_htf_structural_tp_trims_tp_before_wall() -> None:
    """Trim TP to safe area before 1h Upper BB / Swing High wall."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
        use_structural_tp=True,
        use_htf_structural_tp=True,
        structural_tp_buffer_pct=Decimal("0.002"),
        min_structural_rr=Decimal("1.0"),
        risk_reward_ratio=Decimal("3.5"),
        require_confirmation=False,
    )

    candles: list[Candle] = []
    base = Decimal("100.0")
    for i in range(45):
        price = base + Decimal(str(i * 1.0))
        candles.append(
            _make_15m_candle(
                index=i,
                open_price=price,
                high_price=price + Decimal("1.5"),
                low_price=price - Decimal("0.5"),
                close_price=price + Decimal("0.8"),
            )
        )

    for i in range(45, 55):
        prev_close = candles[-1].close_price
        candles.append(
            _make_15m_candle(
                index=i,
                open_price=prev_close,
                high_price=prev_close + Decimal("0.2"),
                low_price=prev_close - Decimal("1.5"),
                close_price=prev_close - Decimal("1.2"),
            )
        )

    last_close = candles[-1].close_price
    candles.append(
        _make_15m_candle(
            index=55,
            open_price=last_close,
            high_price=last_close + Decimal("0.5"),
            low_price=last_close - Decimal("3.0"),
            close_price=last_close + Decimal("0.3"),
            volume=Decimal("250.0"),
        )
    )

    sig = strategy.generate_signal(candles=candles)
    assert sig.signal_type is SignalType.BUY
    assert sig.take_profit is not None
    assert sig.reason is not None
    assert "Structural TP trimmed" in sig.reason
    assert "1h Swing High" in sig.reason


def test_htf_structural_tp_rejects_when_rr_below_floor() -> None:
    """Reject setup when trimmed TP produces RR < min_structural_rr."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
        use_structural_tp=True,
        use_htf_structural_tp=True,
        structural_tp_buffer_pct=Decimal("0.002"),
        min_structural_rr=Decimal("3.0"),  # Requiring at least 3.0 RR
        risk_reward_ratio=Decimal("3.5"),
        require_confirmation=False,
    )

    candles: list[Candle] = []
    base = Decimal("100.0")
    for i in range(45):
        price = base + Decimal(str(i * 1.0))
        candles.append(
            _make_15m_candle(
                index=i,
                open_price=price,
                high_price=price + Decimal("1.5"),
                low_price=price - Decimal("0.5"),
                close_price=price + Decimal("0.8"),
            )
        )

    for i in range(45, 55):
        prev_close = candles[-1].close_price
        candles.append(
            _make_15m_candle(
                index=i,
                open_price=prev_close,
                high_price=prev_close + Decimal("0.2"),
                low_price=prev_close - Decimal("1.5"),
                close_price=prev_close - Decimal("1.2"),
            )
        )

    last_close = candles[-1].close_price
    candles.append(
        _make_15m_candle(
            index=55,
            open_price=last_close,
            high_price=last_close + Decimal("0.5"),
            low_price=last_close - Decimal("3.0"),
            close_price=last_close + Decimal("0.3"),
            volume=Decimal("250.0"),
        )
    )

    sig = strategy.generate_signal(candles=candles)
    assert sig.signal_type is SignalType.HOLD
    assert sig.reason is not None
    assert "BUY setup rejected: Structural resistance" in sig.reason
    assert "restricts TP" in sig.reason
