"""mimo-crypto-research — event-driven multi-agent crypto scanner.

Architecture:
    EventBus  <-  Agents (Discoverer, ContractChecker, RiskAnalyst, Reporter, AlertWatcher)
                       |
                    Scanner (wires everything)
                       |
                    CLI / Dashboard

Agents never call each other directly. They emit and subscribe to events.
"""

from .config import Settings, load_settings
from .scanner import Scanner
from .core.models import (
    TokenFacts, ContractFacts, RiskVerdict, RiskBand,
    ScanResult, ScanRequest, PriceAlert,
)

__all__ = [
    "Settings", "load_settings", "Scanner",
    "TokenFacts", "ContractFacts", "RiskVerdict", "RiskBand",
    "ScanResult", "ScanRequest", "PriceAlert",
]

__version__ = "3.0.0"
