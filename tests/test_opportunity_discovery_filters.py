"""
Botragram

Description:
    Dynamic liquidity and extreme volatility opportunity discovery filter tests.

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
from dataclasses import dataclass, field
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
from botragram.config.strategy_settings import StrategySettings
from botragram.enums import Interval, SignalType, StrategyType
from botragram.models import Candle, Signal
from botragram.services import OpportunityDiscoveryService

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


# =============================================================================
# Test Doubles
# =============================================================================
@dataclass(slots=True)
class FakeMarketService:
    """Provide deterministic candle data for filter testing."""

    symbols: tuple[str, ...]
    candles_by_symbol: dict[str, tuple[Candle, ...]] = field(
        default_factory=dict[str, tuple[Candle, ...]]
    )

    async def get_trading_symbols(self, *, quote_asset: str) -> tuple[str, ...]:
        """Return configured symbols."""
        return self.symbols

    async def get_candles(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int,
        persist: bool = True,
        prefer_stored: bool = False,
        as_of: datetime | None = None,
    ) -> tuple[Candle, ...]:
        """Return deterministic candles for one symbol."""
        return self.candles_by_symbol.get(symbol, ())


@dataclass(slots=True)
class FakeStrategyService:
    """Return preconfigured signals."""

    signals: dict[str, Signal] = field(default_factory=dict[str, Signal])
    evaluated_symbols: list[str] = field(default_factory=list[str])

    def generate_signal(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Record evaluation and return signal."""
        symbol = candles[0].symbol
        self.evaluated_symbols.append(symbol)
        return self.signals[symbol]

    async def save_signal(self, *, signal: Signal) -> None:
        """No-op persistence."""
        pass

    async def generate_and_save(
        self,
        *,
        candles: Sequence[Candle],
        strategy_type: StrategyType | None = None,
    ) -> Signal:
        """Record evaluation and return signal."""
        return self.generate_signal(
            candles=candles,
            strategy_type=strategy_type,
        )


def _make_candle(
    *,
    symbol: str,
    open_price: Decimal = Decimal("100"),
    high_price: Decimal = Decimal("100"),
    low_price: Decimal = Decimal("100"),
    close_price: Decimal = Decimal("100"),
    volume: Decimal = Decimal("100"),
    close_time: datetime = _NOW,
) -> Candle:
    """Create a test candle."""
    return Candle(
        symbol=symbol,
        interval=Interval.M15,
        open_time=close_time - timedelta(minutes=15),
        close_time=close_time,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=volume,
    )


def _make_signal(*, symbol: str, price: Decimal = Decimal("100")) -> Signal:
    """Create a test BUY signal."""
    return Signal(
        symbol=symbol,
        signal_type=SignalType.BUY,
        confidence=Decimal("0.90"),
        price=price,
        generated_at=_NOW,
        strategy_name="ema_cross",
    )


# =============================================================================
# Tests
# =============================================================================
@pytest.mark.asyncio
async def test_opportunity_discovery_liquidity_filter_rejects_low_volume(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Require illiquid symbols to be filtered out before signal generation."""
    caplog.set_level("INFO")
    symbol_low_liq = "LOWLIQUSDT"
    symbol_liquid = "BTCUSDT"

    # LOWLIQUSDT: volume 5 * price 10 = 50 USDT notional (< 1000 USDT)
    candle_low_liq = _make_candle(
        symbol=symbol_low_liq,
        close_price=Decimal("10"),
        high_price=Decimal("10"),
        low_price=Decimal("10"),
        open_price=Decimal("10"),
        volume=Decimal("5"),
    )
    # BTCUSDT: volume 100 * price 100 = 10,000 USDT notional (>= 1000 USDT)
    candle_liquid = _make_candle(
        symbol=symbol_liquid,
        close_price=Decimal("100"),
        high_price=Decimal("101"),
        low_price=Decimal("99"),
        open_price=Decimal("100"),
        volume=Decimal("100"),
    )

    market = FakeMarketService(
        symbols=(symbol_low_liq, symbol_liquid),
        candles_by_symbol={
            symbol_low_liq: (candle_low_liq,),
            symbol_liquid: (candle_liquid,),
        },
    )
    strategy = FakeStrategyService(
        signals={
            symbol_low_liq: _make_signal(symbol=symbol_low_liq, price=Decimal("10")),
            symbol_liquid: _make_signal(symbol=symbol_liquid, price=Decimal("100")),
        }
    )

    service = OpportunityDiscoveryService(
        market_service=market,
        strategy_service=strategy,
        candle_request_delay_seconds=0.0,
        utc_now=lambda: _NOW + timedelta(seconds=1),
        filter_min_liquidity=True,
        min_quote_volume_usdt=Decimal("1000"),
    )

    signals = await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=1,
        max_symbols=10,
        top_n=5,
    )

    assert len(signals) == 1
    assert signals[0].symbol == symbol_liquid
    assert symbol_low_liq not in strategy.evaluated_symbols
    assert "Discovery liquidity filter rejected LOWLIQUSDT" in caplog.text


@pytest.mark.asyncio
async def test_opportunity_discovery_extreme_volatility_filter_rejects_pump(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Require extreme volatility candles (> 15%) to be rejected."""
    caplog.set_level("INFO")
    symbol_volatile = "PUMPUSDT"
    symbol_calm = "ETHUSDT"

    # PUMP: high 120, low 90, close 100 -> range 30 / 100 = 30% volatility (> 15%)
    candle_volatile = _make_candle(
        symbol=symbol_volatile,
        open_price=Decimal("95"),
        high_price=Decimal("120"),
        low_price=Decimal("90"),
        close_price=Decimal("100"),
        volume=Decimal("500"),
    )
    # ETH: high 102, low 98, close 100 -> range 4 / 100 = 4% volatility (<= 15%)
    candle_calm = _make_candle(
        symbol=symbol_calm,
        open_price=Decimal("99"),
        high_price=Decimal("102"),
        low_price=Decimal("98"),
        close_price=Decimal("100"),
        volume=Decimal("500"),
    )

    market = FakeMarketService(
        symbols=(symbol_volatile, symbol_calm),
        candles_by_symbol={
            symbol_volatile: (candle_volatile,),
            symbol_calm: (candle_calm,),
        },
    )
    strategy = FakeStrategyService(
        signals={
            symbol_volatile: _make_signal(symbol=symbol_volatile, price=Decimal("100")),
            symbol_calm: _make_signal(symbol=symbol_calm, price=Decimal("100")),
        }
    )

    service = OpportunityDiscoveryService(
        market_service=market,
        strategy_service=strategy,
        candle_request_delay_seconds=0.0,
        utc_now=lambda: _NOW + timedelta(seconds=1),
        filter_extreme_volatility=True,
        max_candle_volatility_pct=Decimal("0.15"),
    )

    signals = await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=1,
        max_symbols=10,
        top_n=5,
    )

    assert len(signals) == 1
    assert signals[0].symbol == symbol_calm
    assert symbol_volatile not in strategy.evaluated_symbols
    assert "Discovery extreme volatility filter rejected PUMPUSDT" in caplog.text


