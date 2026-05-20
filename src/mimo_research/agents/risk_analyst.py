"""Risk analyst agent — LLM-driven risk assessment.

Subscribes to: contract.checked
Emits:         risk.assessed

This is where MiMo V2.5 long-chain reasoning lives. Takes verified
market data + contract data, asks the LLM to reason over 9 dimensions,
returns a typed RiskVerdict.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from ..core.events import Event, EventBus
from ..core.llm import LLMClient
from ..core.models import TokenFacts, ContractFacts, RiskVerdict, RiskBand
from .base import Agent

log = logging.getLogger("chainscout.risk")

_SYSTEM = (
    "You are a senior crypto risk analyst for a DeFi research desk. "
    "You evaluate tokens for rug-pull, honeypot, low-liquidity, wash-trading, "
    "and concentration risks. You ALWAYS return a single JSON object. "
    "Be conservative — when uncertain, score risk higher and explain why."
)

_SCHEMA = """{
  "score": <int 0-100, 0=safe, 100=critical>,
  "band": "low" | "medium" | "high" | "critical",
  "flags": ["<short_flag>", ...],
  "reasoning": "<2-4 sentences>",
  "confidence": <float 0-1>
}"""

_DIMENSIONS = [
    "liquidity_depth",
    "volume_to_liquidity_ratio",
    "fdv_to_liquidity_ratio",
    "pair_age",
    "contract_verification_status",
    "buy_sell_transaction_ratio",
    "price_momentum_5m_1h_6h_24h",
    "honeypot_signals",
    "overall_market_activity",
]


class RiskAnalyst(Agent):
    name = "risk_analyst"

    def __init__(self, llm: LLMClient) -> None:
        self.llm = llm
        self._bus: Optional[EventBus] = None

    def setup(self, bus: EventBus) -> None:
        self._bus = bus
        bus.subscribe("contract.checked", self._on_checked)

    async def _on_checked(self, event: Event) -> None:
        token: TokenFacts
        contract: ContractFacts
        token, contract = event.data

        log.info("assessing risk: %s/%s", token.chain, token.symbol)

        prompt = self._build_prompt(token, contract)
        scan_id = getattr(event.data, "_scan_id", None)

        try:
            raw = await self.llm.chat_json(
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                agent=self.name,
                temperature=0.1,
                max_tokens=1200,
                scan_id=scan_id,
            )
            verdict = self._parse_verdict(raw)
        except Exception as exc:
            log.error("LLM risk assessment failed: %s", exc)
            verdict = RiskVerdict(
                score=80, band=RiskBand.HIGH,
                flags=["llm_error"],
                reasoning=f"LLM call failed: {exc}",
                confidence=0.1,
            )

        if self._bus:
            await self._bus.emit("risk.assessed", (token, contract, verdict), source=self.name)

    def _build_prompt(self, token: TokenFacts, contract: ContractFacts) -> str:
        data = {
            "token": token.model_dump(mode="json"),
            "contract": contract.model_dump(mode="json"),
            "dimensions": _DIMENSIONS,
        }
        return (
            "Assess this token's risk. Walk through each dimension mentally "
            "before scoring. Return ONLY this JSON schema:\n\n"
            f"{_SCHEMA}\n\n"
            f"{json.dumps(data, indent=2, default=str)}"
        )

    def _parse_verdict(self, raw: dict) -> RiskVerdict:
        try:
            score = int(raw.get("score", 80))
            band_str = str(raw.get("band", "high")).lower()
            band = RiskBand(band_str) if band_str in RiskBand.__members__.values() else RiskBand.HIGH
            return RiskVerdict(
                score=max(0, min(100, score)),
                band=band,
                flags=[str(f) for f in (raw.get("flags") or [])],
                reasoning=str(raw.get("reasoning", "")),
                confidence=float(raw.get("confidence", 0.5)),
            )
        except (ValueError, TypeError):
            return RiskVerdict(
                score=80, band=RiskBand.HIGH,
                flags=["parse_error"],
                reasoning="Failed to parse LLM response",
                confidence=0.1,
            )
