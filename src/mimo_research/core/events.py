"""Event bus — async pub/sub for decoupled agent communication.

Agents never call each other directly. They emit events and subscribe
to the events they care about. The Scanner orchestrates by wiring
subscriptions at startup.

Usage:
    bus = EventBus()
    bus.subscribe("token.discovered", my_handler)
    await bus.emit("token.discovered", token_data)
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional

log = logging.getLogger("chainscout.events")

# Handler signature: async def handler(event: Event) -> None
Handler = Callable[["Event"], Coroutine[Any, Any, None]]


@dataclass(slots=True)
class Event:
    """A single event on the bus."""

    topic: str
    data: Any
    source: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _propagation_stopped: bool = field(default=False, repr=False)

    def stop_propagation(self) -> None:
        """Prevent handlers after this one from running."""
        self._propagation_stopped = True


class EventBus:
    """Async in-process pub/sub with wildcard support."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._history: list[Event] = []
        self._max_history = 500

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Register a handler for a topic. Supports '*' wildcard suffix."""
        self._handlers[topic].append(handler)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        """Remove a handler."""
        if topic in self._handlers:
            self._handlers[topic] = [h for h in self._handlers[topic] if h is not handler]

    async def emit(self, topic: str, data: Any, *, source: str = "") -> Event:
        """Emit an event. Returns the Event object."""
        event = Event(topic=topic, data=data, source=source)
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Exact match handlers
        for handler in self._handlers.get(topic, []):
            if event._propagation_stopped:
                break
            try:
                await handler(event)
            except Exception:
                log.exception("handler error on topic=%s source=%s", topic, source)

        # Wildcard handlers (e.g. "token.*" matches "token.discovered")
        for pattern, handlers in self._handlers.items():
            if pattern.endswith("*") and topic.startswith(pattern[:-1]):
                for handler in handlers:
                    if event._propagation_stopped:
                        break
                    try:
                        await handler(event)
                    except Exception:
                        log.exception("wildcard handler error on topic=%s", topic)

        return event

    def recent(self, topic: Optional[str] = None, limit: int = 20) -> list[Event]:
        """Return recent events, optionally filtered by topic prefix."""
        events = self._history
        if topic:
            events = [e for e in events if e.topic.startswith(topic)]
        return events[-limit:]

    def clear(self) -> None:
        self._handlers.clear()
        self._history.clear()
