"""Base agent — abstract interface for all agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from ..core.events import EventBus


class Agent(ABC):
    """Every agent registers with the event bus via setup()."""

    name: str = "base"

    @abstractmethod
    def setup(self, bus: EventBus) -> None:
        """Wire event subscriptions. Called once at scanner boot."""
        ...
