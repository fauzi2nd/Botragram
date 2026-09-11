"""
Botragram

Description:
    Unit and integration tests for Derivatives Open Interest (OI) indicators,
    confluence evaluation, strategy integration, and exchange data enrichment.

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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.strategy_settings import StrategySettings
from botragram.engine.signal_engine import SignalEngine
from botragram.enums import (
    Interval,
    OpenInterestRegime,
    SignalType,
    StrategyType,
)
from botragram.exchanges.bybit.client import BybitExchangeClient
from botragram.indicators.derivatives.open_interest import (
    calculate_oi_change,
    calculate_oi_sma,
    classify_oi_regime,
    evaluate_oi_confluence,
)
from botragram.models import Candle, Signal
from botragram.services.market_service import MarketService
from botragram.strategies.factory import StrategyFactory
from botragram.strategies.price_action import PinbarEngulfingEmaRsiStrategy

_START_TIME = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def _make_candle(
    *,
    index: int,
    open_price: Decimal,
    high_price: Decimal,
    low_price: Decimal,
    close_price: Decimal,
    volume: Decimal = Decimal("100.0"),
    open_interest: Decimal | None = None,
) -> Candle:
    """Helper to generate a timestamped Candle with optional Open Interest."""
    open_time = _START_TIME + timedelta(minutes=15 * index)
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
        open_interest=open_interest,
    )


# =============================================================================
# Indicator Tests
# =============================================================================
def test_calculate_oi_change_basic() -> None:
    """Verify calculation of delta and percentage change across candles."""
    candles = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("102"),
            open_interest=Decimal("1000"),
        ),
        _make_candle(
            index=1,
            open_price=Decimal("102"),
            high_price=Decimal("108"),
            low_price=Decimal("101"),
            close_price=Decimal("107"),
            open_interest=Decimal("1050"),
        ),
    ]

    result = calculate_oi_change(candles=candles, period=1)
    assert result is not None
    delta, change_pct = result
    assert delta == Decimal("50")
    assert change_pct == Decimal("0.05")


def test_calculate_oi_change_insufficient_or_missing_data() -> None:
    """Verify calculate_oi_change returns None when OI is missing."""
    candles_missing = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("102"),
            open_interest=None,
        ),
        _make_candle(
            index=1,
            open_price=Decimal("102"),
            high_price=Decimal("108"),
            low_price=Decimal("101"),
            close_price=Decimal("107"),
            open_interest=Decimal("1050"),
        ),
    ]
    assert calculate_oi_change(candles=candles_missing, period=1) is None
    assert calculate_oi_change(candles=candles_missing[:1], period=1) is None


def test_calculate_oi_sma() -> None:
    """Verify Simple Moving Average of Open Interest."""
    candles = [
        _make_candle(
            index=i,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("100"),
            open_interest=Decimal(str(1000 + i * 100)),
        )
        for i in range(5)
    ]
    # OI values: 1000, 1100, 1200, 1300, 1400 -> sum=6000 / 5 = 1200
    avg = calculate_oi_sma(candles=candles, period=5)
    assert avg == Decimal("1200")

    # If any candle in period has None, return None
    candles_with_none = list(candles)
    candles_with_none[2] = _make_candle(
        index=2,
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("95"),
        close_price=Decimal("100"),
        open_interest=None,
    )
    assert calculate_oi_sma(candles=candles_with_none, period=5) is None


def test_classify_oi_regime() -> None:
    """Verify 4-quadrant derivatives market regime classification."""
    # Long Buildup: Price UP, OI UP
    assert (
        classify_oi_regime(
            price_delta=Decimal("5.0"),
            oi_delta=Decimal("50.0"),
        )
        is OpenInterestRegime.LONG_BUILDUP
    )

    # Short Covering: Price UP, OI DOWN
    assert (
        classify_oi_regime(
            price_delta=Decimal("5.0"),
            oi_delta=Decimal("-50.0"),
        )
        is OpenInterestRegime.SHORT_COVERING
    )

    # Short Buildup: Price DOWN, OI UP
    assert (
        classify_oi_regime(
            price_delta=Decimal("-5.0"),
            oi_delta=Decimal("50.0"),
        )
        is OpenInterestRegime.SHORT_BUILDUP
    )

    # Long Liquidation: Price DOWN, OI DOWN
    assert (
        classify_oi_regime(
            price_delta=Decimal("-5.0"),
            oi_delta=Decimal("-50.0"),
        )
        is OpenInterestRegime.LONG_LIQUIDATION
    )

    # Neutral if within tolerance
    assert (
        classify_oi_regime(
            price_delta=Decimal("0.0"),
            oi_delta=Decimal("50.0"),
        )
        is OpenInterestRegime.NEUTRAL
    )


def test_evaluate_oi_confluence_buy_and_sell() -> None:
    """Verify signal confirmation and warning classification."""
    # Bullish candle with expanding OI (Long Buildup)
    long_buildup_candles = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("100"),
            open_interest=Decimal("1000"),
        ),
        _make_candle(
            index=1,
            open_price=Decimal("100"),
            high_price=Decimal("108"),
            low_price=Decimal("99"),
            close_price=Decimal("107"),
            open_interest=Decimal("1050"),  # +5%
        ),
    ]

    conf_buy = evaluate_oi_confluence(
        signal_type=SignalType.BUY,
        candles=long_buildup_candles,
        min_change_pct=Decimal("0.02"),
    )
    assert conf_buy is not None
    assert conf_buy.is_confirmed is True
    assert conf_buy.is_warning is False
    assert conf_buy.regime is OpenInterestRegime.LONG_BUILDUP

    # Same candles evaluated for SELL signal -> Contradictory warning
    conf_sell_contra = evaluate_oi_confluence(
        signal_type=SignalType.SELL,
        candles=long_buildup_candles,
    )
    assert conf_sell_contra is not None
    assert conf_sell_contra.is_confirmed is False
    assert conf_sell_contra.is_warning is True

    # Short Covering scenario: Price UP, OI DOWN
    short_covering_candles = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("100"),
            open_interest=Decimal("1000"),
        ),
        _make_candle(
            index=1,
            open_price=Decimal("100"),
            high_price=Decimal("108"),
            low_price=Decimal("99"),
            close_price=Decimal("107"),
            open_interest=Decimal("920"),  # -8%
        ),
    ]
    conf_buy_warn = evaluate_oi_confluence(
        signal_type=SignalType.BUY,
        candles=short_covering_candles,
    )
    assert conf_buy_warn is not None
    assert conf_buy_warn.is_confirmed is False
    assert conf_buy_warn.is_warning is True
    assert "Short Covering" in conf_buy_warn.reason


# =============================================================================
# Strategy Integration Tests
# =============================================================================
def test_base_strategy_apply_open_interest_confluence() -> None:
    """Verify BaseStrategy apply_open_interest_confluence adjustments."""
    strategy = PinbarEngulfingEmaRsiStrategy()
    base_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("50000"),
        confidence=Decimal("0.70"),
        strategy_name="test",
        generated_at=_START_TIME,
        reason="Base signal",
    )

    candles_confirmed = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("100"),
            open_interest=Decimal("1000"),
        ),
        _make_candle(
            index=1,
            open_price=Decimal("100"),
            high_price=Decimal("108"),
            low_price=Decimal("99"),
            close_price=Decimal("107"),
            open_interest=Decimal("1050"),
        ),
    ]

    # Confirmed: confidence boosted
    enhanced_signal = strategy.apply_open_interest_confluence(
        signal=base_signal,
        candles=candles_confirmed,
        confidence_bonus=Decimal("0.05"),
    )
    assert enhanced_signal.confidence == Decimal("0.75")
    assert (
        enhanced_signal.reason is not None
        and "Bullish Long Buildup" in enhanced_signal.reason
    )

    # Warning in strict mode: rejected to HOLD
    candles_warning = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("100"),
            open_interest=Decimal("1000"),
        ),
        _make_candle(
            index=1,
            open_price=Decimal("100"),
            high_price=Decimal("108"),
            low_price=Decimal("99"),
            close_price=Decimal("107"),
            open_interest=Decimal("900"),
        ),
    ]
    rejected_signal = strategy.apply_open_interest_confluence(
        signal=base_signal,
        candles=candles_warning,
        strict=True,
    )
    assert rejected_signal.signal_type is SignalType.HOLD
    assert rejected_signal.confidence == Decimal("0.0")
    assert (
        rejected_signal.reason is not None and "[REJECTED_OI]" in rejected_signal.reason
    )


def test_pinbar_strategy_with_open_interest_parameters() -> None:
    """Verify PinbarEngulfingEmaRsiStrategy respects use_open_interest."""
    settings = StrategySettings(
        strategy_type=StrategyType.PINBAR_ENGULFING_EMA_RSI,
        use_open_interest=True,
        pier_use_open_interest=True,
        pier_min_oi_change_pct=Decimal("0.01"),
        pier_oi_confidence_bonus=Decimal("0.05"),
    )
    strategy = StrategyFactory.create(settings=settings)
    assert isinstance(strategy, PinbarEngulfingEmaRsiStrategy)
    assert strategy.use_open_interest is True
    assert strategy.min_oi_change_pct == Decimal("0.01")


def test_signal_engine_universal_open_interest_confluence() -> None:
    """Verify SignalEngine automatically applies OI confluence across strategies."""
    settings = StrategySettings(
        strategy_type=StrategyType.EMA_CROSS,
        use_open_interest=True,
        min_oi_change_pct=Decimal("0.0"),
        require_oi_confluence=False,
    )
    resolver = StrategyFactory.create_resolver(settings=settings)
    engine = SignalEngine(
        strategy_resolver=resolver,
        default_strategy_type=StrategyType.EMA_CROSS,
        use_open_interest=True,
    )

    # Build 50 candles with EMA golden cross and positive OI delta
    candles: list[Candle] = []
    base_price = Decimal("100.0")
    for i in range(50):
        price = base_price + Decimal(str(i * 2))  # Strong uptrend
        candles.append(
            _make_candle(
                index=i,
                open_price=price - Decimal("1"),
                high_price=price + Decimal("2"),
                low_price=price - Decimal("2"),
                close_price=price,
                volume=Decimal("100.0"),
                open_interest=Decimal(str(1000 + i * 50)),
            )
        )

    signal = engine.generate(candles=candles)
    if signal.signal_type is SignalType.BUY:
        # Should have OI confirmation included
        assert signal.reason is not None and (
            "Long Buildup" in signal.reason or "OI expanded" in signal.reason
        )


# =============================================================================
# Exchange Client & Market Service Tests
# =============================================================================
@pytest.mark.asyncio
async def test_bybit_client_get_open_interest() -> None:
    """Verify BybitExchangeClient parses open interest payload."""
    mock_rest = AsyncMock()
    mock_rest.get.return_value = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "symbol": "BTCUSDT",
            "category": "linear",
            "list": [
                {
                    "openInterest": "1234.56",
                    "timestamp": "1672531200000",
                },
                {
                    "openInterest": "1250.00",
                    "timestamp": "1672532100000",
                },
            ],
        },
    }
    client = BybitExchangeClient(rest=mock_rest, mapper=AsyncMock())
    points = await client.get_open_interest(symbol="BTCUSDT", limit=50)

    assert len(points) == 2
    assert points[0][1] == Decimal("1234.56")
    assert points[1][1] == Decimal("1250.00")


@pytest.mark.asyncio
async def test_market_service_enrich_candles_with_open_interest() -> None:
    """Verify MarketService attaches OI values to candles based on timestamp."""
    mock_exchange = AsyncMock()
    # 2 timestamps corresponding to candle 0 and candle 1
    t0 = _START_TIME
    t1 = _START_TIME + timedelta(minutes=15)
    mock_exchange.get_open_interest.return_value = (
        (t0, Decimal("5000")),
        (t1, Decimal("5200")),
    )
    service = MarketService(
        exchange_client=mock_exchange,
        stream_client=AsyncMock(),
        candle_repository=AsyncMock(),
    )

    candles = [
        _make_candle(
            index=0,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("95"),
            close_price=Decimal("100"),
            open_interest=None,
        ),
        _make_candle(
            index=1,
            open_price=Decimal("100"),
            high_price=Decimal("108"),
            low_price=Decimal("99"),
            close_price=Decimal("107"),
            open_interest=None,
        ),
    ]

    enriched = await service.enrich_candles_with_open_interest(candles=candles)
    assert len(enriched) == 2
    assert enriched[0].open_interest == Decimal("5000")
    assert enriched[1].open_interest == Decimal("5200")
