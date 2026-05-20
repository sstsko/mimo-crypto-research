"""Reporter agent — generates final markdown research briefs.

Subscribes to: risk.assessed
Emits:         scan.complete

LLM-powered. Takes all verified data + risk verdict, produces a
decision-grade markdown report.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..core.events import Event, EventBus
from ..core.llm import LLMClient
from ..core.models import (
    TokenFacts, ContractFacts, RiskVerdict, RiskBand, ScanResult,
)
from ..services.scoring import composite_score
from .base import Agent

log = logging.getLogger("chainscout.reporter")

_SYSTEM = (
    "You are a crypto research analyst. Write a short, decision-grade brief "
    "for a portfolio manager. Neutral, evidence-led tone. Never recommend "
    "buying or selling — describe what is observable and what is uncertain. "
    "Write in clean markdown."
)


class Reporter(Agent):
    name = "reporter"

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self._bus: Optional[EventBus] = None

    def setup(self, bus: EventBus) -> None:
        self._bus = bus
        bus.subscribe("risk.assessed", self._on_risk)

    async def _on_risk(self, event: Event) -> None:
        token: TokenFacts
        contract: ContractFacts
        verdict: RiskVerdict
        token, contract, verdict = event.data

        log.info("writing report: %s/%s (risk=%s)", token.chain, token.symbol, verdict.band.value)

        score = composite_score(token, contract, verdict)

        # Format data for LLM
        snapshot = self._format_snapshot(token, contract, verdict)
        try:
            report_md = await self.llm.chat(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": snapshot},
                ],
                agent=self.name,
                temperature=0.3,
                max_tokens=2000,
            )
        except Exception as exc:
            log.error("LLM report failed: %s", exc)
            report_md = f"Report generation failed: {exc}"

        result = ScanResult(
            token=token,
            contract=contract,
            risk=verdict,
            report_md=report_md.strip(),
            composite_score=score,
        )

        if self._bus:
            await self._bus.emit("scan.complete", result, source=self.name)

    def _format_snapshot(self, token: TokenFacts, contract: ContractFacts, verdict: RiskVerdict) -> str:
        def _money(v: Optional[float]) -> str:
            if v is None:
                return "n/a"
            if v >= 1_000_000:
                return f"${v/1_000_000:.2f}M"
            if v >= 1_000:
                return f"${v/1_000:.1f}K"
            return f"${v:.2f}"

        def _pct(v: Optional[float]) -> str:
            if v is None:
                return "n/a"
            return f"{'+' if v > 0 else ''}{v:.1f}%"

        # Buy/sell ratio
        ratio = "n/a"
        if token.buys_24h and token.sells_24h and token.sells_24h > 0:
            ratio = f"{token.buys_24h / token.sells_24h:.2f}"

        age_str = f"{token.pair_age_hours:.0f}h" if token.pair_age_hours else "n/a"
        verified = "yes" if contract.is_verified else ("no" if contract.is_verified is False else "n/a")
        honeypot = "suspected" if ("no_sells_with_buys" in contract.notes or "low_liq_under_10k" in contract.notes) else "no"

        return (
            f"Write a research brief for {token.symbol} ({token.chain}).\n\n"
            f"## Market\n"
            f"- Price: {_money(token.price_usd)}\n"
            f"- Liquidity: {_money(token.liquidity_usd)}\n"
            f"- 24h Volume: {_money(token.volume_24h)}\n"
            f"- FDV: {_money(token.fdv)}\n"
            f"- Pair age: {age_str}\n"
            f"- DEX: {token.dex or 'n/a'}\n\n"
            f"## Momentum\n"
            f"- 5m: {_pct(token.price_change_5m)}  |  1h: {_pct(token.price_change_1h)}  "
            f"|  6h: {_pct(token.price_change_6h)}  |  24h: {_pct(token.price_change_24h)}\n\n"
            f"## Activity\n"
            f"- 24h buys: {token.buys_24h or 0}  |  sells: {token.sells_24h or 0}  "
            f"|  ratio: {ratio}\n\n"
            f"## Contract\n"
            f"- Verified: {verified}  |  Proxy: {'yes' if contract.is_proxy else 'no'}\n"
            f"- Honeypot: {honeypot}\n"
            f"- Notes: {', '.join(contract.notes) or 'none'}\n\n"
            f"## Risk Assessment\n"
            f"- Score: {verdict.score}/100 ({verdict.band.value})\n"
            f"- Confidence: {verdict.confidence:.0%}\n"
            f"- Flags: {', '.join(verdict.flags) or 'none'}\n"
            f"- Reasoning: {verdict.reasoning}\n"
        )
