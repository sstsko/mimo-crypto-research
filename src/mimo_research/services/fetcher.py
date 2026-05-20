"""Data fetcher — DexScreener + Etherscan, the only place that touches external APIs.

Agents never call APIs directly. They request data through the fetcher,
which handles retries, rate limits, and normalization into TokenFacts/ContractFacts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..core.models import TokenFacts, ContractFacts


DEXSCREENER = "https://api.dexscreener.com"
ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"

_CHAIN_IDS: dict[str, int] = {
    "ethereum": 1, "bsc": 56, "polygon": 137,
    "arbitrum": 42161, "optimism": 10, "base": 8453,
    "avalanche": 43114, "fantom": 250,
}


class DataFetcher:
    """Centralized data access — DexScreener market data + Etherscan contract data."""

    def __init__(self, etherscan_key: Optional[str] = None, *, timeout: float = 30.0,
                 client: Optional[httpx.AsyncClient] = None) -> None:
        self.etherscan_key = etherscan_key
        self._owns = client is None
        self._http = client or httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        if self._owns:
            await self._http.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def _get(self, url: str, params: Optional[dict] = None) -> dict:
        r = await self._http.get(url, params=params)
        r.raise_for_status()
        return r.json()

    # ── DexScreener ────────────────────────────────────────────────────

    async def search_tokens(self, query: str) -> list[TokenFacts]:
        data = await self._get(f"{DEXSCREENER}/latest/dex/search", params={"q": query})
        return [self._pair_to_facts(p, f"search:{query}") for p in (data.get("pairs") or []) if p]

    async def token_by_address(self, address: str) -> list[TokenFacts]:
        data = await self._get(f"{DEXSCREENER}/latest/dex/tokens/{address}")
        return [self._pair_to_facts(p, "address") for p in (data.get("pairs") or []) if p]

    async def trending_tokens(self) -> list[TokenFacts]:
        """Pull recently boosted token profiles."""
        try:
            items = await self._get(f"{DEXSCREENER}/token-profiles/latest/v1")
            if not isinstance(items, list):
                return []
            results: list[TokenFacts] = []
            for item in items[:15]:
                addr = item.get("tokenAddress", "")
                if not addr:
                    continue
                try:
                    pairs = await self.token_by_address(addr)
                    if pairs:
                        best = max(pairs, key=lambda p: (p.liquidity_usd or 0))
                        best = best.model_copy(update={"discovery_source": "trending"})
                        results.append(best)
                except Exception:
                    continue
            return results
        except Exception:
            return []

    def _pair_to_facts(self, pair: dict, source: str) -> TokenFacts:
        base = pair.get("baseToken") or {}
        liq = (pair.get("liquidity") or {}).get("usd")
        vol = (pair.get("volume") or {}).get("h24")
        pc = pair.get("priceChange") or {}
        txns = pair.get("txns") or {}
        h24 = txns.get("h24") or {}
        created_ms = pair.get("pairCreatedAt")

        age_hours = None
        if isinstance(created_ms, (int, float)):
            age_hours = (datetime.now(timezone.utc) - datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc)).total_seconds() / 3600

        return TokenFacts(
            chain=str(pair.get("chainId") or "unknown"),
            address=str(base.get("address") or "").lower(),
            symbol=str(base.get("symbol") or "?"),
            name=str(base.get("name") or "?"),
            pair_url=pair.get("url"),
            price_usd=float(pair["priceUsd"]) if pair.get("priceUsd") else None,
            liquidity_usd=float(liq) if liq is not None else None,
            volume_24h=float(vol) if vol is not None else None,
            fdv=float(pair["fdv"]) if pair.get("fdv") else None,
            pair_age_hours=age_hours,
            price_change_5m=float(pc.get("m5")) if pc.get("m5") is not None else None,
            price_change_1h=float(pc.get("h1")) if pc.get("h1") is not None else None,
            price_change_6h=float(pc.get("h6")) if pc.get("h6") is not None else None,
            price_change_24h=float(pc.get("h24")) if pc.get("h24") is not None else None,
            buys_24h=int(h24.get("buys", 0)) if h24.get("buys") is not None else None,
            sells_24h=int(h24.get("sells", 0)) if h24.get("sells") is not None else None,
            dex=str(pair.get("dexId") or ""),
            discovery_source=source,
        )

    # ── Etherscan ──────────────────────────────────────────────────────

    async def inspect_contract(self, chain: str, address: str) -> Optional[ContractFacts]:
        chain_id = _CHAIN_IDS.get(chain.lower())
        if not self.etherscan_key or not chain_id:
            return ContractFacts(
                address=address, chain=chain,
                notes=["skipped: " + ("no API key" if not self.etherscan_key else f"chain {chain} not mapped")],
            )

        try:
            data = await self._get(ETHERSCAN_V2, params={
                "chainid": chain_id, "module": "contract", "action": "getsourcecode",
                "address": address, "apikey": self.etherscan_key,
            })
            result = data.get("result")
            if not isinstance(result, list) or not result:
                return ContractFacts(address=address, chain=chain, notes=["empty response"])

            entry = result[0]
            source = entry.get("SourceCode", "")
            proxy = entry.get("Proxy", "0") == "1"
            impl = entry.get("Implementation", "")

            return ContractFacts(
                address=address, chain=chain,
                is_verified=bool(source and source.strip()),
                is_proxy=proxy,
                deployer=impl if proxy else None,
                notes=[] if (source and source.strip()) else ["unverified contract"],
            )
        except httpx.HTTPError as exc:
            return ContractFacts(address=address, chain=chain, notes=[f"explorer error: {type(exc).__name__}"])
