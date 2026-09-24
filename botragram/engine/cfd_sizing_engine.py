"""
Botragram

Description:
    TradFi CFD sizing engine calculating pip distances, pip values, and lots.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

import re

# =============================================================================
# Standard Library
# =============================================================================
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Final

# =============================================================================
# Local Imports
# =============================================================================
from botragram.engine.market_calendar import MarketCalendarEngine
from botragram.enums import AssetClass
from botragram.models import CfdContractSpec, PipCalculationResult

# =============================================================================
# Exports
# =============================================================================
__all__ = [
    "CfdSizingEngine",
]

# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO: Final[Decimal] = Decimal("0")
_DEFAULT_LOT_STEP: Final[Decimal] = Decimal("0.01")
_DEFAULT_MIN_LOT: Final[Decimal] = Decimal("0.01")
_DEFAULT_MAX_LOT: Final[Decimal] = Decimal("100.0")

_FOREX_CONTRACT_SIZE: Final[Decimal] = Decimal("100000")
_XAU_CONTRACT_SIZE: Final[Decimal] = Decimal("100")
_XAG_CONTRACT_SIZE: Final[Decimal] = Decimal("5000")
_OIL_CONTRACT_SIZE: Final[Decimal] = Decimal("1000")
_INDEX_CONTRACT_SIZE: Final[Decimal] = Decimal("1")
_CRYPTO_CONTRACT_SIZE: Final[Decimal] = Decimal("1")

_STANDARD_FX_PIP: Final[Decimal] = Decimal("0.0001")
_JPY_FX_PIP: Final[Decimal] = Decimal("0.01")
_XAU_PIP: Final[Decimal] = Decimal("0.10")
_XAG_PIP: Final[Decimal] = Decimal("0.01")
_OIL_PIP: Final[Decimal] = Decimal("0.01")
_INDEX_PIP: Final[Decimal] = Decimal("1.0")
_CRYPTO_PIP: Final[Decimal] = Decimal("1.0")


# =============================================================================
# CFD Sizing Engine
# =============================================================================
class CfdSizingEngine:
    """Deterministic calculation of pip metrics, contract specs, and lot sizing."""

    __slots__ = (
        "_calendar",
        "_is_live",
        "_spec_provider",
        "_specs",
    )

    def __init__(
        self,
        calendar: MarketCalendarEngine | None = None,
        *,
        is_live: bool = False,
        specs: Mapping[str, CfdContractSpec] | None = None,
        spec_provider: Callable[[str], CfdContractSpec | None] | None = None,
    ) -> None:
        """Initialize the CFD sizing engine with an optional calendar."""
        self._calendar = calendar if calendar is not None else MarketCalendarEngine()
        self._is_live = is_live
        self._specs: dict[str, CfdContractSpec] = dict(specs) if specs else {}
        self._spec_provider = spec_provider

    def register_contract_spec(self, spec: CfdContractSpec) -> None:
        """Register or update an authoritative contract specification."""
        clean = self._clean_symbol(spec.symbol)
        self._specs[clean] = spec
        self._specs[spec.symbol.upper()] = spec

    def set_contract_specs(self, specs: Mapping[str, CfdContractSpec]) -> None:
        """Set all authoritative contract specifications."""
        self._specs.clear()
        for spec in specs.values():
            self.register_contract_spec(spec)

    def _clean_symbol(self, symbol: str) -> str:
        """Strip CFD mode suffixes (.s, .pro, etc.) and delimiters."""
        s = re.sub(
            r"(\.(s|pro|cfd|std)|(_ecn|_std|-cfd))$",
            "",
            symbol.strip(),
            flags=re.IGNORECASE,
        ).upper()
        return s.replace("/", "").replace("-", "")

    def get_contract_spec(self, symbol: str) -> CfdContractSpec:
        """Resolve authoritative contract and pip specification for a CFD symbol."""
        clean = self._clean_symbol(symbol)
        upper = symbol.strip().upper()

        if clean in self._specs:
            spec = self._specs[clean]
            if self._is_live and not spec.enable:
                raise ValueError(f"CFD instrument {symbol} is disabled on exchange")
            return spec

        if upper in self._specs:
            spec = self._specs[upper]
            if self._is_live and not spec.enable:
                raise ValueError(f"CFD instrument {symbol} is disabled on exchange")
            return spec

        if self._spec_provider is not None:
            provided = self._spec_provider(clean) or self._spec_provider(upper)
            if provided is not None:
                self.register_contract_spec(provided)
                if self._is_live and not provided.enable:
                    raise ValueError(f"CFD instrument {symbol} is disabled on exchange")
                return provided

        if self._is_live:
            raise ValueError(
                f"Authoritative CFD instrument metadata unavailable"
                f" for {symbol} in LIVE mode"
            )

        return self.get_fallback_contract_spec(symbol)

    def get_fallback_contract_spec(self, symbol: str) -> CfdContractSpec:
        """Resolve deterministic fixture/fallback spec for a CFD symbol."""
        clean = self._clean_symbol(symbol)
        asset_class = self._calendar.classify_asset(symbol)

        if asset_class is AssetClass.CRYPTO:
            return CfdContractSpec(
                symbol=symbol,
                asset_class=asset_class,
                contract_size=_CRYPTO_CONTRACT_SIZE,
                pip_size=_CRYPTO_PIP,
                tick_size=Decimal("0.01"),
                min_lot=_DEFAULT_MIN_LOT,
                max_lot=_DEFAULT_MAX_LOT,
                lot_step=_DEFAULT_LOT_STEP,
                default_leverage=50,
                max_leverage=100,
            )

        if asset_class is AssetClass.COMMODITY:
            if clean.startswith("XAU"):
                return CfdContractSpec(
                    symbol=symbol,
                    asset_class=asset_class,
                    contract_size=_XAU_CONTRACT_SIZE,
                    pip_size=_XAU_PIP,
                    tick_size=Decimal("0.01"),
                    min_lot=_DEFAULT_MIN_LOT,
                    max_lot=_DEFAULT_MAX_LOT,
                    lot_step=_DEFAULT_LOT_STEP,
                    default_leverage=800,
                    max_leverage=800,
                )
            if clean.startswith("XAG"):
                return CfdContractSpec(
                    symbol=symbol,
                    asset_class=asset_class,
                    contract_size=_XAG_CONTRACT_SIZE,
                    pip_size=_XAG_PIP,
                    tick_size=Decimal("0.001"),
                    min_lot=_DEFAULT_MIN_LOT,
                    max_lot=_DEFAULT_MAX_LOT,
                    lot_step=_DEFAULT_LOT_STEP,
                    default_leverage=200,
                    max_leverage=200,
                )
            return CfdContractSpec(
                symbol=symbol,
                asset_class=asset_class,
                contract_size=_OIL_CONTRACT_SIZE,
                pip_size=_OIL_PIP,
                tick_size=Decimal("0.01"),
                min_lot=_DEFAULT_MIN_LOT,
                max_lot=_DEFAULT_MAX_LOT,
                lot_step=_DEFAULT_LOT_STEP,
                default_leverage=100,
                max_leverage=200,
            )

        if asset_class is AssetClass.INDEX:
            return CfdContractSpec(
                symbol=symbol,
                asset_class=asset_class,
                contract_size=_INDEX_CONTRACT_SIZE,
                pip_size=_INDEX_PIP,
                tick_size=Decimal("0.01"),
                min_lot=_DEFAULT_MIN_LOT,
                max_lot=_DEFAULT_MAX_LOT,
                lot_step=_DEFAULT_LOT_STEP,
                default_leverage=100,
                max_leverage=200,
            )

        # Forex
        is_jpy = clean.endswith("JPY")
        is_major_fx = clean in {
            "EURUSD",
            "GBPUSD",
            "USDJPY",
            "AUDUSD",
            "NZDUSD",
            "USDCAD",
            "USDCHF",
        }
        pip_size = _JPY_FX_PIP if is_jpy else _STANDARD_FX_PIP
        tick_size = Decimal("0.001") if is_jpy else Decimal("0.00001")
        default_fx_lev = 500 if is_major_fx else 200
        max_fx_lev = 1000 if is_major_fx else 500
        return CfdContractSpec(
            symbol=symbol,
            asset_class=AssetClass.FOREX,
            contract_size=_FOREX_CONTRACT_SIZE,
            pip_size=pip_size,
            tick_size=tick_size,
            min_lot=_DEFAULT_MIN_LOT,
            max_lot=_DEFAULT_MAX_LOT,
            lot_step=_DEFAULT_LOT_STEP,
            default_leverage=default_fx_lev,
            max_leverage=max_fx_lev,
        )

    def calculate_pip_distance(
        self,
        symbol: str,
        entry_price: Decimal,
        target_price: Decimal,
    ) -> Decimal:
        """Calculate the absolute distance in pips between two price levels."""
        spec = self.get_contract_spec(symbol)
        diff = abs(entry_price - target_price)
        return diff / spec.pip_size

    @staticmethod
    def _extract_base_and_quote(symbol: str) -> tuple[str, str]:
        """Extract normalized base and quote asset identifiers for CFD instrument."""
        clean = re.sub(
            r"(\.(s|pro|cfd|std)|(_ecn|_std|-cfd))$",
            "",
            symbol.strip(),
            flags=re.IGNORECASE,
        ).upper()
        if len(clean) == 6 and clean.isalpha():
            return clean[:3], clean[3:6]
        if clean.endswith(("USDT", "USDC")):
            return clean[:-4], "USD"
        if clean.endswith("USD"):
            return clean[:-3], "USD"
        if clean.endswith("JPY"):
            return clean[:-3], "JPY"
        if clean.endswith("EUR"):
            return clean[:-3], "EUR"
        if clean.endswith("GBP"):
            return clean[:-3], "GBP"
        return clean, "USD"

    def calculate_pip_value_per_lot(
        self,
        symbol: str,
        price: Decimal,
        quote_to_account_rate: Decimal | None = None,
    ) -> Decimal:
        """Calculate the monetary value of 1.0 pip per 1.0 standard lot.

        Args:
            symbol: Trading instrument.
            price: Current market price.
            quote_to_account_rate: Rate to convert quote currency to account currency.
                If None or omitted:
                - If quote is USD/USDT, defaults to 1.0.
                - If base is USD, calculates 1.0 / price.
                - For cross-currency pairs with non-USD quote (e.g. EURJPY):
                  In LIVE mode, fails closed (raises ValueError).
                  In PAPER/tests, falls back to 1.0.
        """
        spec = self.get_contract_spec(symbol)
        base_cur, quote_cur = self._extract_base_and_quote(symbol)

        if quote_to_account_rate is not None:
            if (
                not quote_to_account_rate.is_finite()
                or quote_to_account_rate <= _DECIMAL_ZERO
            ):
                raise ValueError(
                    f"quote_to_account_rate must be finite and positive: "
                    f"{quote_to_account_rate}"
                )
            if (
                self._is_live
                and quote_cur not in ("USD", "USDT")
                and base_cur != "USD"
                and quote_to_account_rate == Decimal("1.0")
            ):
                raise ValueError(
                    f"Conversion rate for non-USD quote currency {quote_cur} "
                    f"cannot default to 1.0 in LIVE mode for {symbol}"
                )
            effective_rate = quote_to_account_rate
        else:
            if quote_cur in ("USD", "USDT"):
                effective_rate = Decimal("1.0")
            elif base_cur == "USD":
                if price <= _DECIMAL_ZERO or not price.is_finite():
                    raise ValueError(
                        f"Valid market price is required for USD base conversion: "
                        f"{price}"
                    )
                effective_rate = Decimal("1.0") / price
            else:
                if self._is_live:
                    raise ValueError(
                        f"Currency conversion rate is required for non-USD quote "
                        f"currency {quote_cur} in LIVE mode for {symbol}"
                    )
                effective_rate = Decimal("1.0")

        pip_in_quote = spec.contract_size * spec.pip_size
        return pip_in_quote * effective_rate

    def calculate_lot_size(
        self,
        *,
        symbol: str,
        entry_price: Decimal,
        stop_loss: Decimal,
        risk_amount: Decimal,
        quote_to_account_rate: Decimal | None = None,
    ) -> PipCalculationResult:
        """Calculate position sizing in lots based on risk capital budget."""
        if entry_price <= _DECIMAL_ZERO:
            raise ValueError("entry_price must be positive")
        if stop_loss <= _DECIMAL_ZERO:
            raise ValueError("stop_loss must be positive")
        if risk_amount < _DECIMAL_ZERO:
            raise ValueError("risk_amount cannot be negative")

        spec = self.get_contract_spec(symbol)
        distance = abs(entry_price - stop_loss)
        if distance <= _DECIMAL_ZERO:
            raise ValueError("Stop-loss distance must be greater than zero")

        distance_in_pips = distance / spec.pip_size
        pip_val_per_lot = self.calculate_pip_value_per_lot(
            symbol=symbol,
            price=entry_price,
            quote_to_account_rate=quote_to_account_rate,
        )

        loss_per_lot = distance_in_pips * pip_val_per_lot
        raw_lots = (
            risk_amount / loss_per_lot
            if loss_per_lot > _DECIMAL_ZERO
            else _DECIMAL_ZERO
        )
        normalized_lots = self.normalize_lot(symbol, raw_lots)

        # Fail closed if normalized lot is below minimum executable lot
        if normalized_lots < spec.min_lot:
            normalized_lots = _DECIMAL_ZERO

        # Calculate accurate notional in account currency
        base_cur, quote_cur = self._extract_base_and_quote(symbol)
        if quote_to_account_rate is not None:
            rate_for_notional = quote_to_account_rate
        elif quote_cur in ("USD", "USDT"):
            rate_for_notional = Decimal("1.0")
        elif base_cur == "USD" and entry_price > _DECIMAL_ZERO:
            rate_for_notional = Decimal("1.0") / entry_price
        else:
            rate_for_notional = Decimal("1.0")

        notional_value = (
            normalized_lots * spec.contract_size * entry_price
        ) * rate_for_notional

        return PipCalculationResult(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            distance_in_pips=distance_in_pips,
            pip_value_per_lot=pip_val_per_lot,
            risk_amount=risk_amount,
            calculated_lots=raw_lots,
            normalized_lots=normalized_lots,
            notional_value=notional_value,
        )

    def normalize_lot(self, symbol: str, raw_lots: Decimal) -> Decimal:
        """Normalize raw lots to the symbol's step size, min_lot, and max_lot.

        Never rounds up past risk budget. If raw_lots is below min_lot,
        returns Decimal("0") to fail closed without silent exposure clamp-up.
        """
        if raw_lots <= _DECIMAL_ZERO:
            return _DECIMAL_ZERO

        spec = self.get_contract_spec(symbol)
        if raw_lots < spec.min_lot:
            return _DECIMAL_ZERO

        # Round down to discrete lot_step
        steps = raw_lots // spec.lot_step
        stepped = steps * spec.lot_step
        if stepped < spec.min_lot:
            return _DECIMAL_ZERO

        return min(spec.max_lot, stepped)
