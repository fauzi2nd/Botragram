"""
Botragram

Description:
    Exchange account access service.

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
from dataclasses import dataclass
from decimal import Decimal

# =============================================================================
# Local Imports
# =============================================================================
from botragram.exchanges.base import BaseExchangeClient
from botragram.models import Account, Balance

__all__ = [
    "AccountService",
]


# =============================================================================
# Constants
# =============================================================================
_DECIMAL_ZERO = Decimal("0")


# =============================================================================
# Service Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class AccountService:
    """Provide normalized access to exchange account information."""

    exchange_client: BaseExchangeClient

    async def get_account(self) -> Account:
        """Return current exchange account information."""
        return await self.exchange_client.get_account()

    async def get_balances(self) -> tuple[Balance, ...]:
        """Return all account balances."""
        account = await self.get_account()

        return tuple(account.balances)

    async def get_balance(
        self,
        *,
        asset: str,
    ) -> Balance | None:
        """Return balance information for an asset.

        Args:
            asset: Asset symbol, such as BTC or USDT.

        Returns:
            Matching balance, or None when the asset does not exist.

        Raises:
            RuntimeError: If duplicate asset balances are returned.
        """
        normalized_asset = self._normalize_asset(asset)
        balances = await self.get_balances()

        matching_balance: Balance | None = None

        for balance in balances:
            if balance.asset.upper() != normalized_asset:
                continue

            if matching_balance is not None:
                raise RuntimeError(
                    "Exchange returned multiple balances for asset "
                    f"{normalized_asset!r}"
                )

            matching_balance = balance

        return matching_balance

    async def get_free_balance(
        self,
        *,
        asset: str,
    ) -> Decimal:
        """Return free balance for an asset.

        Args:
            asset: Asset symbol.

        Returns:
            Free balance, or zero when the asset does not exist.
        """
        balance = await self.get_balance(
            asset=asset,
        )

        if balance is None:
            return _DECIMAL_ZERO

        return balance.free

    async def get_locked_balance(
        self,
        *,
        asset: str,
    ) -> Decimal:
        """Return locked balance for an asset.

        Args:
            asset: Asset symbol.

        Returns:
            Locked balance, or zero when the asset does not exist.
        """
        balance = await self.get_balance(
            asset=asset,
        )

        if balance is None:
            return _DECIMAL_ZERO

        return balance.locked

    async def get_total_balance(
        self,
        *,
        asset: str,
    ) -> Decimal:
        """Return free plus locked balance for an asset.

        Args:
            asset: Asset symbol.

        Returns:
            Total asset balance.
        """
        balance = await self.get_balance(
            asset=asset,
        )

        if balance is None:
            return _DECIMAL_ZERO

        return balance.free + balance.locked

    async def can_trade(self) -> bool:
        """Return whether account trading is enabled."""
        account = await self.get_account()
        return account.can_trade

    async def can_deposit(self) -> bool:
        """Return whether account deposits are enabled."""
        account = await self.get_account()
        return account.can_deposit

    async def can_withdraw(self) -> bool:
        """Return whether account withdrawals are enabled."""
        account = await self.get_account()
        return account.can_withdraw

    @staticmethod
    def _normalize_asset(
        asset: str,
    ) -> str:
        """Normalize and validate an asset symbol."""
        normalized_asset = asset.strip().upper()

        if not normalized_asset:
            raise ValueError("Asset symbol must not be empty")

        return normalized_asset
