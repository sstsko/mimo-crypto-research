"""Contract checker agent — inspects onchain contract data.

Subscribes to: token.discovered
Emits:         contract.checked

Deterministic — no LLM. Uses DataFetcher for Etherscan + honeypot heuristics.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..core.events import Event, EventBus
from ..core.models import TokenFacts, ContractFacts
from ..services.fetcher import DataFetcher
from .base import Agent

log = logging.getLogger("chainscout.contract")


class ContractChecker(Agent):
    name = "contract_checker"

    def __init__(self, fetcher: DataFetcher) -> None:
        self.fetcher = fetcher
        self._bus: Optional[EventBus] = None

    def setup(self, bus: EventBus) -> None:
        self._bus = bus
        bus.subscribe("token.discovered", self._on_token)

    async def _on_token(self, event: Event) -> None:
        token: TokenFacts = event.data
        log.info("checking contract: %s/%s", token.chain, token.symbol)

        facts = await self.fetcher.inspect_contract(token.chain, token.address)
        if facts is None:
            facts = ContractFacts(address=token.address, chain=token.chain)

        # Honeypot heuristics from market data
        if token.liquidity_usd is not None and token.liquidity_usd < 10_000:
            facts.notes.append("low_liq_under_10k")
        if token.buys_24h and token.buys_24h > 10 and (token.sells_24h or 0) == 0:
            facts.notes.append("no_sells_with_buys")

        if self._bus:
            await self._bus.emit("contract.checked", (token, facts), source=self.name)
