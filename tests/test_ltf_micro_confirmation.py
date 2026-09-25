"""
Botragram

Description:
    Unit and integration tests for low-timeframe (LTF) micro-confirmation.

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

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.app.environment_provider import EnvironmentProvider
from botragram.app.settings_manager import SettingsManager
from botragram.enums import Interval, SignalType, StrategyType
from botragram.indicators.trend.ltf_micro_filter import (
    LtfConfirmationMode,
    evaluate_ltf_micro_confirmation,
)
from botragram.models import Candle, Signal
from botragram.services.opportunity_discovery_service import (
    OpportunityDiscoveryService,
)

_BASE_TIME = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def _make_candles(
    prices: Sequence[tuple[Decimal, Decimal]],  # (open, close)
    *,
    interval: Interval = Interval.M3,
) -> list[Candle]:
    candles: list[Candle] = []
    for i, (open_p, close_p) in enumerate(prices):
        t = _BASE_TIME + timedelta(minutes=i * 3)
        high_p = max(open_p, close_p) + Decimal("1")
        low_p = min(open_p, close_p) - Decimal("1")
        candles.append(
            Candle(
                symbol="BTCUSDT",
                interval=interval,
                open_time=t,
                close_time=t + timedelta(minutes=3),
                open_price=open_p,
                high_price=high_p,
                low_price=low_p,
                close_price=close_p,
                volume=Decimal("100"),
            )
        )
    return candles


def test_evaluate_ltf_empty() -> None:
    """Verify empty candle sequence handling with fail_closed flag."""
    open_res = evaluate_ltf_micro_confirmation([], fail_closed=False)
    assert open_res.is_aligned_with_buy is True
    assert open_res.is_aligned_with_sell is True
    assert open_res.ema_value is None

    closed_res = evaluate_ltf_micro_confirmation([], fail_closed=True)
    assert closed_res.is_aligned_with_buy is False
    assert closed_res.is_aligned_with_sell is False


def test_evaluate_ltf_direction_mode() -> None:
    """Verify direction mode validates bullish and bearish candles."""
    bullish_candles = _make_candles([(Decimal("100"), Decimal("105"))])
    res_bull = evaluate_ltf_micro_confirmation(
        bullish_candles,
        mode=LtfConfirmationMode.DIRECTION,
    )
    assert res_bull.is_aligned_with_buy is True
    assert res_bull.is_aligned_with_sell is False
    assert res_bull.mode is LtfConfirmationMode.DIRECTION

    bearish_candles = _make_candles([(Decimal("105"), Decimal("100"))])
    res_bear = evaluate_ltf_micro_confirmation(
        bearish_candles,
        mode=LtfConfirmationMode.DIRECTION,
    )
    assert res_bear.is_aligned_with_buy is False
    assert res_bear.is_aligned_with_sell is True


def test_evaluate_ltf_ema_mode() -> None:
    """Verify EMA mode compares latest close against micro EMA."""
    # 15 rising candles: close will be above EMA9
    rising_pairs = [
        (Decimal("100") + Decimal(i * 2), Decimal("102") + Decimal(i * 2))
        for i in range(15)
    ]
    candles = _make_candles(rising_pairs)
    res = evaluate_ltf_micro_confirmation(
        candles,
        mode=LtfConfirmationMode.EMA,
        ema_period=9,
    )
    assert res.ema_value is not None
    assert res.latest_close > res.ema_value
    assert res.is_aligned_with_buy is True
    assert res.is_aligned_with_sell is False


def test_evaluate_ltf_both_mode() -> None:
    """Verify BOTH mode requires both candle direction and EMA alignment."""
    # 15 candles rising, but last candle is a slight pullback (bearish candle above EMA)
    pairs = [
        (Decimal("100") + Decimal(i * 2), Decimal("102") + Decimal(i * 2))
        for i in range(14)
    ]
    # 15th candle: open=132, close=130 (bearish candle, but well above EMA9)
    pairs.append((Decimal("132"), Decimal("130")))
    candles = _make_candles(pairs)

    res = evaluate_ltf_micro_confirmation(
        candles,
        mode=LtfConfirmationMode.BOTH,
        ema_period=9,
    )
    assert res.ema_value is not None
    assert res.latest_close > res.ema_value
    # Because candle is bearish (close < open), BUY is not aligned under BOTH mode
    assert res.is_aligned_with_buy is False
    # And because close > EMA, SELL is also not aligned under BOTH mode
    assert res.is_aligned_with_sell is False


class _FakeMarketService:
    def __init__(
        self, candles_by_key: dict[tuple[str, Interval], list[Candle]]
    ) -> None:
        self._candles = candles_by_key

    async def get_trading_symbols(self, *, quote_asset: str) -> Sequence[str]:
        return ("BTCUSDT", "ETHUSDT")

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        persist: bool = True,
        prefer_stored: bool = False,
        as_of: datetime | None = None,
    ) -> Sequence[Candle]:
        candles = self._candles.get((symbol, interval), [])
        if as_of is not None:
            candles = [c for c in candles if c.close_time <= as_of]
        return candles[-limit:]


class _FakeStrategyService:
    def __init__(self, signals_by_symbol: dict[str, Signal]) -> None:
        self._signals = signals_by_symbol

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        symbol = candles[-1].symbol
        return self._signals[symbol]

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        symbol = candles[-1].symbol
        return self._signals[symbol]

    async def save_signal(self, *, signal: Signal) -> None:
        pass


@pytest.mark.asyncio
async def test_opportunity_discovery_ltf_filtering() -> None:
    """Verify OpportunityDiscoveryService rejects signals misaligned with LTF."""
    now = _BASE_TIME + timedelta(hours=5)

    # 15m main candles for BTC and ETH
    btc_m15 = [
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M15,
            open_time=now - timedelta(minutes=15),
            close_time=now,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("99"),
            close_price=Decimal("104"),
            volume=Decimal("1000"),
        )
    ]
    eth_m15 = [
        Candle(
            symbol="ETHUSDT",
            interval=Interval.M15,
            open_time=now - timedelta(minutes=15),
            close_time=now,
            open_price=Decimal("100"),
            high_price=Decimal("105"),
            low_price=Decimal("99"),
            close_price=Decimal("104"),
            volume=Decimal("1000"),
        )
    ]

    # LTF 3m candles:
    # BTC has a BEARISH micro candle (open=105, close=104)
    btc_m3 = [
        Candle(
            symbol="BTCUSDT",
            interval=Interval.M3,
            open_time=now - timedelta(minutes=3),
            close_time=now,
            open_price=Decimal("105"),
            high_price=Decimal("106"),
            low_price=Decimal("103"),
            close_price=Decimal("104"),
            volume=Decimal("200"),
        )
    ]
    # ETH has a BULLISH micro candle (open=102, close=104)
    eth_m3 = [
        Candle(
            symbol="ETHUSDT",
            interval=Interval.M3,
            open_time=now - timedelta(minutes=3),
            close_time=now,
            open_price=Decimal("102"),
            high_price=Decimal("105"),
            low_price=Decimal("101"),
            close_price=Decimal("104"),
            volume=Decimal("200"),
        )
    ]

    candles_data = {
        ("BTCUSDT", Interval.M15): btc_m15,
        ("ETHUSDT", Interval.M15): eth_m15,
        ("BTCUSDT", Interval.M3): btc_m3,
        ("ETHUSDT", Interval.M3): eth_m3,
    }
    market_service = _FakeMarketService(candles_data)

    # Both symbols generate BUY signals
    signals_data = {
        "BTCUSDT": Signal(
            symbol="BTCUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("104"),
            confidence=Decimal("0.80"),
            strategy_name=StrategyType.EMA_CROSS.value,
            generated_at=now,
            reason="Test BUY",
        ),
        "ETHUSDT": Signal(
            symbol="ETHUSDT",
            signal_type=SignalType.BUY,
            price=Decimal("104"),
            confidence=Decimal("0.80"),
            strategy_name=StrategyType.EMA_CROSS.value,
            generated_at=now,
            reason="Test BUY",
        ),
    }
    strategy_service = _FakeStrategyService(signals_data)

    # With LTF confirmation enabled: BTC is rejected (BUY with bearish 3m), ETH accepted
    service_ltf = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        ltf_confirmation_enabled=True,
        ltf_interval=Interval.M3,
        ltf_confirmation_mode="direction",
        utc_now=lambda: now,
    )
    result = await service_ltf.discover_symbols(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval=Interval.M15,
        candle_limit=1,
        top_n=2,
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert len(result) == 1
    assert result[0].symbol == "ETHUSDT"

    # With LTF confirmation disabled: both BTC and ETH accepted
    service_disabled = OpportunityDiscoveryService(
        market_service=market_service,
        strategy_service=strategy_service,
        ltf_confirmation_enabled=False,
        utc_now=lambda: now,
    )
    result_disabled = await service_disabled.discover_symbols(
        symbols=("BTCUSDT", "ETHUSDT"),
        interval=Interval.M15,
        candle_limit=1,
        top_n=2,
        strategy_type=StrategyType.EMA_CROSS,
    )
    assert len(result_disabled) == 2
    assert {s.symbol for s in result_disabled} == {"BTCUSDT", "ETHUSDT"}


def test_settings_manager_ltf_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify SettingsManager defaults for LTF settings."""
    env_file = tmp_path / ".env"
    env_file.write_text("ACTIVE_EXCHANGE=BITGET\n", encoding="utf-8")
    monkeypatch.setenv("BOTRAGRAM_ENV_FILE", str(env_file))
    monkeypatch.delenv("LTF_CONFIRMATION_ENABLED", raising=False)
    monkeypatch.delenv("LTF_TIMEFRAME", raising=False)
    monkeypatch.delenv("LTF_CONFIRMATION_MODE", raising=False)
    monkeypatch.delenv("LTF_EMA_PERIOD", raising=False)

    provider = EnvironmentProvider(env_path=str(env_file))
    manager = SettingsManager(environment_provider=provider)
    settings = manager.load()

    assert settings.strategy.ltf_confirmation_enabled is False
    assert settings.strategy.ltf_interval is Interval.M3
    assert settings.strategy.ltf_confirmation_mode == "direction"
    assert settings.strategy.ltf_ema_period == 9


