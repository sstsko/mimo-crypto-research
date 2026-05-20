"""Data contracts — shared between all agents and services."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class RiskBand(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TokenFacts(BaseModel):
    """Verified market data from DexScreener — no LLM involvement."""
    chain: str
    address: str
    symbol: str = "?"
    name: str = "?"
    pair_url: Optional[str] = None
    price_usd: Optional[float] = None
    liquidity_usd: Optional[float] = None
    volume_24h: Optional[float] = None
    fdv: Optional[float] = None
    pair_age_hours: Optional[float] = None
    price_change_5m: Optional[float] = None
    price_change_1h: Optional[float] = None
    price_change_6h: Optional[float] = None
    price_change_24h: Optional[float] = None
    buys_24h: Optional[int] = None
    sells_24h: Optional[int] = None
    dex: Optional[str] = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    discovery_source: str = ""


class ContractFacts(BaseModel):
    """Verified onchain data from explorer — no LLM involvement."""
    address: str
    chain: str
    is_verified: Optional[bool] = None
    has_transfer_fn: Optional[bool] = None
    is_proxy: Optional[bool] = None
    deployer: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class RiskVerdict(BaseModel):
    """LLM-generated risk assessment."""
    score: int = Field(ge=0, le=100, description="0=safe, 100=max risk")
    band: RiskBand
    flags: list[str] = Field(default_factory=list)
    reasoning: str
    confidence: float = Field(ge=0, le=1, description="How confident the model is")


class ScanResult(BaseModel):
    """Complete output of one scan cycle for a single token."""
    token: TokenFacts
    contract: Optional[ContractFacts] = None
    risk: Optional[RiskVerdict] = None
    report_md: Optional[str] = None
    composite_score: float = 0.0
    scan_duration_ms: int = 0
    llm_tokens_used: int = 0


class ScanRequest(BaseModel):
    """Input to the scanner — what to scan."""
    seed: str
    source: str = "manual"  # manual, watchlist, trending, cron
    top_k: int = 1


class PriceAlert(BaseModel):
    """A triggered price movement alert."""
    chain: str
    address: str
    symbol: str
    baseline_price: float
    current_price: float
    change_pct: float
    direction: str  # "up" or "down"
    threshold_pct: float
