"""Agents — event-driven workers that subscribe to the event bus.

Each agent is a class with a `setup(bus)` method that wires its
subscriptions. The Scanner calls setup() at boot.
"""

from .base import Agent
from .discoverer import Discoverer
from .contract_checker import ContractChecker
from .risk_analyst import RiskAnalyst
from .reporter import Reporter
from .alert_watcher import AlertWatcher

__all__ = ["Agent", "Discoverer", "ContractChecker", "RiskAnalyst", "Reporter", "AlertWatcher"]
