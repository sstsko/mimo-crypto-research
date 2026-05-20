"""Scanner — the main orchestrator that wires agents to the event bus.

Unlike a linear pipeline, the Scanner is event-driven:
  1. User emits a scan request
  2. Discoverer finds tokens, emits token.discovered
  3. ContractChecker + AlertWatcher react to token.discovered
  4. RiskAnalyst reacts to contract.checked
  5. Reporter reacts to risk.assessed
  6. Scanner reacts to scan.complete — records to DB, prints output

Agents don't know about each other. They only know the event bus.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Callable, Optional

from .core.db import Database
from .core.events import EventBus, Event
from .core.llm import LLMClient
from .core.models import ScanRequest, ScanResult, PriceAlert
from .agents import Discoverer, ContractChecker, RiskAnalyst, Reporter, AlertWatcher
from .services.fetcher import DataFetcher
from .services.scoring import composite_score

log = logging.getLogger("chainscout.scanner")


class Scanner:
    """Event-driven scanner. Call `boot()` to wire agents, then `scan()` to run."""

    def __init__(
        self,
        db: Database,
        llm: LLMClient,
        fetcher: DataFetcher,
        *,
        alert_thresholds: tuple[float, ...] = (-5.0, -10.0, 5.0, 10.0),
        on_result: Optional[Callable] = None,
        on_alert: Optional[Callable] = None,
    ) -> None:
        self.db = db
        self.llm = llm
        self.fetcher = fetcher
        self.bus = EventBus()
        self._on_result = on_result
        self._on_alert = on_alert
        self._results: list[ScanResult] = []

        # Wire agents
        self.discoverer = Discoverer(fetcher)
        self.contract_checker = ContractChecker(fetcher)
        self.risk_analyst = RiskAnalyst(llm)
        self.reporter = Reporter(llm)
        self.alert_watcher = AlertWatcher(db, alert_thresholds)

    def boot(self) -> None:
        """Register all agents with the event bus."""
        for agent in [self.discoverer, self.contract_checker,
                      self.risk_analyst, self.reporter, self.alert_watcher]:
            agent.setup(self.bus)
            log.info("agent registered: %s", agent.name)

        # Internal handler for completed scans
        self.bus.subscribe("scan.complete", self._on_complete)

    async def _on_complete(self, event: Event) -> None:
        result: ScanResult = event.data

        # Composite score
        result.composite_score = composite_score(result.token, result.contract, result.risk)

        # Record to DB
        scan_id = self.db.record_scan(
            chain=result.token.chain,
            address=result.token.address,
            symbol=result.token.symbol,
            liquidity_usd=result.token.liquidity_usd,
            volume_24h=result.token.volume_24h,
            price_usd=result.token.price_usd,
            risk_score=result.risk.score if result.risk else None,
            risk_band=result.risk.band.value if result.risk else None,
            composite_score=result.composite_score,
            llm_tokens=result.llm_tokens_used,
            duration_ms=result.scan_duration_ms,
        )

        # Record price snapshot for alert tracking
        if result.token.price_usd:
            self.db.snapshot_price(
                result.token.chain, result.token.address, result.token.price_usd,
                result.token.liquidity_usd or 0, result.token.volume_24h or 0,
            )

        self._results.append(result)
        log.info(
            "scan complete: %s/%s risk=%s composite=%.1f",
            result.token.chain, result.token.symbol,
            result.risk.band.value if result.risk else "?",
            result.composite_score,
        )

        if self._on_result:
            try:
                await self._maybe_await(self._on_result(result))
            except Exception:
                log.exception("on_result callback failed")

    async def scan(self, seed: str, *, source: str = "manual") -> list[ScanResult]:
        """Run a full scan for a seed (address, symbol, query, or 'trending')."""
        self._results = []
        t0 = time.monotonic()

        req = ScanRequest(seed=seed, source=source)
        await self.bus.emit("scan.requested", req, source="scanner")

        duration = int((time.monotonic() - t0) * 1000)
        for r in self._results:
            r.scan_duration_ms = duration

        return self._results

    async def scan_trending(self, *, top_k: int = 5) -> list[ScanResult]:
        """Pull trending tokens and scan them."""
        self._results = []
        self.discoverer.top_k = top_k
        await self.bus.emit("trending.scan", None, source="scanner")
        return self._results

    async def scan_watchlist(self) -> list[ScanResult]:
        """Scan all active watchlist entries."""
        items = self.db.get_watchlist(active_only=True)
        all_results = []
        for item in items:
            results = await self.scan(f"0x{item['address']}" if not item['address'].startswith('0x') else item['address'], source="watchlist")
            all_results.extend(results)
        return all_results

    async def close(self) -> None:
        await self.fetcher.close()
        await self.llm.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    @staticmethod
    async def _maybe_await(val):
        if asyncio.iscoroutine(val):
            return await val
        return val
