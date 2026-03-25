import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from core.state_store import CentralStateStore, SymbolState
from core.copilot import CopilotEngine


@pytest.fixture(autouse=True)
def reset():
    CentralStateStore.reset()
    yield
    CentralStateStore.reset()


_make_state_counter = 0


def _make_state(**kwargs) -> SymbolState:
    global _make_state_counter
    _make_state_counter += 1
    key = f"TEST_{_make_state_counter}"
    store = CentralStateStore.get()
    store.add_symbol(key)
    s = store.get_symbol(key)
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def test_market_closed_returns_zero_and_closed_label():
    engine = CopilotEngine()
    state = _make_state(market_open=False, pct_change=5.0)
    score, label = engine.score(state, spy_state=None)
    assert score == 0.0
    assert "CLOSED" in label


def test_rs_divergence_adds_three():
    engine = CopilotEngine()
    state = _make_state(market_open=True, pct_change=1.0, avg_volume=0.0)
    spy = _make_state(pct_change=-0.5)
    spy.symbol = "SPY"
    score, _ = engine.score(state, spy_state=spy)
    assert score >= 3.0


def test_rs_divergence_and_acceleration_are_mutually_exclusive():
    """Divergence (+3) blocks acceleration (+2) — not both."""
    engine = CopilotEngine()
    state = _make_state(market_open=True, pct_change=2.0, avg_volume=0.0)
    spy = _make_state(pct_change=-0.5)
    spy.symbol = "SPY"
    score, _ = engine.score(state, spy_state=spy)
    # Max from RS alone should be 3 (divergence only)
    assert score <= 3.0 + 0.001  # no volume bonus, no vwap


def test_volume_spike_3x_adds_three():
    engine = CopilotEngine()
    state = _make_state(market_open=True, pct_change=0.0, volume=3_000_000, avg_volume=1_000_000)
    score, _ = engine.score(state, spy_state=None)
    assert score >= 3.0


def test_volume_spike_2x_adds_two_not_three():
    engine = CopilotEngine()
    state = _make_state(market_open=True, pct_change=0.0, volume=2_100_000, avg_volume=1_000_000)
    score, _ = engine.score(state, spy_state=None)
    # 2.1x → +2. NOT +3
    assert abs(score - 2.0) < 0.01


def test_vwap_above_adds_two():
    engine = CopilotEngine()
    state = _make_state(market_open=True, price=100.0, vwap=95.0, avg_volume=0.0)
    score, _ = engine.score(state, spy_state=None)
    assert score >= 2.0


def test_vwap_below_subtracts_two():
    engine = CopilotEngine()
    state = _make_state(market_open=True, price=90.0, vwap=95.0, avg_volume=0.0)
    score, _ = engine.score(state, spy_state=None)
    assert score <= -2.0


def test_rsi_none_skipped_in_scoring():
    engine = CopilotEngine()
    state = _make_state(market_open=True, rsi=None, avg_volume=0.0)
    # Should not error and score should exclude RSI component
    score, _ = engine.score(state, spy_state=None)
    assert isinstance(score, float)


def test_rsi_extreme_overbought_penalizes():
    engine = CopilotEngine()
    state = _make_state(market_open=True, rsi=88.0, avg_volume=0.0)
    score, _ = engine.score(state, spy_state=None)
    assert score <= -4.0


def test_score_clamped_at_positive_ten():
    engine = CopilotEngine()
    # Max possible: RS divergence +3, volume 3x +3, VWAP above +2, RSI 60 +2, count vel +1, trend +1 = +12
    state = _make_state(
        market_open=True, pct_change=2.0, volume=4_000_000, avg_volume=1_000_000,
        price=100.0, vwap=95.0, rsi=62.0, count_velocity_5m=5,
        session_low=90.0,  # price above session low (trend alignment)
    )
    spy = _make_state(pct_change=-0.5)
    score, _ = engine.score(state, spy_state=spy)
    assert score == 10.0


def test_score_clamped_at_negative_ten():
    engine = CopilotEngine()
    state = _make_state(
        market_open=True, price=80.0, vwap=95.0, rsi=88.0, avg_volume=0.0
    )
    score, _ = engine.score(state, spy_state=None)
    assert score >= -10.0


def test_label_institutional_for_high_score():
    engine = CopilotEngine()
    state = _make_state(
        market_open=True, pct_change=2.0, volume=4_000_000, avg_volume=1_000_000,
        price=100.0, vwap=95.0, rsi=62.0, count_velocity_5m=5, session_low=90.0,
    )
    spy = _make_state(pct_change=-0.5)
    _, label = engine.score(state, spy_state=spy)
    assert "INSTITUTIONAL" in label or "BREAKOUT" in label


def test_label_liquidity_trap_for_low_score():
    engine = CopilotEngine()
    state = _make_state(market_open=True, price=80.0, vwap=95.0, rsi=88.0, avg_volume=0.0)
    _, label = engine.score(state, spy_state=None)
    assert "WEAK" in label or "TRAP" in label
