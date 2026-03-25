import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import asyncio
import tempfile
from brokers.ghost_broker import GhostBroker


@pytest.fixture
def broker(tmp_path):
    db = tmp_path / "ghost_test.db"
    b = GhostBroker(db_path=db)
    yield b
    b.close()


@pytest.mark.asyncio
async def test_initial_equity_is_100k(broker):
    equity = await broker.get_equity()
    assert equity == 100_000.0


@pytest.mark.asyncio
async def test_enter_long_creates_position(broker):
    await broker.enter_long("NVDA", price=500.0, score=8.0, label="💎 INSTITUTIONAL")
    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "NVDA"
    assert positions[0].direction == "LONG"


@pytest.mark.asyncio
async def test_check_exits_tp_closes_position(broker):
    await broker.enter_long("AAPL", price=100.0, score=7.0, label="🟢 BULL BREAKOUT")
    # Simulate price rising 2% — should hit TP at 1.5%
    await broker.check_exits("AAPL", current_price=102.0)
    positions = await broker.get_positions()
    assert len(positions) == 0
    stats = broker.get_stats()
    assert stats["total_trades"] == 1
    assert stats["winning_trades"] == 1
    assert stats["gross_profit"] > 0


@pytest.mark.asyncio
async def test_check_exits_sl_closes_position(broker):
    await broker.enter_long("TSLA", price=200.0, score=6.5, label="🟢 STRENGTH")
    # Simulate price dropping 1% — hits SL at 0.75%
    await broker.check_exits("TSLA", current_price=198.0)
    positions = await broker.get_positions()
    assert len(positions) == 0
    stats = broker.get_stats()
    assert stats["total_trades"] == 1
    assert stats["winning_trades"] == 0
    assert stats["gross_loss"] < 0


@pytest.mark.asyncio
async def test_flatten_all_clears_positions(broker):
    await broker.enter_long("META", price=500.0, score=7.0, label="🟢 BULL BREAKOUT")
    await broker.enter_long("MSFT", price=400.0, score=6.0, label="🟢 STRENGTH")
    result = await broker.flatten_all()
    assert result.positions_closed == 2
    positions = await broker.get_positions()
    assert len(positions) == 0


@pytest.mark.asyncio
async def test_kelly_uses_fixed_1pct_during_warmup(broker):
    # Less than 10 trades — should use fixed 1% of equity
    equity = await broker.get_equity()
    # Enter and check position size via qty * price ≈ 1% equity
    await broker.enter_long("AMD", price=100.0, score=8.0, label="💎 INSTITUTIONAL")
    positions = await broker.get_positions()
    assert len(positions) == 1
    # qty * price should be ≈ 1% of 100k = $1000
    qty = positions[0].qty
    assert abs(qty * 100.0 - 1000.0) < 1.0  # within $1 rounding


@pytest.mark.asyncio
async def test_equity_updates_after_winning_trade(broker):
    initial_equity = await broker.get_equity()
    await broker.enter_long("PLTR", price=25.0, score=8.0, label="💎 INSTITUTIONAL")
    await broker.check_exits("PLTR", current_price=25.5)  # +2% → TP hit
    new_equity = await broker.get_equity()
    assert new_equity > initial_equity


@pytest.mark.asyncio
async def test_profit_factor_computed_correctly(broker):
    # One win, one loss
    await broker.enter_long("A", price=100.0, score=8.0, label="test")
    await broker.check_exits("A", current_price=102.0)  # TP
    await broker.enter_long("B", price=100.0, score=7.0, label="test")
    await broker.check_exits("B", current_price=98.0)  # SL
    stats = broker.get_stats()
    assert stats["profit_factor"] > 0
    assert stats["win_rate"] == 50.0
