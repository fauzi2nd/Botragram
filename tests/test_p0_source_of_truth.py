"""
Botragram

Description:
    Regression tests for P0 SL/TP source-of-truth contract.

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
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine.risk_engine import RiskEngine
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle, Signal
from botragram.strategies.price_action.pinbar_engulfing_ema_rsi import (
    PinbarEngulfingEmaRsiStrategy,
)

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Signal Model Tests
# =============================================================================
def test_signal_model_defaults_sl_and_tp_to_none() -> None:
    """Verify backward compatibility of Signal constructor when SL/TP are omitted."""
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("50000"),
        confidence=Decimal("0.85"),
        strategy_name="test_strategy",
        generated_at=_NOW,
    )
    assert signal.stop_loss is None
    assert signal.take_profit is None


def test_signal_model_accepts_explicit_sl_and_tp() -> None:
    """Verify Signal accepts explicit numeric stop_loss and take_profit."""
    stop_loss = Decimal("49200.50")
    take_profit = Decimal("51600.00")
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("50000"),
        confidence=Decimal("0.85"),
        strategy_name="pinbar_engulfing_ema_rsi",
        generated_at=_NOW,
        reason="Test pattern rejection",
        stop_loss=stop_loss,
        take_profit=take_profit,
    )
    assert signal.stop_loss == stop_loss
    assert signal.take_profit == take_profit


# =============================================================================
# RiskEngine Source-of-Truth Tests
# =============================================================================
def test_risk_engine_adopts_explicit_pier_buy_sl_tp() -> None:
    """Verify RiskEngine preserves explicit PIER SL/TP when within configured limits."""
    engine = RiskEngine(
        settings=RiskSettings(
            pier_stop_loss_pct=Decimal("0.05"),
            pier_take_profit_pct=Decimal("0.10"),
        )
    )

    entry_price = Decimal("100.0")
    explicit_sl = Decimal("97.5")  # 2.5% risk (within pier_stop_loss_pct = 5.0%)
    explicit_tp = Decimal("105.0")  # 5.0% reward (within pier_take_profit_pct = 10.0%)

    signal = Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.BUY,
        price=entry_price,
        confidence=Decimal("0.80"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=_NOW,
        stop_loss=explicit_sl,
        take_profit=explicit_tp,
    )

    result = engine.evaluate(
        signal=signal,
        account_balance=Decimal("1000.0"),
    )

    assert result.approved is True
    assert result.metrics.stop_loss == explicit_sl
    assert result.metrics.take_profit == explicit_tp
    expected_risk_per_unit = Decimal("2.5")
    assert (
        result.metrics.risk_amount == result.position.quantity * expected_risk_per_unit
    )
    assert result.metrics.risk_reward_ratio == Decimal("2.0")


def test_risk_engine_adopts_explicit_pier_sell_sl_tp() -> None:
    """Verify RiskEngine preserves explicit PIER SELL SL/TP within limits."""
    engine = RiskEngine(
        settings=RiskSettings(
            pier_stop_loss_pct=Decimal("0.05"),
            pier_take_profit_pct=Decimal("0.10"),
        )
    )

    entry_price = Decimal("100.0")
    explicit_sl = Decimal("103.0")  # 3.0% risk above entry
    explicit_tp = Decimal("94.0")  # 6.0% reward below entry

    signal = Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.SELL,
        price=entry_price,
        confidence=Decimal("0.80"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=_NOW,
        stop_loss=explicit_sl,
        take_profit=explicit_tp,
    )

    result = engine.evaluate(
        signal=signal,
        account_balance=Decimal("1000.0"),
    )

    assert result.approved is True
    assert result.metrics.stop_loss == explicit_sl
    assert result.metrics.take_profit == explicit_tp


def test_risk_engine_caps_explicit_sl_tp_to_configured_rates() -> None:
    """Verify RiskEngine caps explicit SL/TP when exceeding strategy rates."""
    engine = RiskEngine(
        settings=RiskSettings(
            pier_stop_loss_pct=Decimal("0.018"),
            pier_take_profit_pct=Decimal("0.036"),
        )
    )

    entry_price = Decimal("100.0")
    # Explicit SL is 4% away (wider than 1.8% configured cap)
    # Explicit TP is 8% away (wider than 3.6% configured cap)
    signal = Signal(
        symbol="ETHUSDT",
        signal_type=SignalType.SELL,
        price=entry_price,
        confidence=Decimal("0.80"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=_NOW,
        stop_loss=Decimal("104.0"),
        take_profit=Decimal("92.0"),
    )

    result = engine.evaluate(
        signal=signal,
        account_balance=Decimal("1000.0"),
    )

    assert result.approved is True
    # Capped at entry + 1.8% = 101.8
    assert result.metrics.stop_loss == Decimal("101.8000")
    # Capped at entry - 3.6% = 96.4
    assert result.metrics.take_profit == Decimal("96.4000")


def test_risk_engine_choch_fvg_fallback_to_configured_rates() -> None:
    """Verify CHOCH_FVG without SL/TP cleanly falls back to configured rates."""
    engine = RiskEngine(settings=RiskSettings())

    entry_price = Decimal("100.0")
    signal = Signal(
        symbol="SOLUSDT",
        signal_type=SignalType.BUY,
        price=entry_price,
        confidence=Decimal("0.75"),
        strategy_name=StrategyType.CHOCH_FVG.value,
        generated_at=_NOW,
        stop_loss=None,
        take_profit=None,
    )

    result = engine.evaluate(
        signal=signal,
        account_balance=Decimal("1000.0"),
    )

    assert result.approved is True
    expected_sl = entry_price * (Decimal("1") - Decimal("0.008"))
    expected_tp = entry_price * (Decimal("1") + Decimal("0.018"))
    assert result.metrics.stop_loss == expected_sl
    assert result.metrics.take_profit == expected_tp


# =============================================================================
# Directional Invariant Validation Tests
# =============================================================================
@pytest.mark.parametrize(
    ("signal_type", "price", "sl", "tp", "expected_reason"),
    [
        (
            SignalType.BUY,
            Decimal("100"),
            Decimal("101"),  # SL >= entry for BUY
            Decimal("105"),
            "Explicit buy stop-loss must be below entry price",
        ),
        (
            SignalType.BUY,
            Decimal("100"),
            Decimal("98"),
            Decimal("99"),  # TP <= entry for BUY
            "Explicit buy take-profit must be above entry price",
        ),
        (
            SignalType.SELL,
            Decimal("100"),
            Decimal("99"),  # SL <= entry for SELL
            Decimal("95"),
            "Explicit sell stop-loss must be above entry price",
        ),
        (
            SignalType.SELL,
            Decimal("100"),
            Decimal("102"),
            Decimal("103"),  # TP >= entry for SELL
            "Explicit sell take-profit must be below entry price",
        ),
        (
            SignalType.BUY,
            Decimal("100"),
            Decimal("0"),  # non-positive SL
            Decimal("105"),
            "Explicit stop-loss must be finite and positive",
        ),
        (
            SignalType.BUY,
            Decimal("100"),
            Decimal("95"),
            Decimal("-10"),  # non-positive TP
            "Explicit take-profit must be finite and positive",
        ),
    ],
)
def test_risk_engine_rejects_invalid_explicit_sl_tp(
    signal_type: SignalType,
    price: Decimal,
    sl: Decimal,
    tp: Decimal,
    expected_reason: str,
) -> None:
    """Verify RiskEngine safely rejects directionally invalid explicit SL/TP."""
    engine = RiskEngine(settings=RiskSettings())

    signal = Signal(
        symbol="BTCUSDT",
        signal_type=signal_type,
        price=price,
        confidence=Decimal("0.80"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=_NOW,
        stop_loss=sl,
        take_profit=tp,
    )

    result = engine.evaluate(
        signal=signal,
        account_balance=Decimal("1000.0"),
    )

    assert result.approved is False
    assert result.reason == expected_reason


# =============================================================================
# PIER Strategy Output Tests
# =============================================================================
def _make_candle(
    *,
    index: int,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
    volume: Decimal = Decimal("100.0"),
) -> Candle:
    ot = _NOW + timedelta(minutes=15 * index)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M15,
        open_time=ot,
        close_time=ot + timedelta(minutes=15),
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
    )


def test_pier_strategy_signal_populates_numeric_sl_tp() -> None:
    """Verify PIER sets numeric stop_loss and take_profit on SELL."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        trend_period=50,
        pullback_period=10,
        rsi_period=14,
        volume_period=10,
    )

    candles: list[Candle] = []
    base = Decimal("200.0")
    for i in range(45):
        price = base - Decimal(str(i * 1.0))
        candles.append(
            _make_candle(
                index=i,
                open_price=price,
                high_price=price + Decimal("0.5"),
                low_price=price - Decimal("1.5"),
                close_price=price - Decimal("0.8"),
                volume=Decimal("100.0"),
            )
        )

    for i in range(45, 53):
        prev_close = candles[-1].close_price
        candles.append(
            _make_candle(
                index=i,
                open_price=prev_close,
                high_price=prev_close + Decimal("1.5"),
                low_price=prev_close - Decimal("0.2"),
                close_price=prev_close + Decimal("1.2"),
                volume=Decimal("100.0"),
            )
        )

    # 3-bar Evening Star
    c52_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=53,
            open_price=c52_close,
            high_price=c52_close + Decimal("4.2"),
            low_price=c52_close - Decimal("0.2"),
            close_price=c52_close + Decimal("4.0"),
            volume=Decimal("120.0"),
        )
    )
    c53_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=54,
            open_price=c53_close + Decimal("0.2"),
            high_price=c53_close + Decimal("1.5"),
            low_price=c53_close - Decimal("0.3"),
            close_price=c53_close - Decimal("0.2"),
            volume=Decimal("130.0"),
        )
    )
    c54_close = candles[-1].close_price
    candles.append(
        _make_candle(
            index=55,
            open_price=c54_close,
            high_price=c54_close + Decimal("0.2"),
            low_price=c54_close - Decimal("3.8"),
            close_price=c54_close - Decimal("3.5"),
            volume=Decimal("250.0"),
        )
    )

    signal = strategy.generate_signal(candles=candles)
    assert signal.signal_type is SignalType.SELL
    assert signal.stop_loss is not None
    assert signal.take_profit is not None
    assert signal.stop_loss > signal.price
    assert signal.take_profit < signal.price
    assert f"SL: {signal.stop_loss:.5f}" in (signal.reason or "")
    assert f"TP: {signal.take_profit:.5f}" in (signal.reason or "")


