"""Alert watcher — monitors price movements for watchlist tokens.

Subscribes to: token.discovered, price.check
Emits:         alert.triggered

Compares current price against a stored baseline. Fires alerts when
the change exceeds configured thresholds.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..core.db import Database
from ..core.events import Event, EventBus
from ..core.models import TokenFacts, PriceAlert
from .base import Agent

log = logging.getLogger("chainscout.alerts")


class AlertWatcher(Agent):
    name = "alert_watcher"

    def __init__(self, db: Database, thresholds: tuple[float, ...] = (-5.0, -10.0, 5.0, 10.0)) -> None:
        self.db = db
        self.thresholds = thresholds
        self._bus: Optional[EventBus] = None

    def setup(self, bus: EventBus) -> None:
        self._bus = bus
        bus.subscribe("token.discovered", self._on_token)

    async def _on_token(self, event: Event) -> None:
        token: TokenFacts = event.data
        if token.price_usd is None:
            return

        # Snapshot current price
        self.db.snapshot_price(
            token.chain, token.address, token.price_usd,
            liquidity=token.liquidity_usd or 0,
            volume=token.volume_24h or 0,
        )

        # Get baseline (first price we recorded)
        baseline = self.db.first_price_in_session(token.chain, token.address)
        if baseline is None or baseline <= 0:
            return

        change_pct = ((token.price_usd - baseline) / baseline) * 100

        for threshold in self.thresholds:
            triggered = False
            if threshold > 0 and change_pct >= threshold:
                triggered = True
            elif threshold < 0 and change_pct <= threshold:
                triggered = True

            if triggered:
                direction = "up" if change_pct > 0 else "down"
                alert = PriceAlert(
                    chain=token.chain,
                    address=token.address,
                    symbol=token.symbol,
                    baseline_price=baseline,
                    current_price=token.price_usd,
                    change_pct=round(change_pct, 2),
                    direction=direction,
                    threshold_pct=threshold,
                )
                log.warning(
                    "ALERT: %s %s %+.1f%% (threshold %+.0f%%)",
                    token.symbol, direction, change_pct, threshold,
                )
                if self._bus:
                    await self._bus.emit("alert.triggered", alert, source=self.name)
                # Update baseline after alert
                self.db.snapshot_price(token.chain, token.address, token.price_usd)
                break
