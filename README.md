# mimo-crypto-research

**Event-Driven Multi-Agent Crypto Scanner — Powered by Xiaomi MiMo V2.5**

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![MiMo](https://img.shields.io/badge/Powered%20by-MiMo%20V2.5-orange.svg)](https://platform.xiaomimimo.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-26%20passing-brightgreen.svg)](#testing)

---

## What is this?

An **event-driven multi-agent crypto scanner** that watches DEX markets across every major chain and produces decision-grade research notes automatically, powered by Xiaomi MiMo V2.5.

Unlike linear pipeline bots where agents call each other directly, this project uses an **async pub/sub EventBus** — agents subscribe to events they care about and emit events when they're done. Agents are fully decoupled and can be added/removed without touching the orchestrator.

---

## Architecture

```
              Event-Driven Agent Architecture

     scan.requested
           │
           ▼
    ┌──────────────┐
    │  Discoverer  │  (deterministic — DexScreener)
    └──────┬───────┘
           │ token.discovered
           ├──────────────────────┐
           ▼                      ▼
  ┌─────────────────┐    ┌────────────────┐
  │ ContractChecker │    │  AlertWatcher  │  (price threshold alerts)
  │ (Etherscan v2)  │    └────────────────┘
  └────────┬────────┘
           │ contract.checked
           ▼
  ┌─────────────────┐
  │  RiskAnalyst    │  ← MiMo V2.5 (~1.2K tokens)
  │  9-dim CoT      │
  └────────┬────────┘
           │ risk.assessed
           ▼
  ┌─────────────────┐
  │   Reporter      │  ← MiMo V2.5 (~1.5K tokens)
  │  markdown brief │
  └────────┬────────┘
           │ scan.complete
           ▼
      SQLite DB + Dashboard
```

Agents **never call each other**. They emit events to the EventBus and subscribe to the events they need. The Scanner wires everything at boot.

---

## Key differences from typical crypto bots

| Feature | This project | Typical bots |
|---|---|---|
| Agent communication | **Event-driven pub/sub** | Linear pipeline / direct calls |
| State persistence | **SQLite** (watchlist, portfolio, history, prices) | In-memory or none |
| Token ranking | **Composite scoring** (6 weighted dimensions) | Single LLM number |
| Risk assessment | **9 dimensions** via long-chain CoT | 1 LLM call |
| Price alerts | **Baseline tracking** + configurable thresholds | None |
| Portfolio tracking | **Open/close positions** with cost basis | None |

---

## The five agents

| # | Agent | Type | Subscribes to | Emits |
|---|---|---|---|---|
| 1 | **Discoverer** | deterministic | `scan.requested` | `token.discovered` |
| 2 | **ContractChecker** | deterministic | `token.discovered` | `contract.checked` |
| 3 | **AlertWatcher** | deterministic | `token.discovered` | `alert.triggered` |
| 4 | **RiskAnalyst** | **LLM** | `contract.checked` | `risk.assessed` |
| 5 | **Reporter** | **LLM** | `risk.assessed` | `scan.complete` |

The RiskAnalyst reasons over 9 dimensions: liquidity depth, volume/liquidity ratio, FDV/liquidity ratio, pair age, contract verification, buy/sell ratio, price momentum, honeypot signals, and market activity.

---

## Quick start

```bash
git clone https://github.com/sstsko/mimo-crypto-research.git
cd mimo-crypto-research
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # edit with your MiMo / Etherscan keys

# Smoke test (no LLM) — DexScreener candidates for PEPE
chainscout demo --no-api

# Full scan with LLM
chainscout scan 0x6982508145454ce325ddbe47a25d4ec3d2311933

# 24/7 autonomous monitor
chainscout monitor

# With trending auto-discovery
chainscout monitor --trending --trending-top-k 5

# Add tokens to watchlist
chainscout watch ethereum 0x6982508145454ce325ddbe47a25d4ec3d2311933 -s PEPE

# View watchlist
chainscout watchlist

# Scan history
chainscout history

# Token usage stats
chainscout stats

# Daily report
chainscout report

# Live web dashboard
chainscout dashboard --port 8080
```

---

## Configuration

`.env`:

```bash
LLM_BASE_URL=https://platform.xiaomimimo.com/v1
LLM_API_KEY=***
LLM_MODEL=mimo-v2.5-flagship

# Optional — Etherscan for contract verification
ETHERSCAN_API_KEY=

# Optional — Telegram alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Database path
DB_PATH=data/chainscout.sqlite

# Price alert thresholds (comma-separated %)
ALERT_THRESHOLDS=-5,-10,5,10
```

Any OpenAI-compatible endpoint works — swap for OpenAI, DeepSeek, OpenRouter, vLLM, or local MiMo gateway.

---

## Project structure

```
src/mimo_research/
├── core/
│   ├── events.py          # Async pub/sub EventBus
│   ├── db.py              # SQLite: watchlist, positions, scans, prices, LLM usage
│   ├── llm.py             # OpenAI-compatible client with auto token logging
│   └── models.py          # Pydantic contracts: TokenFacts, RiskVerdict, etc.
├── agents/
│   ├── base.py            # Abstract Agent interface
│   ├── discoverer.py      # DexScreener discovery + trending
│   ├── contract_checker.py # Etherscan v2 + honeypot heuristics
│   ├── risk_analyst.py    # MiMo V2.5 — 9-dimension risk scoring
│   ├── reporter.py        # MiMo V2.5 — markdown research brief
│   └── alert_watcher.py   # Price movement alerts
├── services/
│   ├── fetcher.py         # Centralized API access (DexScreener + Etherscan)
│   └── scoring.py         # Deterministic composite scoring engine
├── scanner.py             # Orchestrator — wires agents to EventBus
├── cli.py                 # chainscout CLI (Click + Rich)
├── dashboard.py           # FastAPI live dashboard
└── config.py              # .env loader
```

---

## Testing

```bash
pytest -q
```

26 tests, no network or LLM calls — all mocked.

---

## Token consumption

| Mode | Tokens/Hour | Tokens/Day | Scans/Day |
|---|---:|---:|---:|
| **Monitor** (19 seeds + trending, 60s) | ~42K | ~1M | ~190 |
| **Single scan** | — | ~2.7K | 1 |
| **Demo (scout only)** | 0 | 0 | unlimited |

Every LLM call is logged to SQLite with prompt/completion tokens, agent, model, and latency.

---

## License

MIT — see [LICENSE](LICENSE).

---

**Built on Xiaomi MiMo V2.5** — submitted to the [MiMo 100T Token Challenge](https://100t.xiaomimimo.com).