# =============================================================================
# Paper Trading Service Propagation Tests
# =============================================================================
@pytest.mark.asyncio
async def test_paper_trading_service_adopts_explicit_signal_sl_tp() -> None:
    """Verify PaperTradingService creates Position using explicit SL/TP from signal."""
    from botragram.engine import PnLEngine, TradingEngine
    from botragram.services.paper_trading_service import PaperTradingService
    from botragram.storage.memory import (
        MemoryOrderRepository,
        MemoryPositionRepository,
        MemoryTradeRepository,
    )

    orders = MemoryOrderRepository()
    trades = MemoryTradeRepository()
    positions = MemoryPositionRepository()

    service = PaperTradingService(
        order_repository=orders,
        trade_repository=trades,
        position_repository=positions,
        trading_engine=TradingEngine(
            risk_engine=RiskEngine(
                settings=RiskSettings(
                    pier_stop_loss_pct=Decimal("0.05"),
                    pier_take_profit_pct=Decimal("0.10"),
                )
            ),
        ),
        pnl_engine=PnLEngine(),
        initial_balance=Decimal("10000"),
    )

    explicit_sl = Decimal("96.50")
    explicit_tp = Decimal("107.00")
    signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100.00"),
        confidence=Decimal("0.85"),
        strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        generated_at=_NOW,
        stop_loss=explicit_sl,
        take_profit=explicit_tp,
    )

    result = await service.execute(signal=signal)
    assert result.executed

    stored_position = await positions.get_by_symbol(symbol="BTCUSDT")
    assert stored_position is not None
    assert stored_position.stop_loss == explicit_sl
    assert stored_position.take_profit == explicit_tp