def test_settings_manager_ltf_custom_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify SettingsManager parses custom LTF settings correctly."""
    env_file = tmp_path / ".env"
    env_content = (
        "ACTIVE_EXCHANGE=BITGET\n"
        "LTF_CONFIRMATION_ENABLED=true\n"
        "LTF_TIMEFRAME=1m\n"
        "LTF_CONFIRMATION_MODE=both\n"
        "LTF_EMA_PERIOD=14\n"
    )
    env_file.write_text(env_content, encoding="utf-8")
    monkeypatch.setenv("BOTRAGRAM_ENV_FILE", str(env_file))
    monkeypatch.setenv("LTF_CONFIRMATION_ENABLED", "true")
    monkeypatch.setenv("LTF_TIMEFRAME", "1m")
    monkeypatch.setenv("LTF_CONFIRMATION_MODE", "both")
    monkeypatch.setenv("LTF_EMA_PERIOD", "14")

    provider = EnvironmentProvider(env_path=str(env_file))
    manager = SettingsManager(environment_provider=provider)
    settings = manager.load()

    assert settings.strategy.ltf_confirmation_enabled is True
    assert settings.strategy.ltf_interval is Interval.M1
    assert settings.strategy.ltf_confirmation_mode == "both"
    assert settings.strategy.ltf_ema_period == 14
