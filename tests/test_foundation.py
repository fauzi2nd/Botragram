"""
Botragram

Description:
    Unit tests for core foundation modules (utils, config, enums).

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
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.app_settings import AppSettings
from botragram.config.exchange_settings import ExchangeSettings
from botragram.config.market_settings import MarketSettings
from botragram.config.risk_settings import RiskSettings
from botragram.config.strategy_settings import StrategySettings
from botragram.config.telegram_settings import TelegramSettings
from botragram.enums.exchange_type import ExchangeType
from botragram.enums.order_side import OrderSide
from botragram.enums.trade_mode import TradeMode
from botragram.utils.datetime import (
    current_utc_timestamp_ms,
    format_utc_datetime,
)
from botragram.utils.decimal import (
    round_price_precision,
    round_step_size,
    to_decimal,
)
from botragram.utils.formatter import format_currency, format_percentage
from botragram.utils.validator import validate_symbol


def test_decimal_conversions() -> None:
    """Test to_decimal conversion function."""
    assert to_decimal(10) == Decimal("10")
    assert to_decimal("0.005") == Decimal("0.005")
    assert to_decimal(Decimal("1.5")) == Decimal("1.5")


def test_step_size_rounding() -> None:
    """Test rounding quantity based on exchange step size."""
    qty = Decimal("1.23456")
    step = Decimal("0.01")
    rounded = round_step_size(qty, step)
    assert rounded == Decimal("1.23")


def test_tick_size_rounding() -> None:
    """Test rounding price based on exchange tick size."""
    price = Decimal("45123.456")
    tick = Decimal("0.1")
    rounded = round_price_precision(price, tick)
    assert rounded == Decimal("45123.5")


def test_datetime_helpers() -> None:
    """Test datetime timestamp and formatting helpers."""
    ts = current_utc_timestamp_ms()
    assert ts > 0
    formatted = format_utc_datetime()
    assert "UTC" in formatted


def test_formatters() -> None:
    """Test currency and percentage formatters."""
    curr = format_currency(Decimal("100.5"), "USDT")
    assert curr == "100.50 USDT"

    pct = format_percentage(Decimal("0.05"))
    assert pct == "+5.00%"


def test_validator() -> None:
    """Test symbol validation helper."""
    validate_symbol("BTCUSDT")


def test_config_instantiations() -> None:
    """Test default instantiations of settings classes."""
    app_cfg = AppSettings()
    assert app_cfg.trade_mode == TradeMode.PAPER

    ex_cfg = ExchangeSettings()
    assert ex_cfg.exchange_type == ExchangeType.BYBIT

    tg_cfg = TelegramSettings()
    assert tg_cfg.enabled is True

    mkt_cfg = MarketSettings()
    assert mkt_cfg.symbol == "BTCUSDT"

    risk_cfg = RiskSettings()
    assert risk_cfg.leverage == 1

    strat_cfg = StrategySettings()
    assert strat_cfg.fast_period == 9
