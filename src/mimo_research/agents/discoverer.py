"""Discoverer agent — finds token candidates from seeds and trending.

Subscribes to: scan.requested, trending.scan
Emits:         token.discovered

Deterministic — no LLM calls. Uses the DataFetcher to query DexScreener.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..core.events import Event, EventBus
from ..core.models import TokenFacts, ScanRequest
from ..services.fetcher import DataFetcher
from .base import Agent

log = logging.getLogger("chainscout.discoverer")

_EVM_LEN = 42


class Discoverer(Agent):
    name = "discoverer"

    def __init__(self, fetcher: DataFetcher, *, top_k: int = 3) -> None:
        self.fetcher = fetcher
        self.top_k = top_k
        self._bus: Optional[EventBus] = None

    def setup(self, bus: EventBus) -> None:
        self._bus = bus
        bus.subscribe("scan.requested", self._on_scan)
        bus.subscribe("trending.scan", self._on_trending)

    async def _on_scan(self, event: Event) -> None:
        req: ScanRequest = event.data
        seed = req.seed.strip()
        if not seed:
            return

        log.info("discovering: %s", seed)

        if seed.lower().startswith("0x") and len(seed) == _EVM_LEN:
            candidates = await self.fetcher.token_by_address(seed)
        elif seed.lower() == "trending":
            candidates = await self.fetcher.trending_tokens()
        else:
            candidates = await self.fetcher.search_tokens(seed)

        ranked = sorted(candidates, key=_rank, reverse=True)
        for tok in ranked[: self.top_k]:
            await self._bus.emit("token.discovered", tok, source=self.name)

    async def _on_trending(self, event: Event) -> None:
        log.info("fetching trending tokens")
        candidates = await self.fetcher.trending_tokens()
        ranked = sorted(candidates, key=_rank, reverse=True)
        for tok in ranked[: self.top_k]:
            await self._bus.emit("token.discovered", tok, source=self.name)


def _rank(t: TokenFacts) -> float:
    return (t.liquidity_usd or 0) + 0.1 * (t.volume_24h or 0)
