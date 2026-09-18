"""
Botragram

Description:
    Deterministic risk, trading, PnL, and portfolio engine tests.

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
from dataclasses import replace
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
from botragram.config.strategy_settings import StrategySettings
from botragram.engine import (
    PnLEngine,
    PortfolioEngine,
    RiskEngine,
    SignalEngine,
    TradingEngine,
)
from botragram.enums import Interval, PositionSide, SignalType, StrategyType
from botragram.models import Candle, Position, Signal
from botragram.strategies.factory import StrategyFactory

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


# =============================================================================
# Test Helpers
# =============================================================================
def _create_signal(
    *,
    signal_type: SignalType = SignalType.BUY,
    price: Decimal = Decimal("100"),
    strategy_name: str = "test_strategy",
) -> Signal:
    """Create an immutable signal fixture."""
    return Signal(
        symbol="BTCUSDT",
        signal_type=signal_type,
        price=price,
        confidence=Decimal("0.8"),
        strategy_name=strategy_name,
        generated_at=_NOW,
    )


def _create_position(
    *,
    symbol: str,
    side: PositionSide,
    quantity: Decimal,
    entry_price: Decimal,
    current_price: Decimal,
    unrealized_pnl: Decimal,
) -> Position:
    """Create an immutable position fixture."""
    return Position(
        symbol=symbol,
        side=side,
        quantity=quantity,
        entry_price=entry_price,
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )


# =============================================================================
# Risk Engine Tests
# =============================================================================
def test_risk_engine_approves_and_sizes_a_buy_signal() -> None:
    """Verify risk sizing, protective prices, and reward ratio."""
    engine = RiskEngine(settings=RiskSettings())

    result = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("1000"),
    )

    assert result.approved
    assert result.position.quantity == Decimal("10")
    assert result.position.notional == Decimal("1000")
    assert result.metrics.entry_price == Decimal("100")
    assert result.metrics.stop_loss == Decimal("98.00")
    assert result.metrics.take_profit == Decimal("104.00")
    assert result.metrics.risk_amount == Decimal("20.00")
    assert result.metrics.reward_amount == Decimal("40.00")
    assert result.metrics.risk_reward_ratio == Decimal("2")


@pytest.mark.parametrize(
    ("side", "expected_stop_loss", "expected_take_profit"),
    (
        (PositionSide.LONG, Decimal("98"), Decimal("104")),
        (PositionSide.SHORT, Decimal("102"), Decimal("96")),
    ),
)
def test_risk_engine_preserves_default_ema_cross_exit_profile(
    side: PositionSide,
    expected_stop_loss: Decimal,
    expected_take_profit: Decimal,
) -> None:
    """Preserve v1.0.3 EMA cross protection levels for both position sides."""
    engine = RiskEngine(settings=RiskSettings())

    stop_loss, take_profit = engine.calculate_protection_levels(
        side=side,
        entry_price=Decimal("100"),
        strategy_type=StrategyType.EMA_CROSS,
    )

    assert stop_loss == expected_stop_loss
    assert take_profit == expected_take_profit


def test_risk_engine_uses_overridden_ema_cross_exit_profile() -> None:
    """Use narrow EMA cross ratios throughout the evaluated risk result."""
    engine = RiskEngine(
        settings=RiskSettings(
            ema_cross_stop_loss_pct=Decimal("0.001"),
            ema_cross_take_profit_pct=Decimal("0.0015"),
        )
    )

    result = engine.evaluate(
        signal=_create_signal(
            signal_type=SignalType.SELL,
            strategy_name=StrategyType.EMA_CROSS.value,
        ),
        account_balance=Decimal("1000"),
    )

    assert result.approved
    assert result.position.quantity == Decimal("10")
    assert result.position.notional == Decimal("1000")
    assert result.metrics.stop_loss == Decimal("100.1")
    assert result.metrics.take_profit == Decimal("99.85")
    assert result.metrics.risk_amount == Decimal("1")
    assert result.metrics.reward_amount == Decimal("1.5")
    assert result.metrics.risk_reward_ratio == Decimal("1.5")


def test_risk_engine_uses_pier_configured_exit_profile() -> None:
    """Use configured PIER exit rates (e.g. 1.8% SL and 3.6% TP)."""
    engine = RiskEngine(
        settings=RiskSettings(
            pier_stop_loss_pct=Decimal("0.018"),
            pier_take_profit_pct=Decimal("0.036"),
        )
    )

    result = engine.evaluate(
        signal=_create_signal(
            signal_type=SignalType.BUY,
            price=Decimal("100"),
            strategy_name=StrategyType.PINBAR_ENGULFING_EMA_RSI.value,
        ),
        account_balance=Decimal("1000"),
    )

    assert result.approved
    assert result.metrics.stop_loss == Decimal("98.200")
    assert result.metrics.take_profit == Decimal("103.600")
    assert result.metrics.risk_reward_ratio == Decimal("2")


def test_risk_engine_caps_position_at_configured_notional() -> None:
    """Verify calculated quantity respects maximum position size."""
    engine = RiskEngine(
        settings=RiskSettings(max_position_size_usdt=Decimal("500")),
    )

    result = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("1000"),
    )

    assert result.approved
    assert result.position.notional == Decimal("500")
    assert result.position.quantity == Decimal("5")
    assert result.metrics.risk_amount == Decimal("10.00")


def test_risk_engine_uses_dedicated_ema_scalping_exit_profile() -> None:
    """Keep short-horizon EMA exits independent from global swing defaults."""
    engine = RiskEngine(settings=RiskSettings())

    result = engine.evaluate(
        signal=_create_signal(
            strategy_name=StrategyType.EMA_SCALPING.value,
        ),
        account_balance=Decimal("1000"),
    )

    assert result.metrics.stop_loss == Decimal("99.500")
    assert result.metrics.take_profit == Decimal("101.00")
    assert result.metrics.risk_reward_ratio == Decimal("2")


@pytest.mark.parametrize(
    "strategy_name",
    (StrategyType.CUSTOM.value, "external_strategy"),
)
def test_risk_engine_preserves_global_exit_fallback(
    strategy_name: str,
) -> None:
    """Keep custom and unknown strategies on the existing global exit profile."""
    engine = RiskEngine(
        settings=RiskSettings(
            stop_loss_pct=Decimal("0.03"),
            take_profit_pct=Decimal("0.06"),
            ema_cross_stop_loss_pct=Decimal("0.001"),
            ema_cross_take_profit_pct=Decimal("0.0015"),
        )
    )

    result = engine.evaluate(
        signal=_create_signal(strategy_name=strategy_name),
        account_balance=Decimal("1000"),
    )

    assert result.metrics.stop_loss == Decimal("97")
    assert result.metrics.take_profit == Decimal("106")


def test_risk_engine_exit_rates_per_strategy_category() -> None:
    """Verify RiskEngine calculates calibrated SL/TP for each strategy category."""
    custom_risk = RiskSettings(
        scalping_stop_loss_pct=Decimal("0.006"),
        scalping_take_profit_pct=Decimal("0.012"),
        trend_stop_loss_pct=Decimal("0.018"),
        trend_take_profit_pct=Decimal("0.036"),
        swing_stop_loss_pct=Decimal("0.024"),
        swing_take_profit_pct=Decimal("0.048"),
    )
    engine = RiskEngine(settings=custom_risk)

    # Scalping
    res_scalp = engine.evaluate(
        signal=_create_signal(
            strategy_name=StrategyType.RSI_BB_SCALPING.value,
            price=Decimal("100"),
        ),
        account_balance=Decimal("1000"),
        current_drawdown_pct=Decimal("0"),
    )
    assert res_scalp.metrics.stop_loss == Decimal("99.4")  # -0.6%
    assert res_scalp.metrics.take_profit == Decimal("101.2")  # +1.2%

    # Trend
    res_trend = engine.evaluate(
        signal=_create_signal(
            strategy_name=StrategyType.ICHIMOKU_CLOUD.value,
            price=Decimal("100"),
        ),
        account_balance=Decimal("1000"),
        current_drawdown_pct=Decimal("0"),
    )
    assert res_trend.metrics.stop_loss == Decimal("98.2")  # -1.8%
    assert res_trend.metrics.take_profit == Decimal("103.6")  # +3.6%

    # Swing
    res_swing = engine.evaluate(
        signal=_create_signal(
            strategy_name=StrategyType.MACD_SWING.value,
            price=Decimal("100"),
        ),
        account_balance=Decimal("1000"),
        current_drawdown_pct=Decimal("0"),
    )
    assert res_swing.metrics.stop_loss == Decimal("97.6")  # -2.4%
    assert res_swing.metrics.take_profit == Decimal("104.8")  # +4.8%


def test_risk_engine_uses_dedicated_origin_exit_rates() -> None:
    """Ensure BOTRAGRAM_ORIGIN exit rates are taken from origin settings."""
    engine = RiskEngine(
        settings=RiskSettings(
            origin_stop_loss_pct=Decimal("0.012"),
            origin_take_profit_pct=Decimal("0.0216"),
        )
    )

    result = engine.evaluate(
        signal=_create_signal(
            strategy_name=StrategyType.BOTRAGRAM_ORIGIN.value,
            price=Decimal("100"),
        ),
        account_balance=Decimal("1000"),
    )

    assert result.metrics.stop_loss == Decimal("98.800")
    assert result.metrics.take_profit == Decimal("102.1600")
    assert result.metrics.risk_reward_ratio == Decimal("1.8")


@pytest.mark.parametrize(
    ("signal_type", "drawdown", "reason"),
    (
        (SignalType.HOLD, Decimal("0"), "Hold signals"),
        (SignalType.BUY, Decimal("0.10"), "Maximum account drawdown"),
    ),
)
def test_risk_engine_rejects_non_executable_conditions(
    signal_type: SignalType,
    drawdown: Decimal,
    reason: str,
) -> None:
    """Verify rejected risk results remain explicit and zero-sized."""
    engine = RiskEngine(settings=RiskSettings())

    result = engine.evaluate(
        signal=_create_signal(signal_type=signal_type),
        account_balance=Decimal("1000"),
        current_drawdown_pct=drawdown,
    )

    assert not result.approved
    assert result.position.quantity == Decimal("0")
    assert reason in result.reason


@pytest.mark.parametrize(
    ("balance", "drawdown", "price", "message"),
    (
        (Decimal("0"), Decimal("0"), Decimal("100"), "Account balance"),
        (Decimal("100"), Decimal("-0.01"), Decimal("100"), "drawdown"),
        (Decimal("100"), Decimal("0"), Decimal("0"), "Signal price"),
    ),
)
def test_risk_engine_rejects_invalid_inputs(
    balance: Decimal,
    drawdown: Decimal,
    price: Decimal,
    message: str,
) -> None:
    """Verify unsafe numeric inputs fail before position sizing."""
    engine = RiskEngine(settings=RiskSettings())
    signal = _create_signal(price=price)

    with pytest.raises(ValueError, match=message):
        engine.evaluate(
            signal=signal,
            account_balance=balance,
            current_drawdown_pct=drawdown,
        )


# =============================================================================
# Trading Engine Tests
# =============================================================================
def test_trading_engine_approves_an_eligible_signal() -> None:
    """Verify trading decisions include an approved risk result."""
    engine = TradingEngine(risk_engine=RiskEngine(settings=RiskSettings()))

    decision = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("1000"),
        has_open_position=False,
    )

    assert decision.should_execute
    assert decision.risk_result is not None
    assert decision.risk_result.approved
    assert not decision.reason


@pytest.mark.parametrize(
    ("signal_type", "has_position", "reason"),
    (
        (SignalType.HOLD, False, "hold signal"),
        (SignalType.BUY, True, "position already exists"),
    ),
)
def test_trading_engine_blocks_hold_or_duplicate_position(
    signal_type: SignalType,
    has_position: bool,
    reason: str,
) -> None:
    """Verify non-executable trading decisions do not invoke order flow."""
    engine = TradingEngine(risk_engine=RiskEngine(settings=RiskSettings()))

    decision = engine.evaluate(
        signal=_create_signal(signal_type=signal_type),
        account_balance=Decimal("1000"),
        has_open_position=has_position,
    )

    assert not decision.should_execute
    assert decision.risk_result is None
    assert reason in decision.reason


def test_trading_engine_enforces_min_signal_confidence() -> None:
    """Verify TradingEngine rejects signals below min_signal_confidence."""
    engine = TradingEngine(
        risk_engine=RiskEngine(settings=RiskSettings()),
        min_signal_confidence=Decimal("0.80"),
    )

    # Signal with 0.70 confidence < 0.80 min threshold
    low_confidence_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.70"),
        strategy_name="test",
        generated_at=_NOW,
    )

    decision = engine.evaluate(
        signal=low_confidence_signal,
        account_balance=Decimal("1000"),
        has_open_position=False,
    )

    assert not decision.should_execute
    assert decision.risk_result is None
    assert "below minimum threshold" in decision.reason

    # Signal with 0.85 confidence >= 0.80 min threshold
    high_confidence_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.85"),
        strategy_name="test",
        generated_at=_NOW,
    )

    approved_decision = engine.evaluate(
        signal=high_confidence_signal,
        account_balance=Decimal("1000"),
        has_open_position=False,
    )

    assert approved_decision.should_execute
    assert approved_decision.risk_result is not None


@pytest.mark.parametrize(
    ("open_positions", "maximum", "should_execute"),
    (
        ((), 2, True),
        (
            (
                _create_position(
                    symbol="ETHUSDT",
                    side=PositionSide.LONG,
                    quantity=Decimal("1"),
                    entry_price=Decimal("100"),
                    current_price=Decimal("100"),
                    unrealized_pnl=Decimal("0"),
                ),
            ),
            2,
            True,
        ),
        (
            (
                _create_position(
                    symbol="ETHUSDT",
                    side=PositionSide.LONG,
                    quantity=Decimal("1"),
                    entry_price=Decimal("100"),
                    current_price=Decimal("100"),
                    unrealized_pnl=Decimal("0"),
                ),
                _create_position(
                    symbol="SOLUSDT",
                    side=PositionSide.SHORT,
                    quantity=Decimal("1"),
                    entry_price=Decimal("100"),
                    current_price=Decimal("100"),
                    unrealized_pnl=Decimal("0"),
                ),
            ),
            2,
            False,
        ),
    ),
)
def test_trading_engine_enforces_portfolio_capacity(
    open_positions: tuple[Position, ...],
    maximum: int,
    should_execute: bool,
) -> None:
    """Allow candidates only while the portfolio remains below capacity."""
    engine = TradingEngine(
        risk_engine=RiskEngine(settings=RiskSettings(max_open_positions=maximum)),
    )

    decision = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("1000"),
        has_open_position=False,
        open_positions=open_positions,
    )

    assert decision.should_execute is should_execute

    if not should_execute:
        assert decision.risk_result is None
        assert "Maximum open positions" in decision.reason


def test_trading_engine_rejects_duplicate_symbol_from_portfolio_snapshot() -> None:
    """Reject a duplicate even when a caller supplied a stale boolean flag."""
    engine = TradingEngine(risk_engine=RiskEngine(settings=RiskSettings()))
    positions = (
        _create_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            current_price=Decimal("100"),
            unrealized_pnl=Decimal("0"),
        ),
    )

    decision = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("1000"),
        has_open_position=False,
        open_positions=positions,
    )

    assert not decision.should_execute
    assert decision.risk_result is None
    assert "position already exists" in decision.reason


def test_trading_engine_rejects_over_capacity_portfolio_safely() -> None:
    """Reject invalid over-capacity snapshots without invoking trade-level risk."""
    engine = TradingEngine(
        risk_engine=RiskEngine(settings=RiskSettings(max_open_positions=1)),
    )
    positions = (
        _create_position(
            symbol="ETHUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            current_price=Decimal("100"),
            unrealized_pnl=Decimal("0"),
        ),
        _create_position(
            symbol="SOLUSDT",
            side=PositionSide.SHORT,
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            current_price=Decimal("100"),
            unrealized_pnl=Decimal("0"),
        ),
    )

    decision = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("1000"),
        has_open_position=False,
        open_positions=positions,
    )

    assert not decision.should_execute
    assert decision.risk_result is None
    assert "Maximum open positions" in decision.reason


def test_trading_engine_runs_trade_level_risk_after_portfolio_approval() -> None:
    """Keep existing drawdown rejection after a portfolio gate approval."""
    engine = TradingEngine(risk_engine=RiskEngine(settings=RiskSettings()))

    decision = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("1000"),
        has_open_position=False,
        open_positions=(),
        current_drawdown_pct=Decimal("0.10"),
    )

    assert not decision.should_execute
    assert decision.risk_result is not None
    assert "Maximum account drawdown" in decision.reason


# =============================================================================
# PnL Engine Tests
# =============================================================================
def test_pnl_engine_calculates_long_and_short_realized_pnl() -> None:
    """Verify realized PnL is side-aware and deducts fees."""
    engine = PnLEngine()

    long_pnl = engine.calculate_realized(
        side=PositionSide.LONG,
        entry_price=Decimal("100"),
        exit_price=Decimal("110"),
        quantity=Decimal("2"),
        entry_fee=Decimal("1"),
        exit_fee=Decimal("1"),
    )
    short_pnl = engine.calculate_realized(
        side=PositionSide.SHORT,
        entry_price=Decimal("100"),
        exit_price=Decimal("90"),
        quantity=Decimal("2"),
    )

    assert long_pnl == Decimal("18")
    assert short_pnl == Decimal("20")


def test_pnl_engine_calculates_returns_and_unrealized_total() -> None:
    """Verify return percentages and aggregate unrealized PnL."""
    engine = PnLEngine()
    positions = (
        _create_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("2"),
            entry_price=Decimal("100"),
            current_price=Decimal("110"),
            unrealized_pnl=Decimal("20"),
        ),
        _create_position(
            symbol="ETHUSDT",
            side=PositionSide.SHORT,
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            current_price=Decimal("90"),
            unrealized_pnl=Decimal("10"),
        ),
    )

    assert engine.calculate_unrealized(position=positions[0]) == Decimal("20")
    assert engine.calculate_unrealized(position=positions[1]) == Decimal("10")
    assert engine.calculate_total_unrealized(positions=positions) == Decimal("30")
    assert engine.calculate_return_percentage(
        pnl=Decimal("20"),
        entry_price=Decimal("100"),
        quantity=Decimal("2"),
    ) == Decimal("10")
    assert engine.calculate_return_on_margin(
        pnl=Decimal("20"),
        entry_price=Decimal("100"),
        quantity=Decimal("2"),
        leverage=2,
    ) == Decimal("20")


def test_pnl_engine_rejects_invalid_financial_values() -> None:
    """Verify PnL calculations reject zero prices and negative fees."""
    engine = PnLEngine()

    zero_entry_price = Decimal("0")
    valid_entry_price = Decimal("1")
    valid_exit_price = Decimal("2")
    valid_quantity = Decimal("1")
    negative_entry_fee = Decimal("-0.1")

    with pytest.raises(ValueError, match="Entry price"):
        engine.calculate_realized(
            side=PositionSide.LONG,
            entry_price=zero_entry_price,
            exit_price=valid_entry_price,
            quantity=valid_quantity,
        )

    with pytest.raises(ValueError, match="Entry fee"):
        engine.calculate_realized(
            side=PositionSide.LONG,
            entry_price=valid_entry_price,
            exit_price=valid_exit_price,
            quantity=valid_quantity,
            entry_fee=negative_entry_fee,
        )


# =============================================================================
# Portfolio Engine Tests
# =============================================================================
def test_portfolio_engine_calculates_exposure_and_position_metrics() -> None:
    """Verify portfolio aggregation separates long and short exposure."""
    engine = PortfolioEngine()
    positions = (
        _create_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("2"),
            entry_price=Decimal("100"),
            current_price=Decimal("110"),
            unrealized_pnl=Decimal("20"),
        ),
        _create_position(
            symbol="ETHUSDT",
            side=PositionSide.SHORT,
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            current_price=Decimal("90"),
            unrealized_pnl=Decimal("10"),
        ),
    )

    assert engine.calculate_total_notional(positions=positions) == Decimal("310")
    assert engine.calculate_long_exposure(positions=positions) == Decimal("220")
    assert engine.calculate_short_exposure(positions=positions) == Decimal("90")
    assert engine.calculate_net_exposure(positions=positions) == Decimal("130")
    assert engine.calculate_total_unrealized_pnl(
        positions=positions,
    ) == Decimal("30")
    assert engine.calculate_exposure_ratio(
        positions=positions,
        account_equity=Decimal("620"),
    ) == Decimal("0.5")
    assert engine.count_open_positions(positions=positions) == 2
    assert engine.has_position(positions=positions, symbol=" btcusdt ")
    assert not engine.has_position(positions=positions, symbol="SOLUSDT")


def test_portfolio_engine_rejects_invalid_equity() -> None:
    """Verify exposure ratio requires positive account equity."""
    engine = PortfolioEngine()
    positions: tuple[Position, ...] = ()
    zero_equity = Decimal("0")

    with pytest.raises(ValueError, match="Account equity"):
        engine.calculate_exposure_ratio(
            positions=positions,
            account_equity=zero_equity,
        )


def test_signal_engine_inverts_signals_when_enabled() -> None:
    """Verify SignalEngine inverts signals when invert_signals=True."""
    settings = StrategySettings(
        strategy_type=StrategyType.EMA_CROSS,
        fast_period=2,
        slow_period=3,
    )
    resolver = StrategyFactory.create_resolver(settings=settings)
    engine_normal = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.EMA_CROSS,
        invert_signals=False,
    )
    engine_inverted = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.EMA_CROSS,
        invert_signals=True,
    )

    closes = (Decimal("1"), Decimal("1"), Decimal("1"), Decimal("2"))
    candles = [
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M5,
            open_time=_NOW + timedelta(minutes=5 * i),
            close_time=_NOW + timedelta(minutes=5 * (i + 1)),
            open_price=c,
            high_price=c + Decimal("1"),
            low_price=c - Decimal("0.5"),
            close_price=c,
            volume=Decimal("1000"),
        )
        for i, c in enumerate(closes)
    ]

    normal_signal = engine_normal.generate(candles=candles)
    inverted_signal = engine_inverted.generate(candles=candles)

    assert normal_signal.signal_type is SignalType.BUY
    assert inverted_signal.signal_type is SignalType.SELL
    assert inverted_signal.reason is not None and "[INVERTED]" in inverted_signal.reason


def test_risk_engine_slot_sizing_partitions_margin_across_remaining_slots() -> None:
    """Verify that slot sizing divides usable balance equally across slots."""
    settings = RiskSettings(
        slot_sizing_enabled=True,
        slot_margin_buffer_pct=Decimal("0.05"),
        max_position_size_usdt=Decimal("50"),
        leverage=20,
    )
    engine = RiskEngine(settings=settings)

    result = engine.evaluate(
        signal=_create_signal(price=Decimal("100")),
        account_balance=Decimal("9.0"),
        remaining_slots=5,
    )

    assert result.approved
    # usable_balance = 9.0 * 0.95 = 8.55
    # slot_margin = 8.55 / 5 = 1.71
    # notional = 1.71 * 20 = 34.2
    assert result.position.notional == Decimal("34.2")
    assert result.position.quantity == Decimal("0.342")
    assert result.position.leverage == 20


def test_risk_engine_slot_sizing_sequential_five_trades() -> None:
    """Verify 5 sequential entries from 9 USDT each get equal ~1.7 USDT margin."""
    settings = RiskSettings(
        slot_sizing_enabled=True,
        slot_margin_buffer_pct=Decimal("0.05"),
        max_position_size_usdt=Decimal("50"),
        leverage=20,
    )
    engine = RiskEngine(settings=settings)

    balance = Decimal("9.0")
    for remaining in range(5, 0, -1):
        result = engine.evaluate(
            signal=_create_signal(price=Decimal("100")),
            account_balance=balance,
            remaining_slots=remaining,
        )
        assert result.approved
        margin_used = result.position.notional / Decimal(result.position.leverage)
        # Each slot margin should be between 1.6 and 2.0 USDT
        assert Decimal("1.6") <= margin_used <= Decimal("2.0")
        balance -= margin_used

    # Sisa buffer tetap aman di atas 0
    assert balance > Decimal("0")


def test_risk_engine_slot_sizing_insufficient_balance_rejection() -> None:
    """Reject when slot margin at max leverage cannot meet minimum order notional."""
    settings = RiskSettings(
        slot_sizing_enabled=True,
        slot_margin_buffer_pct=Decimal("0.05"),
        min_order_notional_usdt=Decimal("5.0"),
        max_leverage=20,
    )
    engine = RiskEngine(settings=settings)

    result = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("0.10"),
        remaining_slots=1,
    )

    assert not result.approved
    assert result.reason is not None
    assert "minimum order notional" in result.reason


def test_risk_engine_slot_sizing_auto_boosts_leverage_for_min_notional() -> None:
    """Auto-boost leverage up to max_leverage when slot notional < min_notional."""
    settings = RiskSettings(
        slot_sizing_enabled=True,
        slot_margin_buffer_pct=Decimal("0.05"),
        min_order_notional_usdt=Decimal("5.0"),
        leverage=2,
        min_leverage=1,
        max_leverage=10,
    )
    engine = RiskEngine(settings=settings)

    # balance = 3.0, 2 slots => usable = 2.85, slot_margin = 1.425
    # at 2x lev: notional = 2.85 < 5.0. Needs ceil(5.0 / 1.425) = 4x
    result = engine.evaluate(
        signal=_create_signal(price=Decimal("10")),
        account_balance=Decimal("3.0"),
        remaining_slots=2,
    )

    assert result.approved
    assert result.position.leverage >= 4
    assert result.position.notional >= Decimal("5.0")


def test_trading_engine_forwards_remaining_slots() -> None:
    """Verify TradingEngine computes remaining_slots from open positions."""
    settings = RiskSettings(
        slot_sizing_enabled=True,
        slot_margin_buffer_pct=Decimal("0.05"),
        max_open_positions=5,
        max_position_size_usdt=Decimal("50"),
        leverage=20,
    )
    risk_engine = RiskEngine(settings=settings)
    trading_engine = TradingEngine(
        risk_engine=risk_engine,
        portfolio_engine=PortfolioEngine(),
    )

    # 2 existing positions -> 3 remaining slots
    existing_positions = (
        _create_position(
            symbol="ETHUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            current_price=Decimal("100"),
            unrealized_pnl=Decimal("0"),
        ),
        _create_position(
            symbol="SOLUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("1"),
            entry_price=Decimal("100"),
            current_price=Decimal("100"),
            unrealized_pnl=Decimal("0"),
        ),
    )

    decision = trading_engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("9.0"),
        has_open_position=False,
        open_positions=existing_positions,
    )

    assert decision.should_execute
    assert decision.risk_result is not None
    # usable = 8.55 / 3 slots = 2.85 margin * 20 = 57 notional -> capped at 50
    assert decision.risk_result.position.notional == Decimal("50")


def test_risk_engine_dynamic_leverage_incorporates_volatility() -> None:
    """Verify dynamic leverage adapts to coin volatility."""
    settings = RiskSettings(
        dynamic_leverage_enabled=True,
        min_leverage=5,
        max_leverage=20,
    )
    engine = RiskEngine(settings=settings)

    # Low volatility (0.01) -> safe leverage remains capped at max (20)
    low_vol = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("1000"),
        volatility_pct=Decimal("0.01"),
    )
    assert low_vol.position.leverage == 20

    # High volatility (0.06) -> safe leverage is significantly reduced
    high_vol = engine.evaluate(
        signal=_create_signal(),
        account_balance=Decimal("1000"),
        volatility_pct=Decimal("0.06"),
    )
    assert high_vol.position.leverage < 20
    assert high_vol.position.leverage >= 5


def test_risk_engine_stepped_profit_protection() -> None:
    """Verify deterministic stepped protection calculations in RiskEngine."""
    long_pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )

    # Progress & ROI calculation
    assert RiskEngine.calculate_tp_progress(
        position=long_pos, current_price=Decimal("103")
    ) == Decimal("0.3")
    assert RiskEngine.calculate_position_roi(
        position=long_pos, current_price=Decimal("103")
    ) == Decimal("0.03")

    # Step resolution: pure Entry->TP price progress (stepped profit)
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.10")) == 0
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.30")) == 2
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.95")) == 6

    # Independent breakeven policy based on ROI
    assert RiskEngine.resolve_breakeven_step(roi=Decimal("0.10")) == 0
    assert RiskEngine.resolve_breakeven_step(roi=Decimal("0.30")) == 1

    # Leverage invariance: identical price progress yields identical stepped level
    for lev in (1, 5, 20, 50):
        pos_lev = replace(long_pos, leverage=lev)
        prog = RiskEngine.calculate_tp_progress(
            position=pos_lev, current_price=Decimal("103")
        )
        assert prog == Decimal("0.3")
        assert RiskEngine.resolve_protection_step(progress=prog) == 2

    # Stop price calculation for Long:
    # Step 1 (breakeven + fee buffer: 100 * 0.0016 = 0.16 -> 100.16)
    assert RiskEngine.calculate_stepped_stop_loss(position=long_pos, step=1) == Decimal(
        "100.16"
    )

    # Step 2: locked progress = 30% - 20% lag = 10% -> 100 + 10 * 0.10 = 101.0
    assert RiskEngine.calculate_stepped_stop_loss(position=long_pos, step=2) == Decimal(
        "101.0"
    )

    # Short position
    short_pos = Position(
        symbol="BTCUSDT",
        side=PositionSide.SHORT,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        stop_loss=Decimal("105"),
        take_profit=Decimal("90"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )

    # Step 1 for Short: 100 - 0.16 = 99.84
    assert RiskEngine.calculate_stepped_stop_loss(
        position=short_pos, step=1
    ) == Decimal("99.84")

    # Step 2 for Short: locked progress = 10% -> 100 - 10 * 0.10 = 99.0
    assert RiskEngine.calculate_stepped_stop_loss(
        position=short_pos, step=2
    ) == Decimal("99.0")

    # Invalid step raises ValueError
    with pytest.raises(ValueError, match="Invalid protection step"):
        RiskEngine.calculate_stepped_stop_loss(position=long_pos, step=7)


def test_stepped_protection_comprehensive_matrix_and_parity() -> None:
    """Verify full step resolution matrix, BE ROI rules, and live/backtest parity."""
    # 1. Breakeven Step 1 ROI boundary tests
    thresh = Decimal("0.30")
    assert (
        RiskEngine.resolve_breakeven_step(
            roi=Decimal("0.29"), breakeven_roi_threshold=thresh
        )
        == 0
    )
    assert (
        RiskEngine.resolve_breakeven_step(
            roi=Decimal("0.30"), breakeven_roi_threshold=thresh
        )
        == 1
    )
    assert (
        RiskEngine.resolve_breakeven_step(
            roi=Decimal("0.50"), breakeven_roi_threshold=thresh
        )
        == 1
    )

    # 2. Leverage triggers BE faster via ROI, but leaves progress untouched
    pos_1x = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1"),
        entry_price=Decimal("100"),
        current_price=Decimal("100"),
        unrealized_pnl=Decimal("0"),
        stop_loss=Decimal("95"),
        take_profit=Decimal("110"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )
    pos_10x = replace(pos_1x, leverage=10)

    # 1.5% price increase:
    # 1x ROI = 1.5% (< 30% -> BE Step 0)
    # 10x ROI = 15.0% (< 30% -> BE Step 0)
    # 20x ROI = 30.0% (== 30% -> BE Step 1)
    roi_1x = RiskEngine.calculate_position_roi(
        position=pos_1x, current_price=Decimal("101.5")
    )
    roi_10x = RiskEngine.calculate_position_roi(
        position=pos_10x, current_price=Decimal("101.5")
    )
    pos_20x = replace(pos_1x, leverage=20)
    roi_20x = RiskEngine.calculate_position_roi(
        position=pos_20x, current_price=Decimal("101.5")
    )

    assert RiskEngine.resolve_breakeven_step(roi=roi_1x) == 0
    assert RiskEngine.resolve_breakeven_step(roi=roi_10x) == 0
    assert RiskEngine.resolve_breakeven_step(roi=roi_20x) == 1

    # But price progress is IDENTICAL for all leverage levels:
    prog_1x = RiskEngine.calculate_tp_progress(
        position=pos_1x, current_price=Decimal("101.5")
    )
    prog_10x = RiskEngine.calculate_tp_progress(
        position=pos_10x, current_price=Decimal("101.5")
    )
    prog_20x = RiskEngine.calculate_tp_progress(
        position=pos_20x, current_price=Decimal("101.5")
    )
    assert prog_1x == prog_10x == prog_20x == Decimal("0.15")
    assert RiskEngine.resolve_protection_step(progress=prog_1x) == 0
    assert RiskEngine.resolve_protection_step(progress=prog_20x) == 0

    # 3. Pure price progress steps (Steps 2..6)
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.299")) == 0
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.30")) == 2
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.449")) == 2
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.45")) == 3
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.599")) == 3
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.60")) == 4
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.749")) == 4
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.75")) == 5
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.899")) == 5
    assert RiskEngine.resolve_protection_step(progress=Decimal("0.90")) == 6
    assert RiskEngine.resolve_protection_step(progress=Decimal("1.50")) == 6

    # 4. Combined target step (max(be_step, profit_step))
    # BE achieved (ROI >= 30%) but progress < 30% -> Step 1
    assert (
        RiskEngine.resolve_target_protection_step(
            progress=Decimal("0.10"), roi=Decimal("0.35")
        )
        == 1
    )

    # Progress reaches 30% before BE ROI -> Step 2
    assert (
        RiskEngine.resolve_target_protection_step(
            progress=Decimal("0.35"), roi=Decimal("0.10")
        )
        == 2
    )

    # Progress 45% with no BE -> Step 3
    assert (
        RiskEngine.resolve_target_protection_step(
            progress=Decimal("0.50"), roi=Decimal("0.10")
        )
        == 3
    )

    # Both active: progress 60% (Step 4) and BE ROI (Step 1) -> max is Step 4
    assert (
        RiskEngine.resolve_target_protection_step(
            progress=Decimal("0.65"), roi=Decimal("0.50")
        )
        == 4
    )

    # 5. Live Protection Manager and Backtest parity:
    # Live _resolve_step delegates to resolve_target_protection_step
    from botragram.services.position_protection_manager import PositionProtectionManager

    for prog, roi in [
        (Decimal("0.05"), Decimal("0.10")),
        (Decimal("0.15"), Decimal("0.35")),
        (Decimal("0.32"), Decimal("0.10")),
        (Decimal("0.47"), Decimal("0.50")),
        (Decimal("0.92"), Decimal("0.00")),
    ]:
        live_step = PositionProtectionManager.resolve_step(progress=prog, roi=roi)
        engine_step = RiskEngine.resolve_target_protection_step(progress=prog, roi=roi)
        assert live_step == engine_step
