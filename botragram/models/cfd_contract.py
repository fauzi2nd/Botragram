"""
Botragram

Description:
    TradFi CFD contract specifications and pip sizing models.

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
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.enums import AssetClass

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "CfdContractSpec",
    "PipCalculationResult",
]

_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# CFD Contract Specification Model
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class CfdContractSpec:
    """Specification of contract size, pip size, and lot rules for a CFD symbol."""

    symbol: str
    asset_class: AssetClass
    contract_size: Decimal
    pip_size: Decimal
    tick_size: Decimal
    min_lot: Decimal = Decimal("0.01")
    max_lot: Decimal = Decimal("100.0")
    lot_step: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        """Validate CFD contract invariants."""
        if not self.symbol.strip():
            raise ValueError("CfdContractSpec requires a valid symbol")
        if self.contract_size <= _DECIMAL_ZERO:
            raise ValueError("contract_size must be positive")
        if self.pip_size <= _DECIMAL_ZERO:
            raise ValueError("pip_size must be positive")
        if self.tick_size <= _DECIMAL_ZERO:
            raise ValueError("tick_size must be positive")
        if self.min_lot <= _DECIMAL_ZERO:
            raise ValueError("min_lot must be positive")
        if self.max_lot < self.min_lot:
            raise ValueError("max_lot must be greater than or equal to min_lot")
        if self.lot_step <= _DECIMAL_ZERO:
            raise ValueError("lot_step must be positive")


# =============================================================================
# Pip Calculation Result Model
# =============================================================================
@dataclass(slots=True, kw_only=True, frozen=True)
class PipCalculationResult:
    """Result of pip distance, pip value, and dynamic lot sizing calculation."""

    symbol: str
    entry_price: Decimal
    stop_loss: Decimal
    distance_in_pips: Decimal
    pip_value_per_lot: Decimal
    risk_amount: Decimal
    calculated_lots: Decimal
    normalized_lots: Decimal
    notional_value: Decimal

    def __post_init__(self) -> None:
        """Validate result parameters."""
        if not self.symbol.strip():
            raise ValueError("PipCalculationResult requires a valid symbol")
        if self.entry_price <= _DECIMAL_ZERO:
            raise ValueError("entry_price must be positive")
        if self.stop_loss <= _DECIMAL_ZERO:
            raise ValueError("stop_loss must be positive")
        if self.distance_in_pips < _DECIMAL_ZERO:
            raise ValueError("distance_in_pips cannot be negative")
        if self.pip_value_per_lot <= _DECIMAL_ZERO:
            raise ValueError("pip_value_per_lot must be positive")
        if self.risk_amount < _DECIMAL_ZERO:
            raise ValueError("risk_amount cannot be negative")
        if self.calculated_lots < _DECIMAL_ZERO:
            raise ValueError("calculated_lots cannot be negative")
        if self.normalized_lots < _DECIMAL_ZERO:
            raise ValueError("normalized_lots cannot be negative")
        if self.notional_value < _DECIMAL_ZERO:
            raise ValueError("notional_value cannot be negative")
