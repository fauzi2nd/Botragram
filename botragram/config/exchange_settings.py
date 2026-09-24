"""
Botragram

Description:
    Exchange connection settings model.

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

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants import DEFAULT_MAX_RETRIES, DEFAULT_REQUEST_TIMEOUT_SECONDS
from botragram.enums import ExchangeEnvironment, ExchangeType, MarginMode, MarketType

__all__ = [
    "ExchangeSettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class ExchangeSettings:
    """Settings for crypto exchange API connection."""

    exchange: ExchangeType = ExchangeType.BINANCE
    market_type: MarketType = MarketType.SPOT
    api_key: str = ""
    api_secret: str = ""
    passphrase: str = ""
    testnet: bool = True
    demo: bool = False
    timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES
    margin_mode: MarginMode = MarginMode.ISOLATED
    cfd_mode: str = "ecn"

    def __post_init__(self) -> None:
        """Validate and normalize exchange settings."""
        normalized_mode = self.cfd_mode.strip().lower()
        if normalized_mode in ("zero_fee", "zerofee", "zero"):
            normalized_mode = "zero_fee"
        elif normalized_mode == "pro":
            normalized_mode = "pro"
        elif normalized_mode == "ecn":
            normalized_mode = "ecn"
        else:
            raise ValueError(
                f"Invalid CFD mode: {self.cfd_mode!r}. Accepted values are: "
                "'ecn', 'zero_fee', 'pro'."
            )
        object.__setattr__(self, "cfd_mode", normalized_mode)

    @property
    def is_live(self) -> bool:
        """Whether the application connects to the live exchange."""
        return not self.testnet and not self.demo

    @property
    def environment(self) -> ExchangeEnvironment:
        """Return the canonical network environment for this exchange."""
        if self.demo:
            return ExchangeEnvironment.DEMO
        return (
            ExchangeEnvironment.TESTNET if self.testnet else ExchangeEnvironment.MAINNET
        )
