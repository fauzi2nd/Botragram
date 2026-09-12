"""
Botragram

Description:
    Unit and integration tests for Account Long-Short Ratio sentiment indicator,
    confluence evaluation, strategy integration, mapper, and service enrichment.

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
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.environment_provider import EnvironmentProvider
from botragram.app.settings_manager import SettingsManager
from botragram.engine.signal_engine import SignalEngine
from botragram.enums import Interval, SignalType, StrategyType
from botragram.exchanges.bybit.client import BybitExchangeClient
from botragram.exchanges.bybit.mapper import BybitExchangeMapper
from botragram.indicators import (
    AccountRatioSentiment,
    evaluate_account_ratio_sentiment,
)
from botragram.models import Candle, Signal
from botragram.services.market_service import MarketService
from botragram.strategies.base.strategy import BaseStrategy
from botragram.strategies.price_action.pinbar_engulfing_ema_rsi import (
    PinbarEngulfingEmaRsiStrategy,
)

_START_TIME = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


class DummyStrategy(BaseStrategy):
    """Concrete dummy strategy for testing base filter hooks."""

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.EMA_CROSS

    @property
    def minimum_candles(self) -> int:
        return 1

    def generate_signal(self, *, candles: Sequence[Candle]) -> Signal:
        del candles
        return Signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("100"),
            confidence=Decimal("0.80"),
            strategy_name=self.strategy_type.value,
            generated_at=_START_TIME,
            reason="Dummy test signal",
        )


def _make_candle(
    *,
    index: int = 0,
    buy_ratio: Decimal | None = None,
    htf_buy_ratio: Decimal | None = None,
) -> Candle:
    """Helper to generate a test candle."""
    open_time = _START_TIME + timedelta(minutes=15 * index)
    close_time = open_time + timedelta(minutes=15)
    return Candle(
        symbol="BTCUSDT",
        interval=Interval.M15,
        open_time=open_time,
        close_time=close_time,
        open_price=Decimal("100"),
        high_price=Decimal("105"),
        low_price=Decimal("95"),
        close_price=Decimal("102"),
        volume=Decimal("1000"),
        buy_ratio=buy_ratio,
        htf_buy_ratio=htf_buy_ratio,
    )


# =============================================================================
# Indicator Unit Tests
# =============================================================================
def test_evaluate_account_ratio_sentiment_balanced() -> None:
    """Verify balanced crowd sentiment between default 25% and 75%."""
    sentiment: AccountRatioSentiment = evaluate_account_ratio_sentiment(
        buy_ratio=Decimal("0.55"),
    )
    assert sentiment.is_neutral is True
    assert sentiment.is_crowded_long is False
    assert sentiment.is_crowded_short is False
    assert sentiment.sell_ratio == Decimal("0.45")
    assert "BALANCED" in sentiment.reason


def test_evaluate_account_ratio_sentiment_crowded_long() -> None:
    """Verify crowded long classification when buy_ratio > 0.75."""
    sentiment: AccountRatioSentiment = evaluate_account_ratio_sentiment(
        buy_ratio=Decimal("0.82"),
    )
    assert sentiment.is_crowded_long is True
    assert sentiment.is_crowded_short is False
    assert sentiment.is_neutral is False
    assert sentiment.sell_ratio == Decimal("0.18")
    assert "CROWDED_LONG" in sentiment.reason


def test_evaluate_account_ratio_sentiment_crowded_short() -> None:
    """Verify crowded short classification when buy_ratio < 0.25."""
    sentiment: AccountRatioSentiment = evaluate_account_ratio_sentiment(
        buy_ratio=Decimal("0.18"),
        sell_ratio=Decimal("0.82"),
    )
    assert sentiment.is_crowded_long is False
    assert sentiment.is_crowded_short is True
    assert sentiment.is_neutral is False
    assert "CROWDED_SHORT" in sentiment.reason


def test_evaluate_account_ratio_sentiment_custom_thresholds() -> None:
    """Verify custom boundary thresholds."""
    sentiment = evaluate_account_ratio_sentiment(
        buy_ratio=Decimal("0.65"),
        max_long_ratio=Decimal("0.60"),
        min_short_ratio=Decimal("0.35"),
    )
    assert sentiment.is_crowded_long is True

    sentiment2 = evaluate_account_ratio_sentiment(
        buy_ratio=Decimal("0.30"),
        max_long_ratio=Decimal("0.60"),
        min_short_ratio=Decimal("0.35"),
    )
    assert sentiment2.is_crowded_short is True


# =============================================================================
# Base Strategy Filter Tests
# =============================================================================
def test_apply_account_ratio_filter_noop_conditions() -> None:
    """Verify no-op on HOLD signal, empty candles, or missing buy_ratio."""
    strategy = DummyStrategy()
    hold_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.HOLD,
        price=Decimal("100"),
        confidence=Decimal("0.0"),
        strategy_name="test",
        generated_at=_START_TIME,
        reason="Hold",
    )

    # HOLD signal
    res = strategy.apply_account_ratio_filter(
        signal=hold_signal,
        candles=[_make_candle(buy_ratio=Decimal("0.90"))],
    )
    assert res.signal_type is SignalType.HOLD

    # Empty candles
    buy_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.80"),
        strategy_name="test",
        generated_at=_START_TIME,
        reason="Buy",
    )
    res_empty = strategy.apply_account_ratio_filter(
        signal=buy_signal,
        candles=[],
    )
    assert res_empty == buy_signal

    # Candle without buy_ratio
    res_no_ratio = strategy.apply_account_ratio_filter(
        signal=buy_signal,
        candles=[_make_candle(buy_ratio=None)],
    )
    assert res_no_ratio == buy_signal


def test_apply_account_ratio_filter_crowded_long_strict_and_soft() -> None:
    """Verify BUY signal rejection when crowded long."""
    strategy = DummyStrategy()
    buy_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.80"),
        strategy_name="test",
        generated_at=_START_TIME,
        reason="Bullish pattern",
    )
    candles = [_make_candle(buy_ratio=Decimal("0.85"))]

    # Strict mode -> HOLD
    strict_res = strategy.apply_account_ratio_filter(
        signal=buy_signal,
        candles=candles,
        strict=True,
    )
    assert strict_res.signal_type is SignalType.HOLD
    assert strict_res.confidence == Decimal("0.0")
    assert "[REJECTED_LS_RATIO]" in (strict_res.reason or "")

    # Soft mode -> Reduced confidence
    soft_res = strategy.apply_account_ratio_filter(
        signal=buy_signal,
        candles=candles,
        strict=False,
    )
    assert soft_res.signal_type is SignalType.BUY
    assert soft_res.confidence == Decimal("0.65")
    assert "CROWDED_LONG" in (soft_res.reason or "")


def test_apply_account_ratio_filter_crowded_short_strict_and_soft() -> None:
    """Verify SELL signal rejection when crowded short."""
    strategy = DummyStrategy()
    sell_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.SELL,
        price=Decimal("100"),
        confidence=Decimal("0.75"),
        strategy_name="test",
        generated_at=_START_TIME,
        reason="Bearish pattern",
    )
    candles = [_make_candle(buy_ratio=Decimal("0.15"))]

    # Strict mode -> HOLD
    strict_res = strategy.apply_account_ratio_filter(
        signal=sell_signal,
        candles=candles,
        strict=True,
    )
    assert strict_res.signal_type is SignalType.HOLD
    assert strict_res.confidence == Decimal("0.0")
    assert "[REJECTED_LS_RATIO]" in (strict_res.reason or "")

    # Soft mode -> Reduced confidence
    soft_res = strategy.apply_account_ratio_filter(
        signal=sell_signal,
        candles=candles,
        strict=False,
    )
    assert soft_res.signal_type is SignalType.SELL
    assert soft_res.confidence == Decimal("0.60")
    assert "CROWDED_SHORT" in (soft_res.reason or "")


def test_apply_account_ratio_filter_opposing_crowd_allowed() -> None:
    """Verify BUY is allowed when crowd is crowded short (contrarian)."""
    strategy = DummyStrategy()
    buy_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.80"),
        strategy_name="test",
        generated_at=_START_TIME,
        reason="Bullish pattern",
    )
    candles = [_make_candle(buy_ratio=Decimal("0.15"))]
    res = strategy.apply_account_ratio_filter(
        signal=buy_signal,
        candles=candles,
        strict=True,
    )
    assert res.signal_type is SignalType.BUY
    assert res.confidence == Decimal("0.80")


def test_apply_account_ratio_filter_htf_confluence() -> None:
    """Verify higher timeframe confirmation rejects crowded HTF positions."""
    strategy = DummyStrategy()
    buy_signal = Signal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        price=Decimal("100"),
        confidence=Decimal("0.80"),
        strategy_name="test",
        generated_at=_START_TIME,
        reason="Bullish pattern",
    )
    # 15m is uncrowded (0.65 <= 0.70), but 1h HTF is crowded long (0.78 > 0.70)
    candles = [_make_candle(buy_ratio=Decimal("0.65"), htf_buy_ratio=Decimal("0.78"))]

    # Without HTF confirmation -> allowed
    res_no_htf = strategy.apply_account_ratio_filter(
        signal=buy_signal,
        candles=candles,
        max_long_ratio=Decimal("0.70"),
        strict=True,
        confirm_htf=False,
    )
    assert res_no_htf.signal_type is SignalType.BUY

    # With HTF confirmation -> rejected
    res_htf = strategy.apply_account_ratio_filter(
        signal=buy_signal,
        candles=candles,
        max_long_ratio=Decimal("0.70"),
        strict=True,
        confirm_htf=True,
    )
    assert res_htf.signal_type is SignalType.HOLD
    assert "[REJECTED_LS_RATIO]" in (res_htf.reason or "")
    assert "HTF" in (res_htf.reason or "")

    # Both timeframes clean (0.65 and 0.68 <= 0.70) -> allowed
    clean_candles = [
        _make_candle(buy_ratio=Decimal("0.65"), htf_buy_ratio=Decimal("0.68"))
    ]
    res_clean = strategy.apply_account_ratio_filter(
        signal=buy_signal,
        candles=clean_candles,
        max_long_ratio=Decimal("0.70"),
        strict=True,
        confirm_htf=True,
    )
    assert res_clean.signal_type is SignalType.BUY
    assert res_clean.confidence == Decimal("0.80")


# =============================================================================
# PinbarEngulfingEmaRsi Strategy Integration Test
# =============================================================================
def test_pinbar_strategy_account_ratio_filtering() -> None:
    """Verify PinbarEngulfingEmaRsiStrategy honors filter_account_ratio."""
    strategy = PinbarEngulfingEmaRsiStrategy(
        filter_account_ratio=True,
        require_account_ratio_confluence=True,
        max_long_account_ratio=Decimal("0.75"),
    )
    assert strategy.filter_account_ratio is True
    assert strategy.max_long_account_ratio == Decimal("0.75")


# =============================================================================
# Mapper & Exchange Client Unit Tests
# =============================================================================
def test_bybit_mapper_map_account_ratio() -> None:
    """Verify BybitExchangeMapper maps raw account ratio dictionary."""
    mapper = BybitExchangeMapper()
    payload = {
        "symbol": "BTCUSDT",
        "buyRatio": "0.6031",
        "sellRatio": "0.3969",
        "timestamp": "1789221600000",
    }
    ts, buy_ratio, sell_ratio = mapper.map_account_ratio(payload)
    assert buy_ratio == Decimal("0.6031")
    assert sell_ratio == Decimal("0.3969")
    assert ts.year > 2020


@pytest.mark.asyncio
async def test_bybit_client_get_account_ratio() -> None:
    """Verify BybitExchangeClient calls endpoint and returns parsed tuples."""
    mock_rest = AsyncMock()
    mock_rest.get.return_value = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "symbol": "BTCUSDT",
            "category": "linear",
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "buyRatio": "0.6500",
                    "sellRatio": "0.3500",
                    "timestamp": "1672531200000",
                }
            ],
        },
    }
    client = BybitExchangeClient(rest=mock_rest, mapper=BybitExchangeMapper())
    points = await client.get_account_ratio(symbol="BTCUSDT", period="15min", limit=1)
    assert len(points) == 1
    assert points[0][1] == Decimal("0.6500")
    assert points[0][2] == Decimal("0.3500")


# =============================================================================
# Market Service Enrichment Test
# =============================================================================
@pytest.mark.asyncio
async def test_market_service_enrich_candles_with_account_ratio() -> None:
    """Verify MarketService attaches buy_ratio to latest candle."""
    mock_exchange = AsyncMock()
    t0 = _START_TIME
    mock_exchange.get_account_ratio.return_value = (
        (t0, Decimal("0.7800"), Decimal("0.2200")),
    )
    service = MarketService(
        exchange_client=mock_exchange,
        stream_client=AsyncMock(),
        candle_repository=AsyncMock(),
    )

    candles = [_make_candle(index=0), _make_candle(index=1)]
    enriched = await service.enrich_candles_with_account_ratio(candles=candles)

    assert len(enriched) == 2
    assert enriched[0].buy_ratio is None
    assert enriched[0].htf_buy_ratio is None
    assert enriched[1].buy_ratio == Decimal("0.7800")
    assert enriched[1].htf_buy_ratio == Decimal("0.7800")


# =============================================================================
# Signal Engine & Settings Tests
# =============================================================================
def test_signal_engine_account_ratio_confluence() -> None:
    """Verify SignalEngine applies account ratio filtering."""
    engine = SignalEngine(
        strategy_resolver=AsyncMock(),
        default_strategy_type=StrategyType.EMA_CROSS,
        filter_account_ratio=True,
        require_account_ratio_confluence=True,
        confirm_htf_account_ratio=True,
        max_long_account_ratio=Decimal("0.75"),
    )
    assert engine.filter_account_ratio is True
    assert engine.confirm_htf_account_ratio is True
    assert engine.max_long_account_ratio == Decimal("0.75")


def test_settings_manager_account_ratio_loading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify EnvironmentProvider and SettingsManager parse account ratio env."""
    monkeypatch.setenv("FILTER_ACCOUNT_RATIO", "true")
    monkeypatch.setenv("MAX_LONG_ACCOUNT_RATIO", "0.70")
    monkeypatch.setenv("MIN_SHORT_ACCOUNT_RATIO", "0.30")
    monkeypatch.setenv("REQUIRE_ACCOUNT_RATIO_CONFLUENCE", "true")
    monkeypatch.setenv("CONFIRM_HTF_ACCOUNT_RATIO", "true")
    monkeypatch.setenv("ACCOUNT_RATIO_HTF_PERIOD", "1h")
    provider = EnvironmentProvider(env_path=str(tmp_path / "missing.env"))
    manager = SettingsManager(environment_provider=provider)
    settings = manager.load_strategy_settings()
    assert settings.filter_account_ratio is True
    assert settings.max_long_account_ratio == Decimal("0.70")
    assert settings.min_short_account_ratio == Decimal("0.30")
    assert settings.require_account_ratio_confluence is True
    assert settings.confirm_htf_account_ratio is True
    assert settings.account_ratio_htf_period == "1h"
