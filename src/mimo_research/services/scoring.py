"""Composite scoring engine — ranks tokens by multiple weighted factors.

This is NOT an LLM agent. It's a deterministic scoring function that
combines market data, contract data, and risk assessment into a single
comparable score. Used to rank tokens against each other in watchlist
and trending views.

Score range: 0-100 (higher = more interesting for research)
"""

from __future__ import annotations

from ..core.models import TokenFacts, ContractFacts, RiskVerdict


def composite_score(
    token: TokenFacts,
    contract: ContractFacts | None = None,
    risk: RiskVerdict | None = None,
) -> float:
    """Calculate a 0-100 composite score for a token.

    Higher = more worth researching / tracking.
    """
    score = 0.0

    # ── Liquidity (0-25 pts) ──────────────────────────────────────────
    liq = token.liquidity_usd or 0
    if liq >= 10_000_000:
        score += 25
    elif liq >= 1_000_000:
        score += 20
    elif liq >= 100_000:
        score += 15
    elif liq >= 10_000:
        score += 5
    # below 10K = 0

    # ── Volume/Liquidity ratio (0-20 pts) ─────────────────────────────
    vol = token.volume_24h or 0
    if liq > 0:
        ratio = vol / liq
        if ratio >= 2.0:
            score += 20  # very active
        elif ratio >= 0.5:
            score += 15
        elif ratio >= 0.1:
            score += 10
        elif ratio > 0:
            score += 5

    # ── Buy pressure (0-15 pts) ───────────────────────────────────────
    buys = token.buys_24h or 0
    sells = token.sells_24h or 0
    if buys > 0 and sells > 0:
        ratio = buys / sells
        if ratio >= 2.0:
            score += 15
        elif ratio >= 1.5:
            score += 10
        elif ratio >= 1.0:
            score += 5
    elif buys > 10 and sells == 0:
        score += 0  # suspicious — no sells at all

    # ── Contract verification (0-10 pts) ──────────────────────────────
    if contract:
        if contract.is_verified:
            score += 10
        if contract.is_proxy:
            score += 2  # proxy = upgradeable, slight complexity note

    # ── Recency (0-10 pts) ────────────────────────────────────────────
    age = token.pair_age_hours
    if age is not None:
        if age < 24:
            score += 10  # brand new
        elif age < 168:  # 1 week
            score += 7
        elif age < 720:  # 30 days
            score += 3

    # ── Risk penalty (0 to -20 pts) ───────────────────────────────────
    if risk:
        if risk.score >= 80:
            score -= 20
        elif risk.score >= 60:
            score -= 10
        elif risk.score >= 40:
            score -= 5

    return max(0, min(100, score))
