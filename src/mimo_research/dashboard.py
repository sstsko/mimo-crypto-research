"""Dashboard — FastAPI web UI for scan history, stats, and watchlist.

Factory pattern: create_app(db, settings) returns a FastAPI instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

if TYPE_CHECKING:
    from .config import Settings
    from .core.db import Database

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ChainScanner Dashboard</title>
<style>
  :root {
    --primary: #818cf8;
    --primary-dark: #6366f1;
    --bg: #0f172a;
    --surface: #1e293b;
    --surface-2: #334155;
    --text: #e2e8f0;
    --text-dim: #94a3b8;
    --green: #4ade80;
    --red: #f87171;
    --yellow: #fbbf24;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    padding: 2rem;
  }
  h1 {
    font-size: 1.75rem;
    margin-bottom: 0.25rem;
    color: var(--primary);
  }
  .subtitle { color: var(--text-dim); margin-bottom: 2rem; font-size: 0.9rem; }
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }
  .card {
    background: var(--surface);
    border: 1px solid var(--surface-2);
    border-radius: 12px;
    padding: 1.25rem;
  }
  .card .label { color: var(--text-dim); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .card .value { font-size: 1.75rem; font-weight: 700; margin-top: 0.25rem; color: var(--primary); }
  .section { margin-bottom: 2rem; }
  .section h2 { font-size: 1.2rem; margin-bottom: 0.75rem; color: var(--text); }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 0.6rem 0.75rem; text-align: left; border-bottom: 1px solid var(--surface-2); }
  th { color: var(--text-dim); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; }
  td { font-size: 0.9rem; }
  .badge {
    display: inline-block;
    padding: 0.15rem 0.5rem;
    border-radius: 6px;
    font-size: 0.8rem;
    font-weight: 600;
  }
  .badge-low { background: rgba(74,222,128,0.15); color: var(--green); }
  .badge-medium { background: rgba(251,191,36,0.15); color: var(--yellow); }
  .badge-high { background: rgba(248,113,113,0.15); color: var(--red); }
  .badge-critical { background: rgba(248,113,113,0.25); color: var(--red); font-weight: 700; }
  .refresh-note { color: var(--text-dim); font-size: 0.75rem; margin-top: 1rem; }
  a { color: var(--primary); text-decoration: none; }
  a:hover { text-decoration: underline; }
</style>
</head>
<body>
  <h1>⚡ ChainScanner</h1>
  <p class="subtitle">Event-driven multi-agent crypto research dashboard</p>

  <div class="cards" id="cards">
    <div class="card"><div class="label">Total Scans</div><div class="value" id="stat-scans">—</div></div>
    <div class="card"><div class="label">Tokens Today</div><div class="value" id="stat-tokens-today">—</div></div>
    <div class="card"><div class="label">Total Tokens Used</div><div class="value" id="stat-tokens-total">—</div></div>
    <div class="card"><div class="label">Watchlist Items</div><div class="value" id="stat-watchlist">—</div></div>
  </div>

  <div class="section">
    <h2>Recent Scans</h2>
    <table>
      <thead>
        <tr>
          <th>Time</th><th>Symbol</th><th>Chain</th><th>Price</th>
          <th>Liquidity</th><th>Risk</th><th>Composite</th>
        </tr>
      </thead>
      <tbody id="scans-body"></tbody>
    </table>
  </div>

  <div class="section">
    <h2>Agent Usage Breakdown</h2>
    <table>
      <thead>
        <tr><th>Agent</th><th>Calls</th><th>LLM Tokens</th></tr>
      </thead>
      <tbody id="agents-body"></tbody>
    </table>
  </div>

  <p class="refresh-note">Auto-refreshes every 30 seconds. Last update: <span id="last-update">—</span></p>

<script>
async function load() {
  try {
    const [statsRes, scansRes, watchRes] = await Promise.all([
      fetch('/api/stats'), fetch('/api/scans?limit=50'), fetch('/api/watchlist')
    ]);
    const stats = await statsRes.json();
    const scans = await scansRes.json();
    const watch = await watchRes.json();

    document.getElementById('stat-scans').textContent = stats.total_scans.toLocaleString();
    document.getElementById('stat-tokens-today').textContent = stats.tokens_today.toLocaleString();
    document.getElementById('stat-tokens-total').textContent = stats.total_tokens.toLocaleString();
    document.getElementById('stat-watchlist').textContent = watch.length.toLocaleString();

    const tbody = document.getElementById('scans-body');
    tbody.innerHTML = scans.map(s => {
      const risk = s.risk_band || 'N/A';
      const badge = `badge-${risk}`;
      return `<tr>
        <td>${(s.ts||'').slice(0,19)}</td>
        <td><strong>${s.symbol||'?'}</strong></td>
        <td>${s.chain||'?'}</td>
        <td>${s.price_usd ? '$'+s.price_usd.toLocaleString(undefined,{maximumFractionDigits:6}) : 'N/A'}</td>
        <td>${s.liquidity_usd ? '$'+Math.round(s.liquidity_usd).toLocaleString() : 'N/A'}</td>
        <td><span class="badge ${badge}">${risk}</span></td>
        <td>${s.composite_score != null ? s.composite_score.toFixed(1) : 'N/A'}</td>
      </tr>`;
    }).join('');

    const agentsTbody = document.getElementById('agents-body');
    agentsTbody.innerHTML = (stats.tokens_by_agent||[]).map(a =>
      `<tr><td>${a.agent}</td><td>${a.calls}</td><td>${(a.tokens||0).toLocaleString()}</td></tr>`
    ).join('');

    document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
  } catch(e) { console.error('Dashboard refresh failed:', e); }
}
load();
setInterval(load, 30000);
</script>
</body>
</html>"""


def create_app(db: "Database", settings: "Settings") -> FastAPI:
    """FastAPI app factory."""
    app = FastAPI(title="ChainScanner Dashboard", version="3.0.0")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return _DASHBOARD_HTML

    @app.get("/api/stats")
    async def api_stats():
        return {
            "total_scans": len(db.get_recent_scans(limit=10000)),
            "total_tokens": db.total_tokens(),
            "tokens_today": db.tokens_today(),
            "tokens_by_agent": db.tokens_by_agent(),
            "daily_tokens": db.daily_tokens(7),
        }

    @app.get("/api/scans")
    async def api_scans(limit: int = 50):
        return db.get_recent_scans(limit)

    @app.get("/api/watchlist")
    async def api_watchlist():
        return db.get_watchlist(active_only=False)

    return app
