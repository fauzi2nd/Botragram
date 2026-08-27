"""
Botragram

Description:
    Application configuration settings model.

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
from pathlib import Path

# =============================================================================
# Local Imports
# =============================================================================
from botragram.constants import APP_NAME, APP_VERSION
from botragram.enums import Environment, ExecutionPolicy, TradeMode

__all__ = [
    "AppSettings",
]


# =============================================================================
# Configuration Classes
# =============================================================================
@dataclass(
    slots=True,
    kw_only=True,
    frozen=True,
)
class AppSettings:
    """Application-wide environment and runtime settings."""

    app_name: str = APP_NAME
    app_version: str = APP_VERSION
    environment: Environment = Environment.DEVELOPMENT
    trade_mode: TradeMode = TradeMode.PAPER
    execution_policy: ExecutionPolicy | None = None
    autonomous_execution_enabled: bool = False
    autonomous_live_entry_enabled: bool = False
    autonomous_mainnet_entry_enabled: bool = False
    database_path: Path = Path("data") / "botragram.db"

    def __post_init__(self) -> None:
        """Reject ambiguous explicit and legacy execution-policy combinations."""
        if self.autonomous_execution_enabled and self.execution_policy in (
            ExecutionPolicy.SINGLE_SYMBOL,
            ExecutionPolicy.AUTONOMOUS_LIVE,
            ExecutionPolicy.HUMAN_CONFIRMED_PAPER,
        ):
            raise ValueError(
                "AUTONOMOUS_EXECUTION_ENABLED conflicts with the explicit "
                "execution policy"
            )

    @property
    def debug(self) -> bool:
        return self.environment in (
            Environment.DEVELOPMENT,
            Environment.TESTING,
        )

    @property
    def effective_execution_policy(self) -> ExecutionPolicy:
        """Return an explicit policy while preserving the legacy flag default."""
        policy = self.execution_policy

        if policy is not None:
            return policy

        return (
            ExecutionPolicy.AUTONOMOUS_PAPER
            if self.autonomous_execution_enabled
            else ExecutionPolicy.SINGLE_SYMBOL
        )
