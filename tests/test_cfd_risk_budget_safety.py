"""
Botragram

Description:
    Regression tests verifying CFD sizing, currency conversion, and position
    limits remain strictly risk-budget safe and fail closed.

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
from datetime import datetime, timezone
from decimal import Decimal

# =============================================================================
# Third-Party Imports
# =============================================================================
import pytest

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.engine.cfd_financing_engine import CfdFinancingEngine
from botragram.engine.cfd_sizing_engine import CfdSizingEngine
from botragram.engine.risk_engine import RiskEngine
from botragram.engine.trading_engine import TradingEngine
from botragram.enums import AssetClass, MarketType, SignalType
from botragram.models import CfdContractSpec, Signal

# =============================================================================
# Constants
# =============================================================================
_NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Fixture helpers: deterministic contract specs matching fallback values
# Used in is_live=True tests that must supply authoritative metadata.
# ---------------------------------------------------------------------------
_EURUSD_SPEC = CfdContractSpec(
    symbol="EURUSD",
    asset_class=AssetClass.FOREX,
    contract_size=Decimal("100000"),
    pip_size=Decimal("0.0001"),
    tick_size=Decimal("0.00001"),
    min_lot=Decimal("0.01"),
    max_lot=Decimal("100.0"),
    lot_step=Decimal("0.01"),
    default_leverage=500,
    max_leverage=1000,
)
_USDJPY_SPEC = CfdContractSpec(
    symbol="USDJPY",
    asset_class=AssetClass.FOREX,
    contract_size=Decimal("100000"),
    pip_size=Decimal("0.01"),
    tick_size=Decimal("0.001"),
    min_lot=Decimal("0.01"),
    max_lot=Decimal("100.0"),
    lot_step=Decimal("0.01"),
    default_leverage=500,
    max_leverage=1000,
)
_EURJPY_SPEC = CfdContractSpec(
    symbol="EURJPY",
    asset_class=AssetClass.FOREX,
    contract_size=Decimal("100000"),
    pip_size=Decimal("0.01"),
    tick_size=Decimal("0.001"),
    min_lot=Decimal("0.01"),
    max_lot=Decimal("100.0"),
    lot_step=Decimal("0.01"),
    default_leverage=200,
    max_leverage=500,
)


def test_cfd_sizing_normalize_lot_below_minimum() -> None:
    """Raw lots below minimum lot size must return 0 without clamping up."""
    sizing = CfdSizingEngine()
    # EURUSD min_lot = 0.01. Raw lot 0.009 must return 0.
    assert sizing.normalize_lot("EURUSD", Decimal("0.009")) == Decimal("0")
    assert sizing.normalize_lot("EURUSD", Decimal("0.001")) == Decimal("0")
    assert sizing.normalize_lot("EURUSD", Decimal("0.0001")) == Decimal("0")


def test_cfd_sizing_normalize_lot_exact_minimum() -> None:
    """Raw lots exactly at minimum lot size must normalize to min_lot."""
    sizing = CfdSizingEngine()
    assert sizing.normalize_lot("EURUSD", Decimal("0.01")) == Decimal("0.01")


def test_cfd_sizing_normalize_lot_step_rounding_down() -> None:
    """Step normalization must always round down to prevent increasing exposure."""
    sizing = CfdSizingEngine()
    # EURUSD step_lot = 0.01. 0.059 should round down to 0.05, not 0.06.
    assert sizing.normalize_lot("EURUSD", Decimal("0.059")) == Decimal("0.05")
    assert sizing.normalize_lot("EURUSD", Decimal("0.258")) == Decimal("0.25")
    assert sizing.normalize_lot("EURUSD", Decimal("1.999")) == Decimal("1.99")


def test_cfd_currency_conversion_usd_quote() -> None:
    """Instruments quoted in USD require no FX conversion."""
    sizing = CfdSizingEngine(is_live=True)
    sizing.register_contract_spec(_EURUSD_SPEC)
    # EURUSD: contract_size=100000, pip_size=0.0001 -> 10 USD per pip
    pip_val = sizing.calculate_pip_value_per_lot("EURUSD", price=Decimal("1.1000"))
    assert pip_val == Decimal("10.00000000")


def test_cfd_currency_conversion_usd_base() -> None:
    """Instruments with USD base use quote/USD exchange rate."""
    sizing = CfdSizingEngine(is_live=True)
    sizing.register_contract_spec(_USDJPY_SPEC)
    # USDJPY: pip_size=0.01, contract_size=100000 -> 1000 JPY / 150.0 = 6.66666667 USD
    pip_val = sizing.calculate_pip_value_per_lot(
        "USDJPY",
        price=Decimal("150.0"),
    )
    expected = (Decimal("0.01") * Decimal("100000")) / Decimal("150.0")
    assert abs(pip_val - expected) < Decimal("0.00001")


def test_cfd_currency_conversion_non_usd_quote_with_valid_rate() -> None:
    """Non-USD quote pairs apply conversion rate to USD correctly."""
    sizing = CfdSizingEngine(is_live=True)
    sizing.register_contract_spec(_EURJPY_SPEC)
    # EURJPY: contract_size=100000, pip_size=0.01 -> 1000 JPY
    # JPY/USD rate = 0.00666667 (i.e. 1/150) -> 6.66667 USD
    rate = Decimal("0.00666667")
    pip_val = sizing.calculate_pip_value_per_lot(
        "EURJPY",
        price=Decimal("165.0"),
        quote_to_account_rate=rate,
    )
    expected = Decimal("0.01") * Decimal("100000") * rate
    assert abs(pip_val - expected) < Decimal("0.00001")


def test_cfd_currency_conversion_missing_in_live_fails_closed() -> None:
    """Missing or invalid conversion for non-USD quote must fail closed in LIVE."""
    live_sizing = CfdSizingEngine(is_live=True)
    live_sizing.register_contract_spec(_EURJPY_SPEC)
    with pytest.raises(ValueError, match="Currency conversion rate is required"):
        live_sizing.calculate_pip_value_per_lot(
            "EURJPY",
            price=Decimal("165.0"),
            quote_to_account_rate=None,
        )

    with pytest.raises(ValueError, match="cannot default to 1.0 in LIVE"):
        live_sizing.calculate_pip_value_per_lot(
            "EURJPY",
            price=Decimal("165.0"),
            quote_to_account_rate=Decimal("1.0"),
        )


def test_cfd_currency_conversion_paper_allows_fallback() -> None:
    """Paper/test mode retains 1.0 fallback for non-USD quote fixtures."""
    paper_sizing = CfdSizingEngine(is_live=False)
    pip_val = paper_sizing.calculate_pip_value_per_lot(
        "EURJPY",
        price=Decimal("165.0"),
        quote_to_account_rate=None,
    )
    assert pip_val == Decimal("1000.00000000")


def test_trading_engine_cfd_enforces_max_position_size() -> None:
    """CFD trades exceeding max_position_size_usdt must be rejected."""
    cfd_sizing = CfdSizingEngine(is_live=False)
    cfd_financing = CfdFinancingEngine(sizing=cfd_sizing)
    # Set ceiling of 10,000 USDT
    trading_engine = TradingEngine(
        risk_engine=RiskEngine(
            settings=RiskSettings(
                risk_per_trade_pct=Decimal("0.02"),
                max_position_size_usdt=Decimal("10000"),
            ),
        ),
        cfd_sizing_engine=cfd_sizing,
        cfd_financing_engine=cfd_financing,
        market_type=MarketType.CFD,
    )

    # EURUSD entry at 1.1000, SL at 1.0990 (10 pips).
    # Account balance 10,000 -> 2% risk is $200.
    # Pip value = $10. 10 pips = $100 per lot. Lots = 2.0 lots.
    # Notional value = 2.0 * 100,000 * 1.1000 = $220,000 > $10,000 ceiling!
    signal = Signal(
        symbol="EURUSD",
        signal_type=SignalType.BUY,
        price=Decimal("1.1000"),
        stop_loss=Decimal("1.0990"),
        take_profit=Decimal("1.1030"),
        confidence=Decimal("0.90"),
        strategy_name="botragram_origin",
        generated_at=_NOW,
    )

    decision = trading_engine.evaluate(
        signal=signal,
        account_balance=Decimal("10000"),
        current_drawdown_pct=Decimal("0.01"),
        has_open_position=False,
    )
    assert not decision.should_execute
    assert decision.risk_result is None
    assert "exceeds maximum position size limit" in decision.reason


def test_trading_engine_cfd_enforces_risk_budget_post_normalization() -> None:
    """CFD trade must be rejected if actual risk exceeds risk budget."""
    cfd_sizing = CfdSizingEngine(is_live=False)
    trading_engine = TradingEngine(
        risk_engine=RiskEngine(
            settings=RiskSettings(
                risk_per_trade_pct=Decimal("0.01"),  # 1% of 100 = $1.00 risk budget
                max_position_size_usdt=Decimal("500000"),
            ),
        ),
        cfd_sizing_engine=cfd_sizing,
        market_type=MarketType.CFD,
    )

    # Balance 100. Risk budget = $1.00.
    # Gold SL distance: $10 = 100 pips. Min lot is 0.01 ->
    # actual risk = 0.01 * 100 * $10 = $10.
    # Normalized lots would be 0 because 0.001 raw lot < 0.01 min lot.
    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        price=Decimal("2650"),
        stop_loss=Decimal("2640"),
        take_profit=Decimal("2670"),
        confidence=Decimal("0.90"),
        strategy_name="botragram_origin",
        generated_at=_NOW,
    )

    decision = trading_engine.evaluate(
        signal=signal,
        account_balance=Decimal("100"),
        current_drawdown_pct=Decimal("0.0"),
        has_open_position=False,
    )
    assert not decision.should_execute
    assert "Calculated CFD lot size is zero" in decision.reason
