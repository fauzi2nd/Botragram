"""
Botragram

Description:
    Regression tests for dynamic ATR-based trailing stop loss protection.

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
from datetime import UTC, datetime
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.enums import PositionSide, TradeMode
from botragram.exchanges.binance.futures_client import (
    BinanceFuturesExchangeClient,
)
from botragram.exchanges.binance.mapper import BinanceExchangeMapper
from botragram.exchanges.binance.rest import BinanceRestClient
from botragram.models import Position, Ticker
from botragram.services import PositionProtectionManager
from botragram.storage.memory import MemoryPositionRepository

_NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _create_mock_client() -> BinanceFuturesExchangeClient:
    return BinanceFuturesExchangeClient(
        rest=BinanceRestClient(base_url="https://example.test"),
        mapper=BinanceExchangeMapper(),
    )


def _create_ticker(*, symbol: str, price: Decimal) -> Ticker:
    return Ticker(
        symbol=symbol,
        bid_price=price,
        ask_price=price,
        last_price=price,
        timestamp=_NOW,
    )


def test_trailing_stop_risk_settings_validation() -> None:
    """Validate trailing stop configuration constraints in RiskSettings."""
    # Valid trailing stop configuration
    settings = RiskSettings(
        trailing_stop_enabled=True,
        trailing_stop_trigger_pct=Decimal("0.02"),
        trailing_stop_distance_pct=Decimal("0.01"),
    )
    assert settings.trailing_stop_enabled is True
    assert settings.trailing_stop_trigger_pct == Decimal("0.02")
    assert settings.trailing_stop_distance_pct == Decimal("0.01")

    # Invalid: distance >= trigger
    with pytest.raises(ValueError, match="less than trigger percentage"):
        RiskSettings(
            trailing_stop_enabled=True,
            trailing_stop_trigger_pct=Decimal("0.01"),
            trailing_stop_distance_pct=Decimal("0.01"),
        )

    # Invalid: non-positive trigger
    with pytest.raises(ValueError, match="strictly between 0 and 1"):
        RiskSettings(
            trailing_stop_enabled=True,
            trailing_stop_trigger_pct=Decimal("0"),
            trailing_stop_distance_pct=Decimal("0.01"),
        )


@pytest.mark.asyncio
async def test_trailing_stop_long_advancement() -> None:
    """Advance trailing stop behind peak price for a LONG position."""
    position_repository = MemoryPositionRepository()
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=position_repository,
        exchange_client=_create_mock_client(),
        trailing_stop_enabled=True,
        trailing_stop_trigger_pct=Decimal("0.015"),
        trailing_stop_distance_pct=Decimal("0.008"),
        position_refresh_seconds=0.001,
    )

    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("100.0"),
        stop_loss=Decimal("98.0"),
        take_profit=Decimal("110.0"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )
    await position_repository.save(position=position)

    # Tick 1: Price moves up 0.5% (100.5) -> Below 1.5% trigger -> SL unchanged
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("100.5"))
    )
    stored = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("98.0")

    # Tick 2: Price reaches 102.0 (profit 2.0% >= trigger 1.5%)
    # Candidate stop = 102.0 * (1 - 0.008) = 101.184 > 98.0 -> SL advances
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("102.0"))
    )
    stored = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("101.184")

    # Tick 3: Pullback to 101.5 -> Peak remains 102.0 -> SL not lowered
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("101.5"))
    )
    stored = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("101.184")

    # Tick 4: Higher high 105.0 -> Peak 105.0 -> Stop = 105 * 0.992 = 104.16
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("105.0"))
    )
    stored = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("104.16")


@pytest.mark.asyncio
async def test_trailing_stop_short_advancement() -> None:
    """Advance trailing stop behind lowest price for a SHORT position."""
    position_repository = MemoryPositionRepository()
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=position_repository,
        exchange_client=_create_mock_client(),
        trailing_stop_enabled=True,
        trailing_stop_trigger_pct=Decimal("0.015"),
        trailing_stop_distance_pct=Decimal("0.008"),
        position_refresh_seconds=0.001,
    )

    position = Position(
        symbol="ETHUSDT",
        side=PositionSide.SHORT,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("100.0"),
        stop_loss=Decimal("102.0"),
        take_profit=Decimal("90.0"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )
    await position_repository.save(position=position)

    # Tick 1: Price drops 0.5% (99.5) -> Below 1.5% trigger -> SL unchanged
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="ETHUSDT", price=Decimal("99.5"))
    )
    stored = await position_repository.get_by_symbol(symbol="ETHUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("102.0")

    # Tick 2: Price drops to 98.0 (profit 2.0% >= trigger 1.5%)
    # Candidate stop = 98.0 * (1 + 0.008) = 98.784 < 102.0 -> SL advances (tighter)
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="ETHUSDT", price=Decimal("98.0"))
    )
    stored = await position_repository.get_by_symbol(symbol="ETHUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("98.784")

    # Tick 3: Bounce to 98.5 -> Peak remains 98.0 -> SL not raised
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="ETHUSDT", price=Decimal("98.5"))
    )
    stored = await position_repository.get_by_symbol(symbol="ETHUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("98.784")

    # Tick 4: Lower low 95.0 -> Peak 95.0 -> Stop = 95 * 1.008 = 95.76
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="ETHUSDT", price=Decimal("95.0"))
    )
    stored = await position_repository.get_by_symbol(symbol="ETHUSDT")
    assert stored is not None
    assert stored.stop_loss == Decimal("95.76")


@pytest.mark.asyncio
async def test_trailing_stop_cleared_on_position_close() -> None:
    """Clear in-memory peak tracking when position is closed/absent."""
    position_repository = MemoryPositionRepository()
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=position_repository,
        exchange_client=_create_mock_client(),
        trailing_stop_enabled=True,
        trailing_stop_trigger_pct=Decimal("0.015"),
        trailing_stop_distance_pct=Decimal("0.008"),
        position_refresh_seconds=0.001,
    )

    position = Position(
        symbol="SOLUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("100.0"),
        stop_loss=Decimal("98.0"),
        take_profit=Decimal("110.0"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )
    await position_repository.save(position=position)

    # Establish peak price
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="SOLUSDT", price=Decimal("103.0"))
    )
    assert len(manager.peak_prices) > 0

    # Delete position and notify coordinator
    await position_repository.delete(symbol="SOLUSDT")
    manager.lifecycle_coordinator.record_position_deletion(symbol="SOLUSDT")

    # Next tick with no active position clears the peak price cache
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="SOLUSDT", price=Decimal("103.0"))
    )
    assert len(manager.peak_prices) == 0


def test_position_pending_stop_allows_same_step_when_tightened() -> None:
    """Verify Position permits pending stop replacement at same step if tightened."""
    # LONG position tightening stop loss from 98.0 to 99.0 at step 2
    pos_long = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("102.0"),
        stop_loss=Decimal("98.0"),
        take_profit=Decimal("110.0"),
        unrealized_pnl=Decimal("2.0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        protection_step=2,
        pending_stop_loss=Decimal("99.0"),
        pending_stop_loss_client_algo_id="bsl-123456",
        pending_protection_step=2,
    )
    assert pos_long.pending_stop_loss == Decimal("99.0")
    assert pos_long.pending_protection_step == 2

    # SHORT position tightening stop loss from 102.0 to 101.0 at step 1
    pos_short = Position(
        symbol="ETHUSDT",
        side=PositionSide.SHORT,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("98.0"),
        stop_loss=Decimal("102.0"),
        take_profit=Decimal("90.0"),
        unrealized_pnl=Decimal("2.0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
        protection_step=1,
        pending_stop_loss=Decimal("101.0"),
        pending_stop_loss_client_algo_id="bsl-123456",
        pending_protection_step=1,
    )
    assert pos_short.pending_stop_loss == Decimal("101.0")


def test_position_pending_stop_rejects_loosened_or_regressed_step() -> None:
    """Verify Position rejects pending replacements that regress step or loosen stop."""
    import pytest

    # Rejection 1: Regressing protection step from 2 to 1
    with pytest.raises(ValueError, match="must not regress current protection"):
        Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("1.0"),
            entry_price=Decimal("100.0"),
            current_price=Decimal("102.0"),
            stop_loss=Decimal("98.0"),
            take_profit=Decimal("110.0"),
            unrealized_pnl=Decimal("2.0"),
            leverage=1,
            opened_at=_NOW,
            updated_at=_NOW,
            protection_step=2,
            pending_stop_loss=Decimal("99.0"),
            pending_stop_loss_client_algo_id="bsl-123456",
            pending_protection_step=1,
        )

    # Rejection 2: Same step 2, but stop loss is loosened (97.0 <= 98.0 for LONG)
    with pytest.raises(ValueError, match="must tighten stop loss"):
        Position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            quantity=Decimal("1.0"),
            entry_price=Decimal("100.0"),
            current_price=Decimal("102.0"),
            stop_loss=Decimal("98.0"),
            take_profit=Decimal("110.0"),
            unrealized_pnl=Decimal("2.0"),
            leverage=1,
            opened_at=_NOW,
            updated_at=_NOW,
            protection_step=2,
            pending_stop_loss=Decimal("97.0"),
            pending_stop_loss_client_algo_id="bsl-123456",
            pending_protection_step=2,
        )


def test_tiered_trailing_stop_risk_settings_validation() -> None:
    """Validate tier constraints in RiskSettings."""
    # Tier 2 trigger <= Tier 1 trigger
    with pytest.raises(ValueError, match="tier 2 trigger must exceed tier 1"):
        RiskSettings(
            trailing_stop_enabled=True,
            trailing_stop_trigger_pct=Decimal("0.02"),
            trailing_stop_distance_pct=Decimal("0.01"),
            trailing_stop_tier2_trigger_pct=Decimal("0.015"),
            trailing_stop_tier2_distance_pct=Decimal("0.005"),
        )

    # Tier 2 distance >= Tier 1 distance
    with pytest.raises(ValueError, match="tier 2 distance must be strictly between"):
        RiskSettings(
            trailing_stop_enabled=True,
            trailing_stop_trigger_pct=Decimal("0.015"),
            trailing_stop_distance_pct=Decimal("0.008"),
            trailing_stop_tier2_trigger_pct=Decimal("0.025"),
            trailing_stop_tier2_distance_pct=Decimal("0.009"),
        )

    # Tier 3 trigger <= Tier 2 trigger
    with pytest.raises(ValueError, match="tier 3 trigger must exceed tier 2"):
        RiskSettings(
            trailing_stop_enabled=True,
            trailing_stop_trigger_pct=Decimal("0.015"),
            trailing_stop_distance_pct=Decimal("0.008"),
            trailing_stop_tier2_trigger_pct=Decimal("0.025"),
            trailing_stop_tier2_distance_pct=Decimal("0.005"),
            trailing_stop_tier3_trigger_pct=Decimal("0.020"),
            trailing_stop_tier3_distance_pct=Decimal("0.002"),
        )


@pytest.mark.asyncio
async def test_dynamic_tiered_trailing_stop_long_advancement() -> None:
    """Advance trailing stop through Tier 1, Tier 2, and Tier 3 for LONG."""
    position_repository = MemoryPositionRepository()
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=position_repository,
        exchange_client=_create_mock_client(),
        trailing_stop_enabled=True,
        trailing_stop_trigger_pct=Decimal("0.012"),
        trailing_stop_distance_pct=Decimal("0.006"),
        trailing_stop_tier2_trigger_pct=Decimal("0.020"),
        trailing_stop_tier2_distance_pct=Decimal("0.0035"),
        trailing_stop_tier3_trigger_pct=Decimal("0.035"),
        trailing_stop_tier3_distance_pct=Decimal("0.0020"),
        position_refresh_seconds=0.001,
    )

    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.LONG,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("100.0"),
        stop_loss=Decimal("98.0"),
        take_profit=Decimal("110.0"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )
    await position_repository.save(position=position)

    # Tick 1: Price 101.5 (+1.5%) -> Tier 1 (distance 0.006)
    # Stop = 101.5 * (1 - 0.006) = 100.891
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("101.5"))
    )
    pos = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert pos is not None
    assert pos.stop_loss == Decimal("100.891")

    # Tick 2: Price surges to 102.5 (+2.5%) -> Tier 2 (distance 0.0035)
    # Stop = 102.5 * (1 - 0.0035) = 102.14125
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("102.5"))
    )
    pos = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert pos is not None
    assert pos.stop_loss == Decimal("102.14125")

    # Tick 3: Price surges to 104.0 (+4.0%) -> Tier 3 (distance 0.0020)
    # Stop = 104.0 * (1 - 0.0020) = 103.792
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("104.0"))
    )
    pos = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert pos is not None
    assert pos.stop_loss == Decimal("103.792")


@pytest.mark.asyncio
async def test_dynamic_tiered_trailing_stop_short_advancement() -> None:
    """Advance trailing stop through Tier 1, Tier 2, and Tier 3 for SHORT."""
    position_repository = MemoryPositionRepository()
    manager = PositionProtectionManager(
        trade_mode=TradeMode.PAPER,
        position_repository=position_repository,
        exchange_client=_create_mock_client(),
        trailing_stop_enabled=True,
        trailing_stop_trigger_pct=Decimal("0.012"),
        trailing_stop_distance_pct=Decimal("0.006"),
        trailing_stop_tier2_trigger_pct=Decimal("0.020"),
        trailing_stop_tier2_distance_pct=Decimal("0.0035"),
        trailing_stop_tier3_trigger_pct=Decimal("0.035"),
        trailing_stop_tier3_distance_pct=Decimal("0.0020"),
        position_refresh_seconds=0.001,
    )

    position = Position(
        symbol="BTCUSDT",
        side=PositionSide.SHORT,
        quantity=Decimal("1.0"),
        entry_price=Decimal("100.0"),
        current_price=Decimal("100.0"),
        stop_loss=Decimal("102.0"),
        take_profit=Decimal("90.0"),
        unrealized_pnl=Decimal("0"),
        leverage=1,
        opened_at=_NOW,
        updated_at=_NOW,
    )
    await position_repository.save(position=position)

    # Tick 1: Price drops to 98.5 (profit +1.5%) -> Tier 1 (distance 0.006)
    # Stop = 98.5 * (1 + 0.006) = 99.091
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("98.5"))
    )
    pos = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert pos is not None
    assert pos.stop_loss == Decimal("99.091")

    # Tick 2: Price drops to 97.5 (profit +2.5%) -> Tier 2 (distance 0.0035)
    # Stop = 97.5 * (1 + 0.0035) = 97.84125
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("97.5"))
    )
    pos = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert pos is not None
    assert pos.stop_loss == Decimal("97.84125")

    # Tick 3: Price drops to 96.0 (profit +4.0%) -> Tier 3 (distance 0.0020)
    # Stop = 96.0 * (1 + 0.0020) = 96.192
    await manager.on_market_tick(
        ticker=_create_ticker(symbol="BTCUSDT", price=Decimal("96.0"))
    )
    pos = await position_repository.get_by_symbol(symbol="BTCUSDT")
    assert pos is not None
    assert pos.stop_loss == Decimal("96.192")
