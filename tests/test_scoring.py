"""Tests for the composite scoring engine."""

from mimo_research.services.scoring import composite_score
from mimo_research.core.models import TokenFacts, ContractFacts, RiskVerdict, RiskBand


def test_high_liq_high_score():
    token = TokenFacts(
        chain="eth", address="0x1", symbol="TEST",
        liquidity_usd=5_000_000, volume_24h=3_000_000,
        buys_24h=500, sells_24h=200, pair_age_hours=100,
    )
    contract = ContractFacts(address="0x1", chain="eth", is_verified=True)
    risk = RiskVerdict(score=10, band=RiskBand.LOW, reasoning="ok", confidence=0.9)
    score = composite_score(token, contract, risk)
    assert score >= 60


def test_low_liq_low_score():
    token = TokenFacts(
        chain="eth", address="0x1", symbol="RUG",
        liquidity_usd=500, volume_24h=10,
        buys_24h=2, sells_24h=50, pair_age_hours=5000,
    )
    score = composite_score(token)
    assert score <= 20


def test_new_pair_bonus():
    token = TokenFacts(
        chain="eth", address="0x1", symbol="NEW",
        liquidity_usd=100_000, volume_24h=50_000, pair_age_hours=12,
    )
    score = composite_score(token)
    assert score >= 25


def test_risk_penalty():
    token = TokenFacts(
        chain="eth", address="0x1", symbol="CMP",
        liquidity_usd=1_000_000, pair_age_hours=168,
    )
    risk_high = RiskVerdict(score=90, band=RiskBand.CRITICAL, reasoning="bad", confidence=0.8)
    risk_low = RiskVerdict(score=10, band=RiskBand.LOW, reasoning="ok", confidence=0.9)
    score_high = composite_score(token, risk=risk_high)
    score_low = composite_score(token, risk=risk_low)
    assert score_low > score_high
