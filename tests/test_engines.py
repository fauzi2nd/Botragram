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
