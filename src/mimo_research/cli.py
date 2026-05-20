"""CLI — Click + Rich interface for the crypto scanner.

Commands:
    scan      Scan a token seed (address, symbol, query, or 'trending')
    demo      Run a quick demo scan with a hardcoded trending token
    monitor   Continuous scan loop with configurable interval
    history   Show recent scan history from the database
    stats     Show LLM usage stats and scan counts
    watch     Add a token to the watchlist
    watchlist Show current watchlist entries
    report    Generate a report for a specific token
    dashboard Launch the FastAPI dashboard server
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .config import load_settings
from .core.db import Database
from .core.llm import LLMClient
from .scanner import Scanner
from .services.fetcher import DataFetcher

log = logging.getLogger("chainscout")
console = Console()

DEFAULT_SEEDS = [
    "trending",
    "PEPE",
    "DOGE",
    "SHIB",
]


def _build_scanner(
    db: Database,
    *,
    on_result=None,
    on_alert=None,
) -> Scanner:
    """Build a fully-wired Scanner instance from settings."""
    settings = load_settings()
    llm = LLMClient(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        db,
    )
    fetcher = DataFetcher(etherscan_key=settings.etherscan_key)
    scanner = Scanner(
        db,
        llm,
        fetcher,
        alert_thresholds=settings.alert_thresholds,
        on_result=on_result,
        on_alert=on_alert,
    )
    scanner.boot()
    return scanner


def _load_seeds(seed_file: Optional[str]) -> list[str]:
    """Load seeds from a file or return defaults."""
    if seed_file:
        p = Path(seed_file)
        if p.exists():
            return [line.strip() for line in p.read_text().splitlines() if line.strip() and not line.startswith("#")]
        console.print(f"[red]Seed file not found: {seed_file}[/red]")
        sys.exit(1)
    return DEFAULT_SEEDS


def _risk_style(band: Optional[str]) -> str:
    """Return Rich style for a risk band."""
    if not band:
        return "dim"
    return {"low": "green", "medium": "yellow", "high": "red", "critical": "bold red"}.get(band, "white")


def _print_result(result) -> None:
    """Pretty-print a ScanResult."""
    t = result.token
    risk_band = result.risk.band.value if result.risk else "N/A"
    risk_score = str(result.risk.score) if result.risk else "N/A"

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Key", style="bold cyan", width=16)
    table.add_column("Value")
    table.add_row("Symbol", t.symbol)
    table.add_row("Chain", t.chain)
    table.add_row("Address", t.address[:20] + "..." if len(t.address) > 20 else t.address)
    table.add_row("Price", f"${t.price_usd:.8f}" if t.price_usd and t.price_usd < 0.01 else f"${t.price_usd:,.4f}" if t.price_usd else "N/A")
    table.add_row("Liquidity", f"${t.liquidity_usd:,.0f}" if t.liquidity_usd else "N/A")
    table.add_row("Volume 24h", f"${t.volume_24h:,.0f}" if t.volume_24h else "N/A")
    table.add_row("Risk", Text(risk_band, style=_risk_style(risk_band)))
    table.add_row("Risk Score", risk_score)
    table.add_row("Composite", f"{result.composite_score:.1f}")
    table.add_row("Duration", f"{result.scan_duration_ms}ms")

    console.print(Panel(table, title=f"[bold]{t.symbol}[/bold] on {t.chain}", border_style="blue"))


# ── CLI Group ────────────────────────────────────────────────────────

@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def main(verbose: bool) -> None:
    """mimo-crypto-research — event-driven multi-agent crypto scanner."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ── scan ─────────────────────────────────────────────────────────────

@main.command()
@click.argument("seed", default="trending")
@click.option("-k", "--top-k", default=3, help="Max tokens to scan per seed")
def scan(seed: str, top_k: int) -> None:
    """Scan a token seed (address, symbol, query, or 'trending')."""
    asyncio.run(_scan(seed, top_k))


async def _scan(seed: str, top_k: int) -> None:
    settings = load_settings()
    db = Database(settings.db_path)

    results_collected: list = []

    async def on_result(r):
        results_collected.append(r)
        _print_result(r)

    scanner = _build_scanner(db, on_result=on_result)
    scanner.discoverer.top_k = top_k

    async with scanner:
        if seed.lower() == "trending":
            await scanner.scan_trending(top_k=top_k)
        else:
            await scanner.scan(seed)

    if not results_collected:
        console.print("[yellow]No results found.[/yellow]")
    else:
        console.print(f"\n[green]✓ Scanned {len(results_collected)} token(s)[/green]")


