"""
Botragram

Description:
    SQLite storage package initialization.

Python:
    3.14+
"""

# =============================================================================
# Future
# =============================================================================
from __future__ import annotations

# =============================================================================
# Local Imports
# =============================================================================
from botragram.storage.sqlite.autonomous_live_opportunity_claim_repository import (
    SQLiteAutonomousLiveOpportunityClaimRepository,
)
from botragram.storage.sqlite.candle_repository import (
    SQLiteCandleRepository,
)
from botragram.storage.sqlite.database import SQLiteDatabase
from botragram.storage.sqlite.migrations import SQLiteMigrationManager
from botragram.storage.sqlite.order_repository import (
    SQLiteOrderRepository,
)
from botragram.storage.sqlite.position_repository import (
    SQLitePositionRepository,
)
from botragram.storage.sqlite.signal_repository import (
    SQLiteSignalRepository,
)
from botragram.storage.sqlite.submission_attempt_repository import (
    SQLiteSubmissionAttemptRepository,
)
from botragram.storage.sqlite.trade_repository import (
    SQLiteTradeRepository,
)

__all__ = [
    "SQLiteAutonomousLiveOpportunityClaimRepository",
    "SQLiteCandleRepository",
    "SQLiteDatabase",
    "SQLiteMigrationManager",
    "SQLiteOrderRepository",
    "SQLitePositionRepository",
    "SQLiteSignalRepository",
    "SQLiteTradeRepository",
    "SQLiteSubmissionAttemptRepository",
]