@pytest.mark.asyncio
async def test_opportunity_discovery_filters_disabled_passes_all() -> None:
    """Require all symbols to pass when filters are disabled."""
    symbol = "WEIRDUSDT"
    candle = _make_candle(
        symbol=symbol,
        open_price=Decimal("50"),
        high_price=Decimal("200"),
        low_price=Decimal("50"),
        close_price=Decimal("100"),
        volume=Decimal("1"),  # 100 USDT notional, 150% volatility
    )

    market = FakeMarketService(
        symbols=(symbol,),
        candles_by_symbol={symbol: (candle,)},
    )
    strategy = FakeStrategyService(
        signals={symbol: _make_signal(symbol=symbol, price=Decimal("100"))}
    )

    service = OpportunityDiscoveryService(
        market_service=market,
        strategy_service=strategy,
        candle_request_delay_seconds=0.0,
        utc_now=lambda: _NOW + timedelta(seconds=1),
        filter_min_liquidity=False,
        filter_extreme_volatility=False,
    )

    signals = await service.discover(
        quote_asset="USDT",
        interval=Interval.M15,
        candle_limit=1,
        max_symbols=10,
        top_n=5,
    )

    assert len(signals) == 1
    assert signals[0].symbol == symbol


def test_strategy_settings_discovery_validation() -> None:
    """Require invalid bounds to raise ValueError."""
    with pytest.raises(
        ValueError, match="Discovery max candle volatility pct must be between 0 and 1"
    ):
        StrategySettings(
            discovery_max_candle_volatility_pct=Decimal("0"),
        )

    with pytest.raises(
        ValueError, match="Discovery max candle volatility pct must be between 0 and 1"
    ):
        StrategySettings(
            discovery_max_candle_volatility_pct=Decimal("1.5"),
        )

    with pytest.raises(
        ValueError, match="Discovery min quote volume USDT must not be negative"
    ):
        StrategySettings(
            discovery_min_quote_volume_usdt=Decimal("-10"),
        )


def test_settings_manager_loads_discovery_filter_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify SettingsManager parses discovery filter env variables."""
    monkeypatch.delenv("BOTRAGRAM_ENV_FILE", raising=False)
    monkeypatch.delenv("BOTRAGRAM_PROFILE", raising=False)
    monkeypatch.setenv("DISCOVERY_FILTER_EXTREME_VOLATILITY", "true")
    monkeypatch.setenv("DISCOVERY_MAX_CANDLE_VOLATILITY_PCT", "0.20")
    monkeypatch.setenv("DISCOVERY_FILTER_MIN_LIQUIDITY", "true")
    monkeypatch.setenv("DISCOVERY_MIN_QUOTE_VOLUME_USDT", "5000")

    manager = SettingsManager(
        environment_provider=EnvironmentProvider(
            env_path=str(tmp_path / "missing.env"),
        )
    )
    settings = manager.load_strategy_settings()

    assert settings.discovery_filter_extreme_volatility is True
    assert settings.discovery_max_candle_volatility_pct == Decimal("0.20")
    assert settings.discovery_filter_min_liquidity is True
    assert settings.discovery_min_quote_volume_usdt == Decimal("5000")