# ── demo ─────────────────────────────────────────────────────────────

@main.command()
def demo() -> None:
    """Run a quick demo scan with trending tokens."""
    console.print(Panel("[bold cyan]Demo Mode[/bold cyan]\nScanning trending tokens...", border_style="cyan"))
    asyncio.run(_scan("trending", 2))


# ── monitor ──────────────────────────────────────────────────────────

@main.command()
@click.option("-i", "--interval", default=300, help="Seconds between scans")
@click.option("-s", "--seeds-file", default=None, help="File with seeds (one per line)")
@click.option("-k", "--top-k", default=3, help="Max tokens per seed")
def monitor(interval: int, seeds_file: Optional[str], top_k: int) -> None:
    """Continuous scan loop with configurable interval."""
    seeds = _load_seeds(seeds_file)
    console.print(f"[cyan]Monitoring {len(seeds)} seed(s) every {interval}s. Ctrl+C to stop.[/cyan]")
    asyncio.run(_monitor(seeds, interval, top_k))


async def _monitor(seeds: list[str], interval: int, top_k: int) -> None:
    settings = load_settings()
    db = Database(settings.db_path)
    scanner = _build_scanner(db)
    scanner.discoverer.top_k = top_k

    async with scanner:
        cycle = 0
        while True:
            cycle += 1
            console.rule(f"[bold]Cycle {cycle}[/bold]")
            for seed in seeds:
                try:
                    console.print(f"  Scanning [cyan]{seed}[/cyan]...")
                    if seed.lower() == "trending":
                        results = await scanner.scan_trending(top_k=top_k)
                    else:
                        results = await scanner.scan(seed)
                    for r in results:
                        _print_result(r)
                    console.print(f"  [green]✓ {len(results)} result(s) for {seed}[/green]")
                except Exception as exc:
                    console.print(f"  [red]✗ {seed}: {exc}[/red]")
                    log.exception("monitor scan failed for %s", seed)
            console.print(f"\n[dim]Next cycle in {interval}s...[/dim]")
            await asyncio.sleep(interval)


# ── history ──────────────────────────────────────────────────────────

