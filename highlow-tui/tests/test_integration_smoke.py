"""Smoke tests — verify the app instantiates and core modules wire together."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from core.state_store import CentralStateStore
from core.copilot import CopilotEngine
from core.sparkline import sparkline
from brokers.ghost_broker import GhostBroker
from collections import deque
import tempfile


@pytest.fixture(autouse=True)
def reset():
    CentralStateStore.reset()
    yield
    CentralStateStore.reset()


def test_full_pipeline_smoke():
    """End-to-end: price update → copilot score → ghost entry."""
    store = CentralStateStore.get()
    store.add_symbol("NVDA")
    store.add_symbol("SPY")

    # Simulate SPY dropping
    store.update_price("SPY", 500.0)
    store.update_price("SPY", 498.0)

    # Simulate NVDA rising while SPY falls
    store.update_price("NVDA", 100.0, volume=3_000_000)
    nvda = store.get_symbol("NVDA")
    nvda.avg_volume = 1_000_000
    nvda.vwap = 98.0
    nvda.rsi = 62.0
    nvda.market_open = True
    store.update_price("NVDA", 102.0, volume=3_500_000)
    store.increment_count("NVDA")

    engine = CopilotEngine()
    spy_state = store.get_symbol("SPY")
    score, label = engine.score(nvda, spy_state)

    assert score > 0, f"Expected positive score for bullish setup, got {score}"
    assert label != "— CLOSED"
    assert isinstance(label, str)


def test_sparkline_integrates_with_price_history():
    store = CentralStateStore.get()
    store.add_symbol("AAPL")
    for p in [150, 151, 152, 153, 154, 153, 152, 151, 155, 156]:
        store.update_price("AAPL", float(p))
    state = store.get_symbol("AAPL")
    spark = sparkline(state.price_history)
    assert len(spark) == len(state.price_history)
    assert all(c in "▁▂▃▄▅▆▇█" for c in spark)


@pytest.mark.asyncio
async def test_ghost_broker_full_trade_cycle(tmp_path):
    db = tmp_path / "smoke_test.db"
    broker = GhostBroker(db_path=db)
    await broker.enter_long("PLTR", price=25.0, score=8.0, label="💎 INSTITUTIONAL")
    positions = await broker.get_positions()
    assert len(positions) == 1
    await broker.check_exits("PLTR", current_price=25.5)  # +2% → TP
    positions = await broker.get_positions()
    assert len(positions) == 0
    stats = broker.get_stats()
    assert stats["total_trades"] == 1
    assert stats["win_rate"] == 100.0
    broker.close()


def test_all_modules_import_without_error():
    import core.state_store
    import core.copilot
    import core.sparkline
    import core.symbol_monitor
    import brokers.base
    import brokers.ghost_broker
    import brokers.alpaca_broker
    import providers.yahoo_provider
