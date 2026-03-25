import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import time
import pytest
from core.state_store import CentralStateStore, SymbolState


@pytest.fixture(autouse=True)
def reset_store():
    """Each test gets a fresh singleton."""
    CentralStateStore.reset()
    yield
    CentralStateStore.reset()


def test_add_symbol_creates_state():
    store = CentralStateStore.get()
    state = store.add_symbol("AAPL")
    assert isinstance(state, SymbolState)
    assert state.symbol == "AAPL"
    assert state.price == 0.0
    assert state.warmup_ticks == 0


def test_get_singleton():
    a = CentralStateStore.get()
    b = CentralStateStore.get()
    assert a is b


def test_add_symbol_idempotent():
    store = CentralStateStore.get()
    s1 = store.add_symbol("TSLA")
    s2 = store.add_symbol("TSLA")
    assert s1 is s2


def test_update_price_increments_warmup():
    store = CentralStateStore.get()
    store.add_symbol("NVDA")
    store.update_price("NVDA", 100.0)
    state = store.get_symbol("NVDA")
    assert state.warmup_ticks == 1
    assert state.price == 100.0


def test_update_price_tracks_session_high_low():
    store = CentralStateStore.get()
    store.add_symbol("SPY")
    store.update_price("SPY", 500.0)
    store.update_price("SPY", 510.0)
    store.update_price("SPY", 495.0)
    state = store.get_symbol("SPY")
    assert state.session_high == 510.0
    assert state.session_low == 495.0


def test_pct_change_computed_correctly():
    store = CentralStateStore.get()
    store.add_symbol("MSFT")
    store.update_price("MSFT", 100.0)
    store.update_price("MSFT", 102.0)
    state = store.get_symbol("MSFT")
    assert abs(state.pct_change - 2.0) < 0.001


def test_velocity_5m_computed_after_5_ticks():
    store = CentralStateStore.get()
    store.add_symbol("AMD")
    for p in [100.0, 101.0, 102.0, 103.0, 110.0]:
        store.update_price("AMD", p)
    state = store.get_symbol("AMD")
    # velocity = (110 - 100) / 100 * 100 = 10%
    assert abs(state.price_velocity_5m - 10.0) < 0.01


def test_remove_symbol():
    store = CentralStateStore.get()
    store.add_symbol("INTC")
    store.remove_symbol("INTC")
    assert store.get_symbol("INTC") is None


def test_snapshot_is_shallow_copy():
    store = CentralStateStore.get()
    store.add_symbol("META")
    snap1 = store.snapshot()
    store.update_price("META", 500.0)
    snap2 = store.snapshot()
    # Snapshot is a dict copy — same state objects but the dict is independent
    assert "META" in snap1
    assert snap1["META"].price == 500.0  # state objects are shared (by design)


def test_atr_est_initialized_after_two_ticks():
    store = CentralStateStore.get()
    store.add_symbol("PLTR")
    store.update_price("PLTR", 25.0)
    assert store.get_symbol("PLTR").atr_est is None  # need prev_price
    store.update_price("PLTR", 25.5)
    assert store.get_symbol("PLTR").atr_est is not None