@main.command()
@click.option("-n", "--limit", default=20, help="Number of records to show")
def history(limit: int) -> None:
    """Show recent scan history from the database."""
    settings = load_settings()
    db = Database(settings.db_path)
    scans = db.get_recent_scans(limit)

    if not scans:
        console.print("[yellow]No scan history found.[/yellow]")
        return

    table = Table(title="Scan History", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Time", style="cyan", width=20)
    table.add_column("Symbol", style="bold")
    table.add_column("Chain")
    table.add_column("Price", justify="right")
    table.add_column("Liquidity", justify="right")
    table.add_column("Risk", justify="center")
    table.add_column("Composite", justify="right")

    for i, s in enumerate(scans, 1):
        risk_band = s.get("risk_band") or "N/A"
        price = f"${s['price_usd']:,.4f}" if s.get("price_usd") else "N/A"
        liq = f"${s['liquidity_usd']:,.0f}" if s.get("liquidity_usd") else "N/A"
        comp = f"{s['composite_score']:.1f}" if s.get("composite_score") else "N/A"
        ts = s.get("ts", "")[:19]

        table.add_row(
            str(i), ts, s.get("symbol") or "?", s.get("chain") or "?",
            price, liq, Text(risk_band, style=_risk_style(risk_band)), comp,
        )

    console.print(table)


# ── stats ────────────────────────────────────────────────────────────

@main.command()
def stats() -> None:
    """Show LLM usage stats and scan counts."""
    settings = load_settings()
    db = Database(settings.db_path)

    total_tok = db.total_tokens()
    today_tok = db.tokens_today()
    by_agent = db.tokens_by_agent()
    daily = db.daily_tokens(7)
    recent = db.get_recent_scans(1)

    # Summary panel
    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column("Metric", style="bold cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("Total Tokens Used", f"{total_tok:,}")
    summary.add_row("Tokens Today", f"{today_tok:,}")
    summary.add_row("Latest Scan", recent[0]["ts"][:19] if recent else "N/A")
    console.print(Panel(summary, title="[bold]Usage Stats[/bold]", border_style="blue"))

    # Per-agent breakdown
    if by_agent:
        table = Table(title="Tokens by Agent")
        table.add_column("Agent", style="bold")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        for a in by_agent:
            table.add_row(a["agent"], str(a["calls"]), f"{a['tokens']:,}")
        console.print(table)

    # Daily trend
    if daily:
        table = Table(title="Daily Token Usage (7d)")
        table.add_column("Date", style="cyan")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        for d in daily:
            table.add_row(d["date"], str(d["calls"]), f"{d['tokens']:,}")
        console.print(table)


# ── watch ────────────────────────────────────────────────────────────

@main.command()
@click.argument("chain")
@click.argument("address")
@click.option("-s", "--symbol", default="", help="Token symbol")
@click.option("-n", "--name", default="", help="Token name")
@click.option("-t", "--tags", default="", help="Comma-separated tags")
@click.option("--notes", default="", help="Notes")
def watch(chain: str, address: str, symbol: str, name: str, tags: str, notes: str) -> None:
    """Add a token to the watchlist."""
    settings = load_settings()
    db = Database(settings.db_path)
    row_id = db.add_to_watchlist(chain, address, symbol, name, tags, notes)
    if row_id:
        console.print(f"[green]✓ Added {symbol or address} ({chain}) to watchlist (id={row_id})[/green]")
    else:
        console.print(f"[yellow]Token already in watchlist: {chain}/{address}[/yellow]")


# ── watchlist ────────────────────────────────────────────────────────

@main.command()
def watchlist() -> None:
    """Show current watchlist entries."""
    settings = load_settings()
    db = Database(settings.db_path)
    items = db.get_watchlist(active_only=False)

    if not items:
        console.print("[yellow]Watchlist is empty. Use `watch` to add tokens.[/yellow]")
        return

    table = Table(title="Watchlist", show_lines=True)
    table.add_column("#", style="dim", width=4)
    table.add_column("Symbol", style="bold")
    table.add_column("Chain")
    table.add_column("Address", max_width=22)
    table.add_column("Tags")
    table.add_column("Active", justify="center")
    table.add_column("Added", style="dim")

    for i, item in enumerate(items, 1):
        table.add_row(
            str(i),
            item.get("symbol") or "?",
            item.get("chain") or "?",
            (item.get("address") or "")[:20] + "...",
            item.get("tags") or "",
            "✓" if item.get("is_active") else "✗",
            (item.get("added_at") or "")[:19],
        )

    console.print(table)


# ── report ───────────────────────────────────────────────────────────

@main.command()
@click.argument("seed")
@click.option("-k", "--top-k", default=1, help="Max tokens to scan")
def report(seed: str, top_k: int) -> None:
    """Generate a detailed report for a specific token."""
    asyncio.run(_report(seed, top_k))


async def _report(seed: str, top_k: int) -> None:
    settings = load_settings()
    db = Database(settings.db_path)
    scanner = _build_scanner(db)
    scanner.discoverer.top_k = top_k

    async with scanner:
        if seed.lower() == "trending":
            results = await scanner.scan_trending(top_k=top_k)
        else:
            results = await scanner.scan(seed)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    for result in results:
        _print_result(result)
        if result.report_md:
            console.print(Panel(result.report_md, title="LLM Report", border_style="green"))
        if result.risk:
            console.print(f"[bold]Risk Reasoning:[/bold] {result.risk.reasoning}")
            if result.risk.flags:
                console.print("[bold red]Flags:[/bold red]")
                for flag in result.risk.flags:
                    console.print(f"  ⚠ {flag}")


# ── dashboard ────────────────────────────────────────────────────────

@main.command()
@click.option("-p", "--port", default=None, type=int, help="Port (default from settings)")
@click.option("--host", default="0.0.0.0", help="Bind host")
def dashboard(port: Optional[int], host: str) -> None:
    """Launch the FastAPI dashboard server."""
    import uvicorn

    settings = load_settings()
    db = Database(settings.db_path)
    port = port or settings.dashboard_port

    from .dashboard import create_app

    app = create_app(db, settings)
    console.print(f"[cyan]Dashboard starting on http://{host}:{port}[/cyan]")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
