"""Tests for the EventBus pub/sub system."""

import asyncio

import pytest

from mimo_research.core.events import Event, EventBus


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


# ── Basic emit delivers to subscribers ───────────────────────────────

async def test_emit_delivers_to_subscribers(bus: EventBus):
    """Events are delivered to all handlers subscribed to the exact topic."""
    received: list[Event] = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("token.discovered", handler)
    await bus.emit("token.discovered", {"symbol": "TEST", "chain": "ethereum"})

    assert len(received) == 1
    assert received[0].topic == "token.discovered"
    assert received[0].data["symbol"] == "TEST"


async def test_emit_multiple_handlers(bus: EventBus):
    """Multiple handlers on the same topic all receive the event."""
    count = {"a": 0, "b": 0}

    async def handler_a(event: Event):
        count["a"] += 1

    async def handler_b(event: Event):
        count["b"] += 1

    bus.subscribe("scan.complete", handler_a)
    bus.subscribe("scan.complete", handler_b)
    await bus.emit("scan.complete", {"id": 1})

    assert count["a"] == 1
    assert count["b"] == 1


async def test_emit_no_cross_topic(bus: EventBus):
    """A handler subscribed to topic A does not receive events on topic B."""
    received: list[str] = []

    async def handler(event: Event):
        received.append(event.topic)

    bus.subscribe("token.discovered", handler)
    await bus.emit("risk.assessed", {"score": 50})

    assert len(received) == 0


# ── Wildcard subscriptions ───────────────────────────────────────────

async def test_wildcard_subscription(bus: EventBus):
    """A wildcard pattern 'token.*' matches all topics starting with 'token.'."""
    received: list[str] = []

    async def handler(event: Event):
        received.append(event.topic)

    bus.subscribe("token.*", handler)

    await bus.emit("token.discovered", {"a": 1})
    await bus.emit("token.rugged", {"a": 2})
    await bus.emit("risk.assessed", {"a": 3})

    assert len(received) == 2
    assert "token.discovered" in received
    assert "token.rugged" in received


async def test_wildcard_exact_no_match(bus: EventBus):
    """'token.*' does NOT match 'token' without a dot suffix."""
    received: list[str] = []

    async def handler(event: Event):
        received.append(event.topic)

    bus.subscribe("token.*", handler)
    await bus.emit("token", {"x": 1})

    assert len(received) == 0


async def test_wildcard_matches_longer_topics(bus: EventBus):
    """'token.*' matches deeper nested topics like 'token.foo.bar'."""
    received: list[str] = []

    async def handler(event: Event):
        received.append(event.topic)

    bus.subscribe("token.*", handler)
    await bus.emit("token.foo.bar", {"x": 1})

    assert len(received) == 1
    assert received[0] == "token.foo.bar"


# ── stop_propagation ─────────────────────────────────────────────────

async def test_stop_propagation(bus: EventBus):
    """Calling event.stop_propagation() prevents later handlers from running."""
    order: list[str] = []

    async def first(event: Event):
        order.append("first")
        event.stop_propagation()

    async def second(event: Event):
        order.append("second")

    bus.subscribe("test.topic", first)
    bus.subscribe("test.topic", second)
    await bus.emit("test.topic", {})

    assert order == ["first"]


async def test_stop_propagation_wildcard(bus: EventBus):
    """stop_propagation also blocks wildcard handlers."""
    order: list[str] = []

    async def exact_handler(event: Event):
        order.append("exact")
        event.stop_propagation()

    async def wildcard_handler(event: Event):
        order.append("wildcard")

    bus.subscribe("token.discovered", exact_handler)
    bus.subscribe("token.*", wildcard_handler)
    await bus.emit("token.discovered", {})

    assert order == ["exact"]


# ── recent() history filtering ───────────────────────────────────────

async def test_recent_returns_all(bus: EventBus):
    """recent() with no topic filter returns the most recent events."""
    await bus.emit("a", {"i": 1})
    await bus.emit("b", {"i": 2})
    await bus.emit("c", {"i": 3})

    recent = bus.recent()
    assert len(recent) == 3
    assert recent[0].topic == "a"
    assert recent[-1].topic == "c"


async def test_recent_filters_by_topic_prefix(bus: EventBus):
    """recent(topic='token') returns only events whose topic starts with 'token'."""
    await bus.emit("token.discovered", {"x": 1})
    await bus.emit("risk.assessed", {"x": 2})
    await bus.emit("token.rugged", {"x": 3})
    await bus.emit("scan.complete", {"x": 4})

    recent = bus.recent(topic="token")
    assert len(recent) == 2
    assert all(e.topic.startswith("token") for e in recent)


async def test_recent_respects_limit(bus: EventBus):
    """recent(limit=N) returns at most N events."""
    for i in range(10):
        await bus.emit("test", {"i": i})

    recent = bus.recent(limit=3)
    assert len(recent) == 3
    # Should be the last 3
    assert recent[0].data["i"] == 7
    assert recent[-1].data["i"] == 9


async def test_recent_empty(bus: EventBus):
    """recent() on a fresh bus returns an empty list."""
    assert bus.recent() == []


# ── Metadata ─────────────────────────────────────────────────────────

async def test_event_source_metadata(bus: EventBus):
    """The source field is preserved on emitted events."""
    received: list[Event] = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("test", handler)
    await bus.emit("test", {}, source="discoverer")

    assert received[0].source == "discoverer"


async def test_event_has_timestamp(bus: EventBus):
    """Events have a UTC timestamp."""
    received: list[Event] = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("test", handler)
    await bus.emit("test", {})

    assert received[0].timestamp is not None
    assert received[0].timestamp.tzinfo is not None


async def test_history_capped(bus: EventBus):
    """History is capped at _max_history to avoid unbounded growth."""
    bus._max_history = 5
    for i in range(10):
        await bus.emit("test", {"i": i})

    assert len(bus._history) == 5
    assert bus._history[0].data["i"] == 5


async def test_clear_resets_everything(bus: EventBus):
    """clear() removes all handlers and history."""
    received: list[Event] = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("test", handler)
    await bus.emit("test", {})
    assert len(received) == 1

    bus.clear()
    await bus.emit("test", {})
    assert len(received) == 1  # Handler was cleared, no new delivery
    # History was cleared by clear(), but emit records new events
    assert len(bus._history) == 1  # Only the new emit, not the old one


async def test_unsubscribe(bus: EventBus):
    """unsubscribe() removes a specific handler."""
    received: list[Event] = []

    async def handler(event: Event):
        received.append(event)

    bus.subscribe("test", handler)
    await bus.emit("test", {})
    assert len(received) == 1

    bus.unsubscribe("test", handler)
    await bus.emit("test", {})
    assert len(received) == 1  # No new delivery
