import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import pytest
from core.state_store import CentralStateStore, SymbolState
from core.symbol_monitor import SymbolMonitor


@pytest.fixture(autouse=True)
def reset():
    CentralStateStore.reset()
    yield
    CentralStateStore.reset()


def _sym(symbol: str, **kwargs) -> SymbolState:
    store = CentralStateStore.get()
    store.add_symbol(symbol)
    s = store.get_symbol(symbol)
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def test_turbo_not_triggered_below_threshold():
    monitor = SymbolMonitor()
    state = _sym("AAPL", atr_est=0.5, atr_baseline=0.5, price=100.0, prev_price=99.5)
    monitor.evaluate("AAPL")
    assert not state.is_turbo


def test_turbo_triggered_by_atr_expansion():
    monitor = SymbolMonitor()
    # atr_est > 1.5 × atr_baseline → turbo
    state = _sym("NVDA", atr_est=1.6, atr_baseline=1.0, price=100.0, prev_price=100.0)
    monitor.evaluate("NVDA")
    assert state.is_turbo


def test_turbo_triggered_by_price_move():
    monitor = SymbolMonitor()
    # price moved > 1% in one tick
    state = _sym("TSLA", price=102.0, prev_price=100.0, atr_est=None, atr_baseline=None)
    monitor.evaluate("TSLA")
    assert state.is_turbo


def test_turbo_triggered_by_volume_spike():
    monitor = SymbolMonitor()
    state = _sym("AMD", volume=4_000_000, avg_volume=1_000_000, price=50.0, prev_price=50.0, atr_est=None, atr_baseline=None)
    monitor.evaluate("AMD")
    assert state.is_turbo


def test_turbo_triggered_by_high_copilot_score():
    monitor = SymbolMonitor()
    state = _sym("META", copilot_score=7.0, price=500.0, prev_price=500.0, atr_est=None, atr_baseline=None)
    monitor.evaluate("META")
    assert state.is_turbo


def test_turbo_timer_resets_on_retrigger():
    monitor = SymbolMonitor()
    state = _sym("PLTR", price=26.0, prev_price=25.0, atr_est=None, atr_baseline=None)
    monitor.evaluate("PLTR")
    first_until = state.turbo_until
    time.sleep(0.01)
    monitor.evaluate("PLTR")  # re-trigger
    assert state.turbo_until >= first_until


def test_turbo_expires_after_time():
    monitor = SymbolMonitor()
    state = _sym("SMCI", price=102.0, prev_price=100.0, atr_est=None, atr_baseline=None)
    monitor.evaluate("SMCI")
    assert state.is_turbo
    # Manually expire
    state.turbo_until = time.time() - 1
    state.prev_price = state.price  # reset so no re-trigger
    monitor.clear_expired()
    assert not state.is_turbo


def test_atr_baseline_snapshot_updated():
    monitor = SymbolMonitor()
    state = _sym("GOOGL", atr_est=1.0, atr_baseline=None)
    monitor.take_baseline_snapshot()
    assert state.atr_baseline == 1.0
