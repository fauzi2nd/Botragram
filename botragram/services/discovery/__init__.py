"""
Botragram

Description:
    Discovery subpackage — signal opportunity discovery, stalking radar,
    and universe ranking services.

Python:
    3.14+
"""

from __future__ import annotations

from botragram.services.discovery.opportunity_discovery_service import (
    OpportunityDiscoveryService,
    SignalFilterResult,
)
from botragram.services.discovery.setup_stalking_service import (
    SetupStalkingService,
    StalkingSetupProvider,
)
from botragram.services.discovery.volume_ranked_discovery_universe_service import (
    VolumeRankedDiscoveryUniverseService,
)

__all__ = [
    "OpportunityDiscoveryService",
    "SetupStalkingService",
    "SignalFilterResult",
    "StalkingSetupProvider",
    "VolumeRankedDiscoveryUniverseService",
]
