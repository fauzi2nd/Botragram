"""
Botragram

Description:
    Unit tests for Bitget Futures isolated margin support, verifying
    order placement, protection orders, leverage setting, and configuration.

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
from botragram.enums import (
    ExchangeType,
    MarginMode,
    MarketType,
    OrderSide,
    OrderType,
)
from botragram.exchanges.bitget.futures_client import BitgetFuturesExchangeClient
from botragram.exchanges.bitget.mapper import BitgetExchangeMapper
from tests.test_bitget import MockBitgetRestClient


# =============================================================================
# Tests
# =============================================================================
@pytest.mark.asyncio
async def test_bitget_futures_create_order_isolated_margin() -> None:
    """Verify create_order sends marginMode=isolated by default."""
    rest = MockBitgetRestClient()
    client = BitgetFuturesExchangeClient(
        rest=rest,
        mapper=BitgetExchangeMapper(),
        margin_mode=MarginMode.ISOLATED,
    )

    await client.create_order(
        symbol="MUBARAKUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("100"),
    )

    assert ("POST", "/api/v3/trade/place-order") in rest.history
    assert rest.last_data is not None
    assert rest.last_data.get("symbol") == "MUBARAKUSDT"
    assert rest.last_data.get("side") == "sell"
    assert rest.last_data.get("marginMode") == "isolated"


@pytest.mark.asyncio
async def test_bitget_futures_set_leverage_isolated_margin() -> None:
    """Verify set_leverage uses isolated margin when configured."""
    rest = MockBitgetRestClient()
    client = BitgetFuturesExchangeClient(
        rest=rest,
        mapper=BitgetExchangeMapper(),
        margin_mode=MarginMode.ISOLATED,
    )

    await client.set_leverage(
        symbol="MUBARAKUSDT",
        leverage=8,
        hold_side="long",
    )

    assert rest.last_path == "/api/v3/account/set-leverage"
    assert rest.last_data is not None
    assert rest.last_data.get("symbol") == "MUBARAKUSDT"
    assert rest.last_data.get("leverage") == "8"
    assert rest.last_data.get("marginMode") == "isolated"


@pytest.mark.asyncio
async def test_bitget_futures_protection_orders_isolated_margin() -> None:
    """Verify create_protection_orders includes marginMode=isolated."""
    rest = MockBitgetRestClient()
    client = BitgetFuturesExchangeClient(
        rest=rest,
        mapper=BitgetExchangeMapper(),
        margin_mode=MarginMode.ISOLATED,
    )

    await client.create_protection_orders(
        symbol="MUBARAKUSDT",
        side=OrderSide.BUY,
        quantity=Decimal("100"),
        stop_loss=Decimal("0.055"),
        take_profit=Decimal("0.050"),
    )

    assert rest.last_path == "/api/v3/trade/place-strategy-order"
    assert rest.last_data is not None
    assert rest.last_data.get("marginMode") == "isolated"
    assert rest.last_data.get("stopLoss") == "0.055"
    assert rest.last_data.get("takeProfit") == "0.050"


def test_settings_manager_loads_isolated_margin_mode(tmp_path: Path) -> None:
    """Verify SettingsManager parses BITGET_MARGIN_MODE correctly."""
    env_file = tmp_path / ".env.test"
    env_file.write_text(
        "ACTIVE_EXCHANGE=BITGET\n"
        "BITGET_MARKET_TYPE=FUTURES\n"
        "BITGET_MARGIN_MODE=ISOLATED\n",
        encoding="utf-8",
    )
    provider = EnvironmentProvider(env_path=str(env_file), override=True)
    manager = SettingsManager(environment_provider=provider)
    settings = manager.load_exchange_settings(exchange_override=ExchangeType.BITGET)

    assert settings.exchange is ExchangeType.BITGET
    assert settings.market_type is MarketType.FUTURES
    assert settings.margin_mode is MarginMode.ISOLATED
