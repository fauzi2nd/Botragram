"""
Botragram

Description:
    Unit tests for asset-class aware volatility and risk threshold resolver.

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
from datetime import UTC, datetime, timedelta
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import AssetClass, Interval, SignalType
from botragram.models import Candle
from botragram.strategies.base.asset_thresholds import (
    resolve_asset_class,
    resolve_effective_distance_pct,
    resolve_effective_natr_bounds,
)
from botragram.strategies.price_action.pinbar_engulfing_ema_rsi import (
    PinbarEngulfingEmaRsiStrategy,
)


# =============================================================================
# Test Asset Classification
# =============================================================================
def test_resolve_asset_class() -> None:
    """Verify symbols resolve to the correct AssetClass."""
    assert resolve_asset_class("BTCUSDT") is AssetClass.CRYPTO
    assert resolve_asset_class("ETHUSDT") is AssetClass.CRYPTO
    assert resolve_asset_class("EURUSD") is AssetClass.FOREX
    assert resolve_asset_class("AUDCAD") is AssetClass.FOREX
    assert resolve_asset_class("XAUUSD") is AssetClass.COMMODITY
    assert resolve_asset_class("USOIL") is AssetClass.COMMODITY
    assert resolve_asset_class("COCOA") is AssetClass.COMMODITY
    assert resolve_asset_class("DE40") is AssetClass.INDEX
    assert resolve_asset_class("AUS200") is AssetClass.INDEX
    assert resolve_asset_class("SPY") is AssetClass.INDEX


# =============================================================================
# Test Effective NATR Bounds
# =============================================================================
def test_resolve_effective_natr_bounds_crypto() -> None:
    """Verify Crypto preserves original configured base thresholds."""
    base_min = Decimal("0.0020")
    base_max = Decimal("0.0350")
    eff_min, eff_max = resolve_effective_natr_bounds("BTCUSDT", base_min, base_max)
    assert eff_min == Decimal("0.0020")
    assert eff_max == Decimal("0.0350")


def test_resolve_effective_natr_bounds_forex() -> None:
    """Verify Forex adapts to 1 pip / 0.01% dead-market floor and 0.5% shock ceiling."""
    base_min = Decimal("0.0020")
    base_max = Decimal("0.0350")
    eff_min, eff_max = resolve_effective_natr_bounds("EURUSD", base_min, base_max)
    assert eff_min == Decimal("0.0001")
    assert eff_max == Decimal("0.0050")


def test_resolve_effective_natr_bounds_commodity() -> None:
    """Verify Commodities adapt to 0.04% dead-market floor and 1.5% shock ceiling."""
    base_min = Decimal("0.0020")
    base_max = Decimal("0.0350")
    eff_min, eff_max = resolve_effective_natr_bounds("XAUUSD", base_min, base_max)
    assert eff_min == Decimal("0.0004")
    assert eff_max == Decimal("0.0150")


def test_resolve_effective_natr_bounds_index() -> None:
    """Verify Indices adapt to 0.02% dead-market floor and 1.5% shock ceiling."""
    base_min = Decimal("0.0020")
    base_max = Decimal("0.0350")
    eff_min, eff_max = resolve_effective_natr_bounds("DE40", base_min, base_max)
    assert eff_min == Decimal("0.0002")
    assert eff_max == Decimal("0.0150")


# =============================================================================
# Test Effective Distance Percentages
# =============================================================================
def test_resolve_effective_distance_pct_crypto() -> None:
    """Verify Crypto preserves original configured base percentages."""
    base_sl = Decimal("0.0080")
    base_trend = Decimal("0.0030")
    eff_sl, eff_trend = resolve_effective_distance_pct("BTCUSDT", base_sl, base_trend)
    assert eff_sl == Decimal("0.0080")
    assert eff_trend == Decimal("0.0030")


def test_resolve_effective_distance_pct_forex() -> None:
    """Verify Forex adapts to 0.10% SL and 0.05% Trend distance."""
    base_sl = Decimal("0.0080")
    base_trend = Decimal("0.0030")
    eff_sl, eff_trend = resolve_effective_distance_pct("EURUSD", base_sl, base_trend)
    assert eff_sl == Decimal("0.0010")
    assert eff_trend == Decimal("0.0005")


def test_resolve_effective_distance_pct_commodity() -> None:
    """Verify Commodities adapt to 0.20% SL and 0.10% Trend distance."""
    base_sl = Decimal("0.0080")
    base_trend = Decimal("0.0030")
    eff_sl, eff_trend = resolve_effective_distance_pct("XAUUSD", base_sl, base_trend)
    assert eff_sl == Decimal("0.0020")
    assert eff_trend == Decimal("0.0010")


def test_resolve_effective_distance_pct_index() -> None:
    """Verify Indices adapt to 0.15% SL and 0.10% Trend distance."""
    base_sl = Decimal("0.0080")
    base_trend = Decimal("0.0030")
    eff_sl, eff_trend = resolve_effective_distance_pct("DE40", base_sl, base_trend)
    assert eff_sl == Decimal("0.0015")
    assert eff_trend == Decimal("0.0010")


# =============================================================================
# Strategy Integration: Forex NATR acceptance vs Crypto rejection
# =============================================================================
def test_forex_natr_not_rejected_as_dead_market() -> None:
    """Verify that Forex with NATR=0.0003 is accepted whereas Crypto is rejected."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        min_natr_threshold=Decimal("0.0020"),
    )

    base_time = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)

    def _build_candles(symbol: str, base_price: Decimal, tick: Decimal) -> list[Candle]:
        candles: list[Candle] = []
        for i in range(210):
            t_open = base_time + timedelta(minutes=i * 5)
            t_close = t_open + timedelta(minutes=5)
            p = base_price + Decimal(i) * tick
            # High-Low spread gives ATR/Price = ~0.0003
            spread = p * Decimal("0.0003")
            candles.append(
                Candle(
                    symbol=symbol,
                    interval=Interval.M5,
                    open_time=t_open,
                    close_time=t_close,
                    open_price=p,
                    high_price=p + spread / Decimal("2"),
                    low_price=p - spread / Decimal("2"),
                    close_price=p,
                    volume=Decimal("1000"),
                )
            )
        return candles

    forex_candles = _build_candles("EURUSD", Decimal("1.0800"), Decimal("0.00005"))
    crypto_candles = _build_candles("BTCUSDT", Decimal("60000.00"), Decimal("5.00"))

    # For crypto, NATR ~0.0003 < 0.0020 must be rejected as Dead Market
    sig_crypto = strategy.generate_signal(candles=crypto_candles)
    assert sig_crypto.signal_type is SignalType.HOLD
    assert (
        sig_crypto.reason is not None
        and "Dead market volatility rejected" in sig_crypto.reason
    )

    # For Forex, NATR ~0.0003 >= 0.0001 must NOT be rejected as Dead Market
    sig_forex = strategy.generate_signal(candles=forex_candles)
    assert (
        sig_forex.reason is None
        or "Dead market volatility rejected" not in sig_forex.reason
    )
