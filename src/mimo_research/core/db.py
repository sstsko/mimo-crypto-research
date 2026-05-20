"""SQLite database — single source of truth for watchlist, portfolio, scans, and LLM usage.

All state lives in one SQLite file. No JSON files, no in-memory-only state.
Tables:
  - watchlist     — tokens the user is tracking
  - positions     — portfolio entries with cost basis
  - scan_history  — every completed scan with scores
  - llm_usage     — per-call token accounting
  - price_snapshots — historical price points for alert/comparison
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain       TEXT NOT NULL,
                    address     TEXT NOT NULL,
                    symbol      TEXT,
                    name        TEXT,
                    added_at    TEXT NOT NULL,
                    tags        TEXT DEFAULT '',
                    notes       TEXT DEFAULT '',
                    is_active   INTEGER DEFAULT 1,
                    UNIQUE(chain, address)
                );

                CREATE TABLE IF NOT EXISTS positions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    chain       TEXT NOT NULL,
                    address     TEXT NOT NULL,
                    symbol      TEXT,
                    quantity    REAL NOT NULL DEFAULT 0,
                    cost_basis  REAL NOT NULL DEFAULT 0,
                    opened_at   TEXT NOT NULL,
                    closed_at   TEXT,
                    status      TEXT DEFAULT 'open'
                );

                CREATE TABLE IF NOT EXISTS scan_history (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts              TEXT NOT NULL,
                    chain           TEXT NOT NULL,
                    address         TEXT NOT NULL,
                    symbol          TEXT,
                    liquidity_usd   REAL,
                    volume_24h      REAL,
                    price_usd       REAL,
                    risk_score      INTEGER,
                    risk_band       TEXT,
                    composite_score REAL,
                    llm_tokens      INTEGER DEFAULT 0,
                    duration_ms     INTEGER DEFAULT 0,
                    report_path     TEXT
                );

                CREATE TABLE IF NOT EXISTS llm_usage (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          TEXT NOT NULL,
                    agent       TEXT NOT NULL,
                    model       TEXT NOT NULL,
                    prompt_tok  INTEGER NOT NULL DEFAULT 0,
                    comp_tok    INTEGER NOT NULL DEFAULT 0,
                    total_tok   INTEGER NOT NULL DEFAULT 0,
                    latency_ms  INTEGER,
                    scan_id     INTEGER
                );

                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts          TEXT NOT NULL,
                    chain       TEXT NOT NULL,
                    address     TEXT NOT NULL,
                    price_usd   REAL,
                    liquidity   REAL,
                    volume_24h  REAL
                );

                CREATE INDEX IF NOT EXISTS idx_scan_ts ON scan_history(ts);
                CREATE INDEX IF NOT EXISTS idx_usage_ts ON llm_usage(ts);
                CREATE INDEX IF NOT EXISTS idx_price_snap ON price_snapshots(chain, address, ts);
                CREATE INDEX IF NOT EXISTS idx_watchlist_active ON watchlist(is_active);
            """)

    # ── Watchlist ──────────────────────────────────────────────────────

    def add_to_watchlist(self, chain: str, address: str, symbol: str = "", name: str = "",
                         tags: str = "", notes: str = "") -> int:
        now = _now()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO watchlist (chain, address, symbol, name, added_at, tags, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chain, address.lower(), symbol, name, now, tags, notes),
            )
            return cur.lastrowid or 0

    def remove_from_watchlist(self, chain: str, address: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM watchlist WHERE chain=? AND address=?",
                (chain, address.lower()),
            )
            return cur.rowcount > 0

    def get_watchlist(self, *, active_only: bool = True) -> list[dict]:
        with self.connect() as conn:
            q = "SELECT * FROM watchlist"
            if active_only:
                q += " WHERE is_active=1"
            q += " ORDER BY added_at DESC"
            return [dict(r) for r in conn.execute(q).fetchall()]

    # ── Positions ──────────────────────────────────────────────────────

    def open_position(self, chain: str, address: str, symbol: str,
                      quantity: float, cost_basis: float) -> int:
        now = _now()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO positions (chain, address, symbol, quantity, cost_basis, opened_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chain, address.lower(), symbol, quantity, cost_basis, now),
            )
            return cur.lastrowid or 0

    def close_position(self, position_id: int) -> bool:
        now = _now()
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE positions SET status='closed', closed_at=? WHERE id=? AND status='open'",
                (now, position_id),
            )
            return cur.rowcount > 0

    def get_positions(self, *, status: str = "open") -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM positions WHERE status=? ORDER BY opened_at DESC", (status,)
            ).fetchall()]

    # ── Scan History ───────────────────────────────────────────────────

    def record_scan(self, **kwargs) -> int:
        now = _now()
        with self.connect() as conn:
            cols = ["ts"] + list(kwargs.keys())
            vals = [now] + list(kwargs.values())
            placeholders = ", ".join("?" * len(cols))
            cur = conn.execute(
                f"INSERT INTO scan_history ({', '.join(cols)}) VALUES ({placeholders})", vals
            )
            return cur.lastrowid or 0

    def get_recent_scans(self, limit: int = 30) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM scan_history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()]

    def get_scans_for_token(self, chain: str, address: str, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM scan_history WHERE chain=? AND address=? ORDER BY id DESC LIMIT ?",
                (chain, address.lower(), limit),
            ).fetchall()]

    # ── LLM Usage ──────────────────────────────────────────────────────

    def record_llm(self, *, agent: str, model: str, prompt_tok: int, comp_tok: int,
                   latency_ms: int = 0, scan_id: Optional[int] = None) -> int:
        now = _now()
        total = prompt_tok + comp_tok
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO llm_usage (ts, agent, model, prompt_tok, comp_tok, total_tok, latency_ms, scan_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (now, agent, model, prompt_tok, comp_tok, total, latency_ms, scan_id),
            )
            return cur.lastrowid or 0

    def total_tokens(self) -> int:
        with self.connect() as conn:
            r = conn.execute("SELECT COALESCE(SUM(total_tok),0) FROM llm_usage").fetchone()
            return int(r[0])

    def tokens_today(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.connect() as conn:
            r = conn.execute(
                "SELECT COALESCE(SUM(total_tok),0) FROM llm_usage WHERE ts LIKE ?",
                (f"{today}%",),
            ).fetchone()
            return int(r[0])

    def tokens_by_agent(self) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT agent, COUNT(*) as calls, SUM(total_tok) as tokens "
                "FROM llm_usage GROUP BY agent ORDER BY tokens DESC"
            ).fetchall()]

    def daily_tokens(self, days: int = 7) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT substr(ts,1,10) as date, COUNT(*) as calls, SUM(total_tok) as tokens "
                "FROM llm_usage GROUP BY date ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()]

    # ── Price Snapshots ────────────────────────────────────────────────

    def snapshot_price(self, chain: str, address: str, price: float,
                       liquidity: float = 0, volume: float = 0) -> int:
        now = _now()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO price_snapshots (ts, chain, address, price_usd, liquidity, volume_24h) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (now, chain, address.lower(), price, liquidity, volume),
            )
            return cur.lastrowid or 0

    def get_price_history(self, chain: str, address: str, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM price_snapshots WHERE chain=? AND address=? ORDER BY ts DESC LIMIT ?",
                (chain, address.lower(), limit),
            ).fetchall()]

    def first_price_in_session(self, chain: str, address: str) -> Optional[float]:
        """Get the earliest price snapshot for this token (for alert baseline)."""
        with self.connect() as conn:
            r = conn.execute(
                "SELECT price_usd FROM price_snapshots WHERE chain=? AND address=? ORDER BY ts ASC LIMIT 1",
                (chain, address.lower()),
            ).fetchone()
            return float(r["price_usd"]) if r and r["price_usd"] else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
