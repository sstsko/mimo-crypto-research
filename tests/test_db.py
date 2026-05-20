"""Tests for the database layer."""

from pathlib import Path

from mimo_research.core.db import Database


def test_watchlist_crud(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite")
    db.add_to_watchlist("ethereum", "0xabc", symbol="TEST")
    items = db.get_watchlist()
    assert len(items) == 1
    assert items[0]["symbol"] == "TEST"
    assert items[0]["chain"] == "ethereum"
    assert db.remove_from_watchlist("ethereum", "0xabc")
    assert len(db.get_watchlist()) == 0


def test_positions(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite")
    pid = db.open_position("ethereum", "0xabc", "TEST", 100.0, 50.0)
    positions = db.get_positions()
    assert len(positions) == 1
    assert positions[0]["quantity"] == 100.0
    assert positions[0]["cost_basis"] == 50.0
    db.close_position(pid)
    assert len(db.get_positions()) == 0
    assert len(db.get_positions(status="closed")) == 1


def test_scan_history(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite")
    db.record_scan(chain="ethereum", address="0xabc", symbol="TEST", risk_score=42)
    scans = db.get_recent_scans()
    assert len(scans) == 1
    assert scans[0]["risk_score"] == 42
    assert scans[0]["symbol"] == "TEST"


def test_llm_usage(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite")
    db.record_llm(agent="risk", model="m", prompt_tok=100, comp_tok=50)
    db.record_llm(agent="reporter", model="m", prompt_tok=200, comp_tok=100)
    assert db.total_tokens() == 450
    assert db.tokens_today() == 450
    by_agent = db.tokens_by_agent()
    assert len(by_agent) == 2


def test_price_snapshots(tmp_path: Path):
    db = Database(tmp_path / "test.sqlite")
    db.snapshot_price("ethereum", "0xabc", 1.0)
    db.snapshot_price("ethereum", "0xabc", 2.0)
    history = db.get_price_history("ethereum", "0xabc")
    assert len(history) == 2
    assert db.first_price_in_session("ethereum", "0xabc") == 1.0
