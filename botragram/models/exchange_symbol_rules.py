"""Botragram exchange symbol rules used by Futures execution boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from botragram.enums import OrderType, PositionSide
from botragram.exceptions import VenueRuleValidationError

__all__ = ["ExchangeSymbolRules"]


_DECIMAL_ZERO = Decimal("0")


@dataclass(slots=True, kw_only=True, frozen=True)
class ExchangeSymbolRules:
    """Represent vendor-neutral MARKET quantity and trigger-price constraints."""

    symbol: str
    market_min_quantity: Decimal
    market_max_quantity: Decimal
    market_quantity_step: Decimal
    minimum_notional: Decimal | None = None
    minimum_price: Decimal = _DECIMAL_ZERO
    maximum_price: Decimal = _DECIMAL_ZERO
    price_tick_size: Decimal = _DECIMAL_ZERO

    def __post_init__(self) -> None:
        """Validate immutable exchange quantity and price constraints."""
        if not self.symbol.strip():
            raise ValueError("Exchange symbol rules require a symbol")
        if self.market_min_quantity <= _DECIMAL_ZERO:
            raise ValueError("Market minimum quantity must be greater than zero")
        if self.market_max_quantity < self.market_min_quantity:
            raise ValueError("Market maximum quantity must meet the minimum")
        if self.market_quantity_step <= _DECIMAL_ZERO:
            raise ValueError("Market quantity step must be greater than zero")
        if self.minimum_notional is not None and self.minimum_notional <= _DECIMAL_ZERO:
            raise ValueError("Minimum notional must be greater than zero")
        if self.minimum_price < _DECIMAL_ZERO:
            raise ValueError("Minimum price must not be negative")
        if self.maximum_price < _DECIMAL_ZERO:
            raise ValueError("Maximum price must not be negative")
        if (
            self.maximum_price > _DECIMAL_ZERO
            and self.maximum_price < self.minimum_price
        ):
            raise ValueError("Maximum price must meet the minimum price")
        if self.price_tick_size <= _DECIMAL_ZERO:
            raise ValueError("Price tick size must be greater than zero")

    def normalize_protection_trigger(
        self,
        *,
        raw_trigger_price: Decimal,
        position_side: PositionSide,
        order_type: OrderType,
        mark_price: Decimal,
    ) -> Decimal:
        """Return one venue-valid, conservative protection trigger price.

        Args:
            raw_trigger_price: Risk-engine protection price before venue rounding.
            position_side: Side of the protected position.
            order_type: STOP or take-profit protection order type.
            mark_price: Fresh exchange MARK_PRICE for trigger validation.

        Returns:
            The directionally normalized price on the venue's anchored grid.

        Raises:
            VenueRuleValidationError: If the price cannot safely be submitted.
        """
        self._validate_raw_trigger(raw_trigger_price=raw_trigger_price)
        self._validate_mark_price(mark_price=mark_price)
        rounding = self._rounding_for(
            position_side=position_side,
            order_type=order_type,
        )
        normalized = self._round_to_price_grid(
            price=raw_trigger_price,
            rounding=rounding,
        )
        self._validate_normalized_trigger(
            trigger_price=normalized,
            position_side=position_side,
            order_type=order_type,
            mark_price=mark_price,
        )
        return normalized

    def _validate_raw_trigger(self, *, raw_trigger_price: Decimal) -> None:
        """Reject a raw trigger outside the exchange's supported price range."""
        if raw_trigger_price <= _DECIMAL_ZERO:
            raise VenueRuleValidationError("Protection trigger price must be positive")
        if raw_trigger_price < self.minimum_price:
            raise VenueRuleValidationError("Protection trigger price is below minimum")
        if (
            self.maximum_price > _DECIMAL_ZERO
            and raw_trigger_price > self.maximum_price
        ):
            raise VenueRuleValidationError("Protection trigger price exceeds maximum")

    @staticmethod
    def _validate_mark_price(*, mark_price: Decimal) -> None:
        """Reject an unusable MARK_PRICE reference."""
        if mark_price <= _DECIMAL_ZERO:
            raise VenueRuleValidationError("MARK_PRICE must be greater than zero")

    def _round_to_price_grid(self, *, price: Decimal, rounding: str) -> Decimal:
        """Round one price against the exchange grid anchored at minimum price."""
        grid_steps = (price - self.minimum_price) / self.price_tick_size
        aligned_steps = grid_steps.to_integral_value(rounding=rounding)
        return self.minimum_price + aligned_steps * self.price_tick_size

    def _validate_normalized_trigger(
        self,
        *,
        trigger_price: Decimal,
        position_side: PositionSide,
        order_type: OrderType,
        mark_price: Decimal,
    ) -> None:
        """Validate a normalized trigger before the protection mutation boundary."""
        if trigger_price <= _DECIMAL_ZERO:
            raise VenueRuleValidationError("Protection trigger price must be positive")
        if trigger_price < self.minimum_price:
            raise VenueRuleValidationError("Protection trigger price is below minimum")
        if self.maximum_price > _DECIMAL_ZERO and trigger_price > self.maximum_price:
            raise VenueRuleValidationError("Protection trigger price exceeds maximum")
        if (trigger_price - self.minimum_price) % self.price_tick_size != _DECIMAL_ZERO:
            raise VenueRuleValidationError(
                "Protection trigger price is not tick-aligned"
            )
        self._validate_trigger_direction(
            trigger_price=trigger_price,
            position_side=position_side,
            order_type=order_type,
            mark_price=mark_price,
        )

    @staticmethod
    def _rounding_for(*, position_side: PositionSide, order_type: OrderType) -> str:
        """Return the conservative venue-rounding mode for one protection leg."""
        if order_type not in {OrderType.STOP_MARKET, OrderType.TAKE_PROFIT_MARKET}:
            raise VenueRuleValidationError("Unsupported protection order type")
        if position_side is PositionSide.LONG:
            return ROUND_CEILING if order_type is OrderType.STOP_MARKET else ROUND_FLOOR
        return ROUND_FLOOR if order_type is OrderType.STOP_MARKET else ROUND_CEILING

    @staticmethod
    def _validate_trigger_direction(
        *,
        trigger_price: Decimal,
        position_side: PositionSide,
        order_type: OrderType,
        mark_price: Decimal,
    ) -> None:
        """Ensure a MARK_PRICE trigger cannot immediately execute the exit leg."""
        is_below_mark = trigger_price < mark_price
        is_above_mark = trigger_price > mark_price
        if position_side is PositionSide.LONG:
            valid = (
                is_below_mark if order_type is OrderType.STOP_MARKET else is_above_mark
            )
        else:
            valid = (
                is_above_mark if order_type is OrderType.STOP_MARKET else is_below_mark
            )
        if not valid:
            raise VenueRuleValidationError(
                "Protection trigger is invalid relative to current MARK_PRICE"
            )
