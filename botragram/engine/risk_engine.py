"""
Botragram

Description:
    Risk engine for enforcing order sizing and risk boundaries.

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
import logging
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.config.risk_settings import RiskSettings
from botragram.enums.order_side import OrderSide
from botragram.utils.validator import validate_positive_decimal

logger = logging.getLogger(__name__)


# =============================================================================
# Risk Engine Class
# =============================================================================
class RiskEngine:
    """Engine responsible for risk validation and order size calculation."""

    def __init__(self, settings: RiskSettings | None = None) -> None:
        """Initialize RiskEngine.

        Args:
            settings: Optional RiskSettings instance.
        """
        self._settings = settings or RiskSettings()

    def calculate_position_size(
        self,
        account_balance: Decimal,
        entry_price: Decimal,
    ) -> Decimal:
        """Calculate maximum order quantity based on risk settings.

        Args:
            account_balance: Total available balance as Decimal.
            entry_price: Planned entry price as Decimal.

        Returns:
            Calculated quantity as Decimal.
        """
        validate_positive_decimal(entry_price, name="entry_price")
        if account_balance <= Decimal("0"):
            return Decimal("0")

        risk_amount = account_balance * self._settings.risk_per_trade_pct
        max_allowed_notional = min(
            account_balance * Decimal(str(self._settings.leverage)),
            self._settings.max_position_size_usdt,
        )

        position_notional = min(risk_amount, max_allowed_notional)
        quantity = position_notional / entry_price
        return quantity

    def calculate_sl_tp_prices(
        self,
        entry_price: Decimal,
        side: OrderSide,
    ) -> tuple[Decimal, Decimal]:
        """Calculate Stop Loss and Take Profit prices based on risk percentage.

        Args:
            entry_price: Entry price.
            side: Order side enum (BUY/SELL).

        Returns:
            Tuple of (stop_loss_price, take_profit_price).
        """
        validate_positive_decimal(entry_price, name="entry_price")

        sl_pct = self._settings.stop_loss_pct
        tp_pct = self._settings.take_profit_pct

        if side == OrderSide.BUY:
            sl_price = entry_price * (Decimal("1") - sl_pct)
            tp_price = entry_price * (Decimal("1") + tp_pct)
        else:
            sl_price = entry_price * (Decimal("1") + sl_pct)
            tp_price = entry_price * (Decimal("1") - tp_pct)

        return sl_price, tp_price

    def validate_order(
        self,
        quantity: Decimal,
        entry_price: Decimal,
    ) -> bool:
        """Validate whether an order meets risk parameters.

        Args:
            quantity: Planned quantity.
            entry_price: Planned price.

        Returns:
            True if order is within risk limits, False otherwise.
        """
        if quantity <= Decimal("0") or entry_price <= Decimal("0"):
            logger.warning("Order rejected: Non-positive quantity or price")
            return False

        notional = quantity * entry_price
        if notional > self._settings.max_position_size_usdt:
            logger.warning(
                f"Order rejected: Notional {notional} exceeds max allowed "
                f"{self._settings.max_position_size_usdt}"
            )
            return False

        return True
