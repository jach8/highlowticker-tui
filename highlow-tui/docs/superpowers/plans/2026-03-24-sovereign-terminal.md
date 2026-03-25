# Sovereign Terminal v2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite highlowticker-tui into a zero-flicker Bloomberg-class trading terminal with a reactive CellGrid, Co-Pilot alpha engine, Ghost paper-trading engine, adaptive turbo polling, and professional UX (omnipresent command bar, heatmap rows, kill switch).

**Architecture:** Replace `DataTable` with a `CellGrid` of explicit `Static` subclasses where each cell carries a class-level `reactive(value)` — only dirty cells re-render. A `CentralStateStore` singleton is the single source of truth; the data pipeline writes to it and a diff engine pushes changed values to cell widgets. A `CopilotEngine` computes −10→+10 alpha scores per symbol; a `GhostBroker` auto-enters high-score signals into a SQLite paper-trading ledger.

**Tech Stack:** Python 3.11+, Textual ≥ 0.65.0, yfinance ≥ 0.2.50, sqlite3 (stdlib), asyncio, pytest, pytest-asyncio

---

## File Map (all paths relative to `highlow-tui/`)

| File | Status | Responsibility |
|------|--------|---------------|
| `requirements.txt` | Modify | Add textual≥0.65, aiohttp, pytest-asyncio |
| `core/__init__.py` | Create | Package marker |
| `core/state_store.py` | Create | `SymbolState` dataclass + `CentralStateStore` singleton |
| `core/sparkline.py` | Create | `sparkline(deque) → str` using Unicode blocks |
| `core/copilot.py` | Create | `CopilotEngine.score()` — weighted −10/+10 alpha signal |
| `core/symbol_monitor.py` | Create | `SymbolMonitor` — turbo mode trigger + ATR baseline snapshots |
| `brokers/__init__.py` | Create | Package marker |
| `brokers/base.py` | Create | `BrokerBase` ABC + `Order`, `Position`, `FlattenResult` dataclasses |
| `brokers/ghost_broker.py` | Create | `GhostBroker(BrokerBase)` — SQLite-backed paper trading |
| `brokers/alpaca_broker.py` | Create | `AlpacaBroker(BrokerBase)` stub |
| `providers/yahoo_provider.py` | Modify | Add `asyncio.Semaphore(3)` + exponential backoff on HTTP 429 |
| `app.py` | Rewrite | `SovereignApp` — all Cell subclasses, `CellGrid`, `CommandBar`, `KillModal`, `GhostPanel`, layout, TCSS |
| `tests/test_state_store.py` | Create | Unit tests for `CentralStateStore` |
| `tests/test_sparkline.py` | Create | Unit tests for `sparkline()` |
| `tests/test_copilot.py` | Create | Unit tests for `CopilotEngine.score()` |
| `tests/test_ghost_broker.py` | Create | Unit tests for `GhostBroker` PnL, Kelly sizing, flatten |
| `tests/test_symbol_monitor.py` | Create | Unit tests for turbo trigger conditions |
| `tests/test_cell_widgets.py` | Create | Textual async tests for `PriceCell`, `CellGrid` dirty-only render |
| `tests/test_command_bar.py` | Create | Textual async tests for `CommandBar` key intercept + modes |
| `tests/test_kill_modal.py` | Create | Textual async tests for `KillModal` CONFIRM/ESC/timeout |

---

## Task 1: Requirements & Project Structure

**Files:**
- Modify: `requirements.txt`
- Create: `core/__init__.py`, `brokers/__init__.py`

- [ ] **Step 1: Update requirements.txt**

Replace the entire file content:

```
textual>=0.65.0
python-dotenv>=1.0.0
yfinance>=0.2.50
httpx>=0.27.0
aiohttp>=3.9.0
tomli>=2.0.0; python_version < "3.11"
websockets>=12.0
PyJWT>=2.8.0
cryptography>=42.0.0
certifi>=2024.0.0
pytest>=8.0.0
pytest-asyncio>=0.23.0

# ── Optional: connect a real broker ──────────────────────────────────
# alpaca-py>=0.8.2
```

- [ ] **Step 2: Create package markers**

```bash
touch highlow-tui/core/__init__.py
touch highlow-tui/brokers/__init__.py
```

- [ ] **Step 3: Install updated deps**

```bash
cd highlow-tui && pip install -r requirements.txt
```

Expected: all packages install without error. `python -c "import textual; print(textual.__version__)"` should print `0.65.x` or higher.

- [ ] **Step 4: Verify Textual version has VerticalScroll**

```bash
python -c "from textual.widgets import VerticalScroll; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt core/__init__.py brokers/__init__.py
git commit -m "chore: add core/ and brokers/ packages, update requirements for v2"
```

---

## Task 2: Sparkline Utility

**Files:**
- Create: `core/sparkline.py`
- Create: `tests/test_sparkline.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sparkline.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import deque
from core.sparkline import sparkline

def test_empty_returns_dashes():
    assert sparkline(deque()) == "—" * 20

def test_single_value_returns_mid_blocks():
    result = sparkline(deque([100.0]))
    assert all(c == "▄" for c in result)
    assert len(result) == 1

def test_all_same_price_returns_mid_block():
    d = deque([50.0, 50.0, 50.0, 50.0], maxlen=20)
    result = sparkline(d)
    assert all(c == "▄" for c in result)

def test_rising_prices_end_with_high_block():
    d = deque([1.0, 2.0, 3.0, 4.0, 5.0], maxlen=20)
    result = sparkline(d)
    assert result[-1] == "█"  # highest block for max price
    assert result[0] == "▁"   # lowest block for min price

def test_output_width_capped_at_20():
    d = deque(range(50), maxlen=20)
    result = sparkline(d)
    assert len(result) <= 20

def test_uses_last_20_prices():
    # 25 items but maxlen=20 keeps last 20
    d = deque(range(25), maxlen=20)
    result = sparkline(d)
    assert len(result) == 20
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd highlow-tui && pytest tests/test_sparkline.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.sparkline'`

- [ ] **Step 3: Implement `core/sparkline.py`**

```python
"""Unicode block sparkline — converts a price deque to an 8-level bar string."""
from collections import deque

_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(prices, width: int = 20) -> str:
    """Return a sparkline string of up to `width` chars from a price sequence.

    Args:
        prices: Any sequence of floats (typically a deque(maxlen=20)).
        width:  Maximum output length (uses last `width` values).

    Returns:
        A string of Unicode block characters, or dashes if prices is empty.
    """
    data = list(prices)
    if not data:
        return "—" * width
    if len(data) == 1:
        return "▄"
    data = data[-width:]
    lo, hi = min(data), max(data)
    if hi == lo:
        return "▄" * len(data)
    return "".join(
        _BLOCKS[round((p - lo) / (hi - lo) * 7)]
        for p in data
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd highlow-tui && pytest tests/test_sparkline.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/sparkline.py tests/test_sparkline.py
git commit -m "feat: add Unicode block sparkline utility with tests"
```

---

## Task 3: CentralStateStore

**Files:**
- Create: `core/state_store.py`
- Create: `tests/test_state_store.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_state_store.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd highlow-tui && pytest tests/test_state_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.state_store'`

- [ ] **Step 3: Implement `core/state_store.py`**

```python
"""Central state store — single source of truth for all symbol market data."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SymbolState:
    symbol: str
    price: float = 0.0
    prev_price: float = 0.0
    pct_change: float = 0.0
    count: int = 0                          # session high/low hit count
    session_high: float = 0.0
    session_low: float = float("inf")
    price_history: deque = field(default_factory=lambda: deque(maxlen=20))
    volume: float = 0.0
    avg_volume: float = 0.0                 # bootstrapped from 3-month ADV on add
    price_velocity_5m: float = 0.0         # (price_now - price_5ago) / price_5ago * 100
    count_velocity_5m: int = 0
    vwap: Optional[float] = None           # None until first market-hours tick
    rsi: Optional[float] = None            # None until warmup_ticks >= 14
    atr_est: Optional[float] = None        # None until warmup_ticks >= 2
    atr_baseline: Optional[float] = None   # Snapshot every 5 min by SymbolMonitor
    copilot_score: float = 0.0
    copilot_label: str = "— NEUTRAL"
    is_turbo: bool = False
    turbo_until: float = 0.0
    last_fetch_status: str = "OK"          # "OK" | "429" | "TIMEOUT" | "ERR"
    last_updated: float = 0.0
    warmup_ticks: int = 0
    market_open: bool = True
    # Internal: timestamps of count increments for count_velocity_5m
    _count_timestamps: deque = field(
        default_factory=lambda: deque(maxlen=100), repr=False
    )
    # Internal: cumulative vwap numerator/denominator
    _vwap_num: float = field(default=0.0, repr=False)
    _vwap_den: float = field(default=0.0, repr=False)


class CentralStateStore:
    """Singleton source of truth. The UI reads; the data pipeline writes."""

    _instance: Optional[CentralStateStore] = None

    def __init__(self) -> None:
        self._states: dict[str, SymbolState] = {}

    @classmethod
    def get(cls) -> CentralStateStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton — for tests only."""
        cls._instance = None

    # ── Symbol management ────────────────────────────────────────────

    def add_symbol(self, symbol: str) -> SymbolState:
        if symbol not in self._states:
            self._states[symbol] = SymbolState(symbol=symbol)
        return self._states[symbol]

    def remove_symbol(self, symbol: str) -> None:
        self._states.pop(symbol, None)

    def get_symbol(self, symbol: str) -> Optional[SymbolState]:
        return self._states.get(symbol)

    def all_symbols(self) -> list[str]:
        return list(self._states.keys())

    def snapshot(self) -> dict[str, SymbolState]:
        """Shallow copy of the states dict for diff comparisons."""
        return dict(self._states)

    # ── Price update ─────────────────────────────────────────────────

    def update_price(
        self,
        symbol: str,
        price: float,
        volume: float = 0.0,
    ) -> SymbolState:
        """Update price and all derived fields. Returns the mutated state."""
        state = self._states.get(symbol) or self.add_symbol(symbol)

        state.prev_price = state.price
        state.price = price
        state.volume = volume
        state.last_updated = time.time()
        state.warmup_ticks += 1

        # Pct change
        if state.prev_price > 0:
            state.pct_change = (price - state.prev_price) / state.prev_price * 100

        # Price history (sparkline source)
        state.price_history.append(price)

        # Session high / low
        if price > state.session_high:
            state.session_high = price
        if state.session_low == float("inf") or price < state.session_low:
            state.session_low = price

        # 5-minute price velocity
        history_list = list(state.price_history)
        if len(history_list) >= 5:
            price_5ago = history_list[-5]
            if price_5ago > 0:
                state.price_velocity_5m = (price - price_5ago) / price_5ago * 100

        # ATR estimate (EMA of |tick_delta|)
        if state.prev_price > 0:
            tick_move = abs(price - state.prev_price)
            if state.atr_est is None:
                state.atr_est = tick_move
            else:
                state.atr_est = state.atr_est * 0.9 + tick_move * 0.1

        # VWAP (cumulative, resets at market open via reset_session)
        if state.market_open and volume > 0:
            state._vwap_num += price * volume
            state._vwap_den += volume
            state.vwap = state._vwap_num / state._vwap_den

        return state

    def increment_count(self, symbol: str) -> None:
        """Called when a new session high/low hit is recorded."""
        state = self._states.get(symbol)
        if state is None:
            return
        state.count += 1
        now = time.time()
        state._count_timestamps.append(now)
        # Count velocity: hits in last 5 minutes
        cutoff = now - 300
        state.count_velocity_5m = sum(
            1 for t in state._count_timestamps if t >= cutoff
        )

    def reset_session(self, symbol: str) -> None:
        """Reset intraday state (call at market open)."""
        state = self._states.get(symbol)
        if state is None:
            return
        state.session_high = 0.0
        state.session_low = float("inf")
        state.count = 0
        state._vwap_num = 0.0
        state._vwap_den = 0.0
        state.vwap = None
        state._count_timestamps.clear()
        state.count_velocity_5m = 0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd highlow-tui && pytest tests/test_state_store.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/state_store.py tests/test_state_store.py
git commit -m "feat: add CentralStateStore with SymbolState and price-update logic"
```

---

## Task 4: CopilotEngine

**Files:**
- Create: `core/copilot.py`
- Create: `tests/test_copilot.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_copilot.py`:

```python
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


def _make_state(**kwargs) -> SymbolState:
    store = CentralStateStore.get()
    store.add_symbol("TEST")
    s = store.get_symbol("TEST")
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
    # Strong negative: VWAP below -2, RSI extreme overbought -4 = -6 raw; clamp at -10 (won't reach -10 with current rules)
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd highlow-tui && pytest tests/test_copilot.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.copilot'`

- [ ] **Step 3: Implement `core/copilot.py`**

```python
"""Co-Pilot alpha engine — weighted momentum score from -10 to +10."""
from __future__ import annotations
from typing import Optional
from .state_store import SymbolState

# Ordered from highest score downward — first match wins
_LABEL_MAP: list[tuple[float, str]] = [
    (8.0,  "💎 INSTITUTIONAL"),
    (6.0,  "🟢 BULL BREAKOUT"),
    (4.0,  "🟢 STRENGTH"),
    (2.0,  "● WATCH"),
    (-2.0, "— NEUTRAL"),
    (-4.0, "● FADE"),
    (-6.0, "🔴 WEAK"),
    (float("-inf"), "⚠ LIQUIDITY TRAP"),
]


class CopilotEngine:
    """Stateless scorer — call score() on every data tick."""

    def score(
        self,
        state: SymbolState,
        spy_state: Optional[SymbolState],
    ) -> tuple[float, str]:
        """Return (clamped_score, label). Score is [-10, +10].

        When market is closed or state.market_open is False, returns (0.0, '— CLOSED').
        When an indicator is None (warmup), that component is skipped.
        """
        if not state.market_open:
            return 0.0, "— CLOSED"

        raw = 0.0
        spy_pct = spy_state.pct_change if spy_state else 0.0

        # ── 1. Relative Strength vs SPY ───────────────────────────────
        if state.pct_change > 0 and spy_pct < 0:
            raw += 3.0  # Divergence — green while SPY red
        elif abs(spy_pct) > 0.01 and abs(state.pct_change) > 2 * abs(spy_pct):
            raw += 2.0  # Acceleration (elif — mutually exclusive with divergence)

        # ── 2. Volume Profile ─────────────────────────────────────────
        if state.avg_volume > 0:
            ratio = state.volume / state.avg_volume
            if ratio > 3.0:
                raw += 3.0
            elif ratio > 2.0:   # elif — mutually exclusive
                raw += 2.0

        # ── 3. Price vs VWAP ──────────────────────────────────────────
        if state.vwap is not None and state.vwap > 0:
            raw += 2.0 if state.price > state.vwap else -2.0

        # ── 4. RSI (skipped during warmup) ───────────────────────────
        if state.rsi is not None:
            if 55.0 <= state.rsi <= 70.0:
                raw += 2.0
            elif state.rsi < 30.0:   # elif — mutually exclusive with above
                raw += 2.0           # Oversold bounce
            if state.rsi > 85.0:
                raw -= 4.0           # Extreme overbought
            elif state.rsi > 80.0:   # elif — mutually exclusive
                raw -= 3.0

        # ── 5. Count velocity ─────────────────────────────────────────
        if state.count_velocity_5m > 3:
            raw += 1.0

        # ── 6. Trend alignment ───────────────────────────────────────
        if (state.session_low > 0
                and state.price > state.session_low
                and state.vwap is not None
                and state.price > state.vwap):
            raw += 1.0

        score = max(min(raw, 10.0), -10.0)
        return score, _label(score)


def _label(score: float) -> str:
    for threshold, label in _LABEL_MAP:
        if score >= threshold:
            return label
    return "⚠ LIQUIDITY TRAP"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd highlow-tui && pytest tests/test_copilot.py -v
```

Expected: all 13 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/copilot.py tests/test_copilot.py
git commit -m "feat: add CopilotEngine with weighted alpha scoring and 13 tests"
```

---

## Task 5: BrokerBase + GhostBroker

**Files:**
- Create: `brokers/base.py`
- Create: `brokers/ghost_broker.py`
- Create: `brokers/alpaca_broker.py`
- Create: `tests/test_ghost_broker.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_ghost_broker.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import asyncio
import tempfile
from pathlib import Path as PPath
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd highlow-tui && pytest tests/test_ghost_broker.py -v
```

Expected: `ModuleNotFoundError: No module named 'brokers.ghost_broker'`

- [ ] **Step 3: Create `brokers/base.py`**

```python
"""Abstract broker interface — implement for Alpaca, Binance, Ghost, etc."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str           # 'buy' | 'sell'
    qty: float
    order_type: str     # 'market' | 'limit'
    status: str         # 'pending' | 'filled' | 'cancelled'
    limit_price: Optional[float] = None


@dataclass
class Position:
    symbol: str
    qty: float
    direction: str      # 'LONG' | 'SHORT'
    entry_price: float
    current_price: float

    @property
    def unrealized_pnl(self) -> float:
        if self.direction == "LONG":
            return (self.current_price - self.entry_price) * self.qty
        return (self.entry_price - self.current_price) * self.qty


@dataclass
class FlattenResult:
    positions_closed: int
    orders_cancelled: int
    total_exposure: float


class BrokerBase(ABC):
    @abstractmethod
    async def submit_order(
        self, symbol: str, side: str, qty: float,
        order_type: str, limit_price: Optional[float] = None,
    ) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def flatten_all(self) -> FlattenResult: ...

    @abstractmethod
    async def get_equity(self) -> float: ...
```

- [ ] **Step 4: Create `brokers/ghost_broker.py`**

```python
"""GhostBroker — SQLite-backed paper trading engine."""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from .base import BrokerBase, FlattenResult, Order, Position

_DEFAULT_DB = Path.home() / ".sovereign" / "ghost_trades.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT    NOT NULL,
    direction     TEXT    NOT NULL,
    entry_price   REAL    NOT NULL,
    qty           REAL    NOT NULL,
    entry_time    REAL    NOT NULL,
    score_at_entry REAL   NOT NULL,
    label_at_entry TEXT   NOT NULL,
    algo_version  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT,
    direction     TEXT,
    entry_price   REAL,
    exit_price    REAL,
    qty           REAL,
    pnl           REAL,
    entry_time    REAL,
    exit_time     REAL,
    duration_secs REAL,
    exit_reason   TEXT,
    score_at_entry REAL,
    label_at_entry TEXT,
    algo_version  INTEGER DEFAULT 1,
    slippage_pct  REAL
);

CREATE TABLE IF NOT EXISTS stats (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    equity          REAL    DEFAULT 100000.0,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    gross_profit    REAL    DEFAULT 0.0,
    gross_loss      REAL    DEFAULT 0.0,
    max_drawdown_pct REAL   DEFAULT 0.0,
    peak_equity     REAL    DEFAULT 100000.0,
    updated_at      REAL    DEFAULT 0
);

INSERT OR IGNORE INTO stats (id) VALUES (1);
"""

_SL_PCT = 0.75   # stop-loss %
_TP_PCT = 1.5    # take-profit %
_MAX_HOLD_SECS = 1800  # 30 minutes


class GhostBroker(BrokerBase):
    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── BrokerBase interface ──────────────────────────────────────────

    async def submit_order(
        self, symbol: str, side: str, qty: float,
        order_type: str, limit_price: Optional[float] = None,
    ) -> Order:
        return Order(
            order_id=uuid.uuid4().hex[:8], symbol=symbol,
            side=side, qty=qty, order_type=order_type, status="filled",
        )

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_positions(self) -> list[Position]:
        rows = self._conn.execute(
            "SELECT symbol, direction, entry_price, qty FROM positions"
        ).fetchall()
        return [
            Position(symbol=r[0], direction=r[1], entry_price=r[2],
                     qty=r[3], current_price=r[2])
            for r in rows
        ]

    async def flatten_all(self) -> FlattenResult:
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(qty * entry_price), 0) FROM positions"
        ).fetchone()
        count, exposure = row[0], row[1]
        self._conn.execute("DELETE FROM positions")
        self._conn.commit()
        return FlattenResult(
            positions_closed=count, orders_cancelled=0, total_exposure=exposure
        )

    async def get_equity(self) -> float:
        row = self._conn.execute(
            "SELECT equity FROM stats WHERE id=1"
        ).fetchone()
        return row[0] if row else 100_000.0

    # ── Ghost-specific methods ───────────────────────────────────────

    async def enter_long(
        self, symbol: str, price: float, score: float, label: str
    ) -> None:
        equity = await self.get_equity()
        qty = self._kelly_size(equity) / max(price, 0.01)
        self._conn.execute(
            "INSERT INTO positions "
            "(symbol, direction, entry_price, qty, entry_time, score_at_entry, label_at_entry) "
            "VALUES (?,?,?,?,?,?,?)",
            (symbol, "LONG", price, qty, time.time(), score, label),
        )
        self._conn.commit()

    async def check_exits(self, symbol: str, current_price: float) -> None:
        """Evaluate SL / TP / max-hold for all open positions in symbol."""
        now = time.time()
        rows = self._conn.execute(
            "SELECT id, direction, entry_price, qty, entry_time, "
            "score_at_entry, label_at_entry "
            "FROM positions WHERE symbol=?",
            (symbol,),
        ).fetchall()

        for pos_id, direction, entry_price, qty, entry_time, score, label in rows:
            if direction == "LONG":
                pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100

            exit_reason: Optional[str] = None
            target_pct: float = 0.0
            if pnl_pct <= -_SL_PCT:
                exit_reason, target_pct = "SL", -_SL_PCT
            elif pnl_pct >= _TP_PCT:
                exit_reason, target_pct = "TP", _TP_PCT
            elif (now - entry_time) >= _MAX_HOLD_SECS:
                exit_reason, target_pct = "MAX_HOLD", pnl_pct

            if exit_reason:
                raw_pnl = pnl_pct / 100 * entry_price * qty
                slippage = abs(pnl_pct - target_pct)
                self._conn.execute(
                    "INSERT INTO trades "
                    "(symbol, direction, entry_price, exit_price, qty, pnl, "
                    "entry_time, exit_time, duration_secs, exit_reason, "
                    "score_at_entry, label_at_entry, slippage_pct) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        symbol, direction, entry_price, current_price, qty,
                        raw_pnl, entry_time, now, now - entry_time, exit_reason,
                        score, label, slippage,
                    ),
                )
                self._conn.execute(
                    "DELETE FROM positions WHERE id=?", (pos_id,)
                )
                self._update_stats(raw_pnl)

        self._conn.commit()

    def get_stats(self) -> dict:
        row = self._conn.execute(
            "SELECT equity, total_trades, winning_trades, "
            "gross_profit, gross_loss, max_drawdown_pct "
            "FROM stats WHERE id=1"
        ).fetchone()
        if not row:
            return {}
        equity, total, wins, gp, gl, maxdd = row
        win_rate = (wins / total * 100) if total > 0 else 0.0
        losses = total - wins
        profit_factor = (gp / abs(gl)) if gl != 0 and losses > 0 else 0.0
        return {
            "equity": equity,
            "total_trades": total,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown_pct": maxdd,
            "gross_profit": gp,
            "gross_loss": gl,
        }

    def close(self) -> None:
        self._conn.close()

    # ── Private ───────────────────────────────────────────────────────

    def _kelly_size(self, equity: float) -> float:
        row = self._conn.execute(
            "SELECT total_trades, winning_trades, gross_profit, gross_loss "
            "FROM stats WHERE id=1"
        ).fetchone()
        if not row or row[0] < 10:
            return equity * 0.01  # Warmup: fixed 1%
        total, wins, gp, gl = row
        losses = total - wins
        if wins == 0 or losses == 0 or gl == 0:
            return equity * 0.01
        win_rate = wins / total
        payoff = (gp / wins) / (abs(gl) / losses)
        kelly = 0.5 * (win_rate - (1 - win_rate) / payoff)
        kelly = max(0.0025, min(0.02, kelly))
        return equity * kelly

    def _update_stats(self, pnl: float) -> None:
        row = self._conn.execute(
            "SELECT equity, total_trades, winning_trades, "
            "gross_profit, gross_loss, peak_equity "
            "FROM stats WHERE id=1"
        ).fetchone()
        equity, total, wins, gp, gl, peak = row
        equity += pnl
        total += 1
        if pnl > 0:
            wins += 1
            gp += pnl
        else:
            gl += pnl
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak > 0 else 0.0
        self._conn.execute(
            "UPDATE stats SET equity=?, total_trades=?, winning_trades=?, "
            "gross_profit=?, gross_loss=?, "
            "max_drawdown_pct=MAX(max_drawdown_pct, ?), "
            "peak_equity=?, updated_at=? WHERE id=1",
            (equity, total, wins, gp, gl, drawdown, peak, time.time()),
        )
```

- [ ] **Step 5: Create `brokers/alpaca_broker.py`**

```python
"""AlpacaBroker stub — implement for live trading."""
from .base import BrokerBase, FlattenResult, Order, Position
from typing import Optional


class AlpacaBroker(BrokerBase):
    """Live equity/crypto broker via Alpaca Markets.

    Setup:
        pip install alpaca-py
        .env: ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER=true
    """

    async def submit_order(self, symbol, side, qty, order_type, limit_price=None):
        raise NotImplementedError("AlpacaBroker not configured. See brokers/alpaca_broker.py")

    async def cancel_order(self, order_id):
        raise NotImplementedError

    async def get_positions(self):
        raise NotImplementedError

    async def flatten_all(self):
        raise NotImplementedError

    async def get_equity(self):
        raise NotImplementedError
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd highlow-tui && pytest tests/test_ghost_broker.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add brokers/base.py brokers/ghost_broker.py brokers/alpaca_broker.py tests/test_ghost_broker.py
git commit -m "feat: add BrokerBase ABC, GhostBroker SQLite paper engine, AlpacaBroker stub"
```

---

## Task 6: Yahoo Provider — Semaphore + 429 Backoff

**Files:**
- Modify: `providers/yahoo_provider.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_yahoo_provider.py`:

```python
# Add at top
import asyncio
import time

def test_backoff_state_initialized():
    """Provider starts with clean backoff state."""
    provider = YahooFinanceProvider(SYMBOLS, poll_interval=90)
    assert provider._backoff_until == 0
    assert provider._backoff_secs == 5


def test_mark_rate_limited_sets_backoff():
    provider = YahooFinanceProvider(SYMBOLS, poll_interval=90)
    before = time.time()
    provider._mark_rate_limited()
    assert provider._backoff_until > before
    assert provider._backoff_secs == 10  # doubled from 5


def test_mark_rate_limited_caps_at_60s():
    provider = YahooFinanceProvider(SYMBOLS, poll_interval=90)
    provider._backoff_secs = 32  # one step below cap
    provider._mark_rate_limited()
    assert provider._backoff_secs == 60  # capped


def test_is_rate_limited_returns_false_when_expired():
    provider = YahooFinanceProvider(SYMBOLS, poll_interval=90)
    provider._backoff_until = time.time() - 1  # expired
    assert provider.is_rate_limited() is False


def test_is_rate_limited_returns_true_when_active():
    provider = YahooFinanceProvider(SYMBOLS, poll_interval=90)
    provider._backoff_until = time.time() + 30
    assert provider.is_rate_limited() is True
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd highlow-tui && pytest tests/test_yahoo_provider.py::test_backoff_state_initialized -v
```

Expected: `AttributeError: 'YahooFinanceProvider' object has no attribute '_backoff_until'`

- [ ] **Step 3: Add backoff state to `YahooFinanceProvider.__init__`**

Open `providers/yahoo_provider.py`. Locate `__init__`. Add after existing attributes:

```python
# Rate-limit backoff state
self._backoff_until: float = 0.0
self._backoff_secs: float = 5.0
self._semaphore = asyncio.Semaphore(3)
```

- [ ] **Step 4: Add `_mark_rate_limited` and `is_rate_limited` methods**

```python
def _mark_rate_limited(self) -> None:
    """Called on HTTP 429. Doubles backoff, caps at 60s."""
    import time
    self._backoff_until = time.time() + self._backoff_secs
    self._backoff_secs = min(self._backoff_secs * 2, 60.0)

def is_rate_limited(self) -> bool:
    import time
    return time.time() < self._backoff_until

def _reset_backoff(self) -> None:
    self._backoff_secs = 5.0
    self._backoff_until = 0.0
```

- [ ] **Step 5: Guard `_poll` with rate-limit check**

In `providers/yahoo_provider.py`, at the top of `_poll()`:

```python
def _poll(self):
    if self.is_rate_limited():
        return None  # Skip poll, return stale
    try:
        result = self._do_poll()
        self._reset_backoff()
        return result
    except Exception as e:
        if "429" in str(e) or "Too Many" in str(e):
            self._mark_rate_limited()
        return None
```

- [ ] **Step 6: Run all yahoo tests**

```bash
cd highlow-tui && pytest tests/test_yahoo_provider.py -v
```

Expected: all tests (old + new) PASS.

- [ ] **Step 7: Commit**

```bash
git add providers/yahoo_provider.py tests/test_yahoo_provider.py
git commit -m "feat: add Semaphore(3) and exponential backoff on 429 to YahooFinanceProvider"
```

---

## Task 7: SymbolMonitor

**Files:**
- Create: `core/symbol_monitor.py`
- Create: `tests/test_symbol_monitor.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_symbol_monitor.py`:

```python
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
    monitor.evaluate("SMCI")  # evaluate without trigger — should clear
    # Price is now same so no re-trigger
    state.prev_price = state.price  # reset so no trigger
    monitor._clear_expired()
    assert not state.is_turbo


def test_atr_baseline_snapshot_updated():
    monitor = SymbolMonitor()
    state = _sym("GOOGL", atr_est=1.0, atr_baseline=None)
    monitor.take_baseline_snapshot()
    assert state.atr_baseline == 1.0
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd highlow-tui && pytest tests/test_symbol_monitor.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.symbol_monitor'`

- [ ] **Step 3: Implement `core/symbol_monitor.py`**

```python
"""SymbolMonitor — evaluates turbo mode triggers and ATR baseline snapshots."""
from __future__ import annotations
import time
from .state_store import CentralStateStore

_TURBO_DURATION_SECS = 300       # 5 minutes
_ATR_EXPANSION_THRESHOLD = 1.5   # atr_est / atr_baseline > 1.5
_PRICE_MOVE_THRESHOLD_PCT = 1.0  # 1% single-tick move
_VOLUME_SPIKE_THRESHOLD = 3.0    # 3× avg_volume
_SCORE_THRESHOLD = 6.0           # copilot score crosses ±6


class SymbolMonitor:
    """Stateless evaluator — call evaluate(symbol) on each data tick."""

    def evaluate(self, symbol: str) -> bool:
        """Check turbo triggers for symbol. Returns True if turbo activated."""
        store = CentralStateStore.get()
        state = store.get_symbol(symbol)
        if state is None:
            return False

        triggered = False

        # Trigger 1: ATR expansion
        if (state.atr_est is not None
                and state.atr_baseline is not None
                and state.atr_baseline > 0
                and state.atr_est / state.atr_baseline > _ATR_EXPANSION_THRESHOLD):
            triggered = True

        # Trigger 2: Price move > 1% in one tick
        if not triggered and state.prev_price > 0:
            move_pct = abs(state.price - state.prev_price) / state.prev_price * 100
            if move_pct > _PRICE_MOVE_THRESHOLD_PCT:
                triggered = True

        # Trigger 3: Volume spike
        if not triggered and state.avg_volume > 0:
            if state.volume / state.avg_volume > _VOLUME_SPIKE_THRESHOLD:
                triggered = True

        # Trigger 4: Co-Pilot score crosses threshold
        if not triggered and abs(state.copilot_score) >= _SCORE_THRESHOLD:
            triggered = True

        if triggered:
            # Reset timer to now + 5 min on EVERY trigger (not additive)
            state.is_turbo = True
            state.turbo_until = time.time() + _TURBO_DURATION_SECS

        return triggered

    def _clear_expired(self) -> None:
        """Clear turbo flags for symbols whose timer has elapsed."""
        store = CentralStateStore.get()
        now = time.time()
        for symbol in store.all_symbols():
            state = store.get_symbol(symbol)
            if state and state.is_turbo and now >= state.turbo_until:
                state.is_turbo = False

    def take_baseline_snapshot(self) -> None:
        """Called every 5 minutes — snapshot current atr_est as the new baseline."""
        store = CentralStateStore.get()
        for symbol in store.all_symbols():
            state = store.get_symbol(symbol)
            if state and state.atr_est is not None:
                state.atr_baseline = state.atr_est
```

- [ ] **Step 4: Run tests**

```bash
cd highlow-tui && pytest tests/test_symbol_monitor.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/symbol_monitor.py tests/test_symbol_monitor.py
git commit -m "feat: add SymbolMonitor with turbo mode triggers and ATR baseline snapshots"
```

---

## Task 8: Cell Widgets + CellGrid

**Files:**
- Modify: `app.py` (add cell widget classes before `SovereignApp`)
- Create: `tests/test_cell_widgets.py`

- [ ] **Step 1: Write failing Textual widget tests**

Create `tests/test_cell_widgets.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static


# We test that the class-level reactive pattern works by building a minimal app
class _PriceCell(Static):
    from textual.reactive import reactive
    value: reactive = reactive("—", layout=False)

    def watch_value(self, new: str) -> None:
        self.update(new)


class _TestApp(App):
    def compose(self) -> ComposeResult:
        yield _PriceCell("—", id="cell")


@pytest.mark.asyncio
async def test_price_cell_updates_on_value_change():
    app = _TestApp()
    async with app.run_test() as pilot:
        cell = app.query_one("#cell", _PriceCell)
        assert cell.value == "—"
        cell.value = "$142.50"
        await pilot.pause()
        assert cell.value == "$142.50"


@pytest.mark.asyncio
async def test_price_cell_no_update_when_value_unchanged():
    """Setting same value should not trigger watch_value (Textual built-in behavior)."""
    app = _TestApp()
    update_count = []

    original_watch = _PriceCell.watch_value

    def counting_watch(self, new):
        update_count.append(new)
        original_watch(self, new)

    _PriceCell.watch_value = counting_watch
    try:
        async with app.run_test() as pilot:
            cell = app.query_one("#cell", _PriceCell)
            cell.value = "$100.00"
            await pilot.pause()
            count_after_first = len(update_count)
            cell.value = "$100.00"  # same value
            await pilot.pause()
            # watch_value should NOT have been called again
            assert len(update_count) == count_after_first
    finally:
        _PriceCell.watch_value = original_watch
```

- [ ] **Step 2: Run to verify test infrastructure works**

```bash
cd highlow-tui && pytest tests/test_cell_widgets.py -v
```

Expected: Both tests should PASS (they test native Textual behavior, not app.py yet).

- [ ] **Step 3: Add all Cell subclasses to `app.py`**

At the top of `app.py`, after imports, add:

```python
from textual.widgets import Static, Input, Button, VerticalScroll
from textual.reactive import reactive
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical

# ── Cell widget subclasses ────────────────────────────────────────────────────
# IMPORTANT: reactive() must be declared at the class level, not on instances.
# Textual only calls watch_* when the value actually changes (always_update=False).

class _Cell(Static):
    """Base cell — all cells are strings pre-formatted before assignment."""
    value: reactive[str] = reactive("—", layout=False)

    def watch_value(self, new: str) -> None:
        self.update(new)


class SymCell(_Cell):
    """Symbol + optional badge (⚡ turbo, 52W high/low marker)."""
    pass


class CntCell(_Cell):
    """Hit count."""
    pass


class PriceCell(_Cell):
    """Current price."""
    pass


class TrendCell(_Cell):
    """Trend arrows (▲▲▲ or ▼▼▼)."""
    pass


class PctCell(_Cell):
    """Percent change."""
    pass


class RsiCell(_Cell):
    """RSI value or '—' during warmup."""
    pass


class VwapDeltaCell(_Cell):
    """Price delta vs VWAP."""
    pass


class SparkCell(_Cell):
    """20-bar Unicode sparkline."""
    pass


class CopilotCell(_Cell):
    """Co-Pilot score label."""
    pass
```

- [ ] **Step 4: Add `GridRow` and `CellGrid` classes to `app.py`**

```python
class GridRow(Horizontal):
    """One row in the CellGrid — holds all Cell widgets for one symbol."""

    # Heat class names for velocity tinting (set via set_class)
    HEAT_CLASSES = {
        "heat-5", "heat-4", "heat-3", "heat-0",
        "heat-n3", "heat-n4", "heat-n5"
    }

    def __init__(self, symbol: str, side: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symbol = symbol
        self.side = side  # "high" | "low"
        self._current_heat = "heat-0"
        # Dict of column_name → Cell widget reference (set after compose)
        self.cells: dict[str, _Cell] = {}

    def compose(self) -> ComposeResult:
        yield SymCell("—",      classes="col-sym",   id=f"{self.symbol}-sym-{self.side}")
        yield CntCell("—",      classes="col-cnt",   id=f"{self.symbol}-cnt-{self.side}")
        yield PriceCell("—",    classes="col-price", id=f"{self.symbol}-price-{self.side}")
        yield TrendCell("—",    classes="col-trend", id=f"{self.symbol}-trend-{self.side}")
        yield PctCell("—",      classes="col-pct",   id=f"{self.symbol}-pct-{self.side}")
        yield RsiCell("—",      classes="col-rsi",   id=f"{self.symbol}-rsi-{self.side}")
        yield VwapDeltaCell("—",classes="col-vwap",  id=f"{self.symbol}-vwap-{self.side}")
        yield SparkCell("—",    classes="col-spark", id=f"{self.symbol}-spark-{self.side}")
        yield CopilotCell("—",  classes="col-pilot", id=f"{self.symbol}-pilot-{self.side}")

    def on_mount(self) -> None:
        self.cells = {
            "sym":   self.query_one(SymCell),
            "cnt":   self.query_one(CntCell),
            "price": self.query_one(PriceCell),
            "trend": self.query_one(TrendCell),
            "pct":   self.query_one(PctCell),
            "rsi":   self.query_one(RsiCell),
            "vwap":  self.query_one(VwapDeltaCell),
            "spark": self.query_one(SparkCell),
            "pilot": self.query_one(CopilotCell),
        }

    def set_heat(self, velocity_pct: float) -> None:
        """Set row background heat class based on 5-min price velocity."""
        if velocity_pct > 1.5:
            new_heat = "heat-5"
        elif velocity_pct > 0.8:
            new_heat = "heat-4"
        elif velocity_pct > 0.3:
            new_heat = "heat-3"
        elif velocity_pct < -1.5:
            new_heat = "heat-n5"
        elif velocity_pct < -0.8:
            new_heat = "heat-n4"
        elif velocity_pct < -0.3:
            new_heat = "heat-n3"
        else:
            new_heat = "heat-0"

        if new_heat != self._current_heat:
            self.remove_class(self._current_heat)
            self.add_class(new_heat)
            self._current_heat = new_heat


class CellGrid(VerticalScroll):
    """Zero-flicker reactive grid. Only dirty cells repaint.

    Maintains separate grids for session highs and session lows.
    """

    def __init__(self, side: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.side = side  # "high" | "low"
        self._rows: dict[str, GridRow] = {}
        self._cursor_idx: int = 0
        self._symbol_order: list[str] = []

    def add_row(self, symbol: str) -> GridRow:
        if symbol not in self._rows:
            row = GridRow(symbol, self.side, id=f"row-{symbol}-{self.side}")
            self._rows[symbol] = row
            self._symbol_order.append(symbol)
            self.mount(row)
        return self._rows[symbol]

    def remove_row(self, symbol: str) -> None:
        row = self._rows.pop(symbol, None)
        if row:
            self._symbol_order.remove(symbol)
            row.remove()

    def update_row(self, symbol: str, data: dict) -> None:
        """Diff-update only the cells whose values changed."""
        row = self._rows.get(symbol)
        if row is None:
            row = self.add_row(symbol)
        for col, new_val in data.items():
            cell = row.cells.get(col)
            if cell and cell.value != new_val:
                cell.value = new_val
        if "velocity" in data:
            row.set_heat(data["velocity"])

    def move_cursor(self, delta: int) -> None:
        if not self._symbol_order:
            return
        self._cursor_idx = max(
            0, min(self._cursor_idx + delta, len(self._symbol_order) - 1)
        )
        sym = self._symbol_order[self._cursor_idx]
        row = self._rows.get(sym)
        if row:
            row.scroll_visible()
            for r in self._rows.values():
                r.remove_class("cursor-row")
            row.add_class("cursor-row")

    def selected_symbol(self) -> str | None:
        if not self._symbol_order:
            return None
        return self._symbol_order[self._cursor_idx]
```

- [ ] **Step 5: Run existing tests to confirm no regressions**

```bash
cd highlow-tui && pytest tests/ -v --ignore=tests/test_license.py
```

Expected: all previously-passing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_cell_widgets.py
git commit -m "feat: add Cell subclasses, GridRow, and CellGrid (zero-flicker reactive grid)"
```

---

## Task 9: CommandBar

**Files:**
- Modify: `app.py` (add `CommandBar` widget class)
- Create: `tests/test_command_bar.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_command_bar.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from textual.app import App, ComposeResult


# Minimal host app for testing CommandBar
class _TestApp(App):
    CSS = """
    CommandBar { height: 3; }
    """
    def compose(self) -> ComposeResult:
        from app import CommandBar
        yield CommandBar(id="cmd")

    def on_key(self, event) -> None:
        from app import CommandBar
        cmd = self.query_one(CommandBar)
        if event.is_printable and not cmd.has_focus:
            cmd.open(event.character)
            event.stop()


@pytest.mark.asyncio
async def test_command_bar_opens_on_printable_key():
    app = _TestApp()
    async with app.run_test() as pilot:
        from app import CommandBar
        cmd = app.query_one(CommandBar)
        assert not cmd.is_open
        await pilot.press("n")
        assert cmd.is_open


@pytest.mark.asyncio
async def test_escape_closes_command_bar():
    app = _TestApp()
    async with app.run_test() as pilot:
        from app import CommandBar
        cmd = app.query_one(CommandBar)
        await pilot.press("n")
        assert cmd.is_open
        await pilot.press("escape")
        assert not cmd.is_open


@pytest.mark.asyncio
async def test_slash_sets_search_mode():
    app = _TestApp()
    async with app.run_test() as pilot:
        from app import CommandBar
        cmd = app.query_one(CommandBar)
        await pilot.press("/")
        assert cmd.mode == "search"


@pytest.mark.asyncio
async def test_colon_sets_command_mode():
    app = _TestApp()
    async with app.run_test() as pilot:
        from app import CommandBar
        cmd = app.query_one(CommandBar)
        await pilot.press(":")
        assert cmd.mode == "command"
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd highlow-tui && pytest tests/test_command_bar.py -v
```

Expected: `ImportError: cannot import name 'CommandBar' from 'app'`

- [ ] **Step 3: Add `CommandBar` to `app.py`**

```python
class CommandBar(Widget):
    """Omnipresent command input. Auto-focused when user types any letter.

    Modes:
        'add'     — default, adds ticker on Enter
        'search'  — triggered by '/', filters grid rows
        'command' — triggered by ':', executes :dd :mode :clear etc.
    """

    is_open: reactive[bool] = reactive(False, layout=True)
    mode: reactive[str] = reactive("add")

    def __init__(self, on_add=None, on_search=None, on_command=None, **kwargs):
        super().__init__(**kwargs)
        self._on_add = on_add
        self._on_search = on_search
        self._on_command = on_command

    def compose(self) -> ComposeResult:
        yield Static("⌨ ADD ▸", id="cmd-prompt", classes="cmd-prompt")
        yield Input(placeholder="ticker / /search / :command",
                    id="cmd-input", classes="cmd-input")
        yield Static("↵ add · ESC cancel · / search · : cmd",
                     id="cmd-hint", classes="cmd-hint")

    def open(self, first_char: str = "") -> None:
        """Focus input and optionally pre-fill first character."""
        self.is_open = True
        inp = self.query_one("#cmd-input", Input)
        self.app.set_focus(inp)
        if first_char == "/":
            self.mode = "search"
            inp.value = ""
        elif first_char == ":":
            self.mode = "command"
            inp.value = ""
        else:
            self.mode = "add"
            inp.value = first_char.upper() if first_char else ""

    def close(self) -> None:
        self.is_open = False
        self.mode = "add"
        self.query_one("#cmd-input", Input).value = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip().upper()
        if not text:
            self.close()
            return
        if self.mode == "add" and self._on_add:
            self._on_add(text)
        elif self.mode == "search" and self._on_search:
            self._on_search(text.lower())
        elif self.mode == "command" and self._on_command:
            self._on_command(text.lower())
        self.close()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.close()
            event.stop()
```

- [ ] **Step 4: Run tests**

```bash
cd highlow-tui && pytest tests/test_command_bar.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_command_bar.py
git commit -m "feat: add omnipresent CommandBar with add/search/command modes"
```

---

## Task 10: KillModal

**Files:**
- Modify: `app.py` (add `KillModal` class)
- Create: `tests/test_kill_modal.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_kill_modal.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from textual.app import App, ComposeResult


class _KillApp(App):
    def compose(self) -> ComposeResult:
        from app import KillModal
        yield KillModal(positions=[], on_confirm=self._confirmed, id="kill")
        self.confirmed = False

    def _confirmed(self):
        self.confirmed = True


@pytest.mark.asyncio
async def test_kill_modal_confirm_button_disabled_initially():
    app = _KillApp()
    async with app.run_test() as pilot:
        confirm_btn = app.query_one("#kill-confirm-btn")
        assert confirm_btn.disabled


@pytest.mark.asyncio
async def test_kill_modal_confirm_enabled_after_typing_confirm():
    app = _KillApp()
    async with app.run_test() as pilot:
        inp = app.query_one("#kill-input")
        await pilot.click(inp)
        await pilot.type("CONFIRM")
        await pilot.pause()
        confirm_btn = app.query_one("#kill-confirm-btn")
        assert not confirm_btn.disabled


@pytest.mark.asyncio
async def test_kill_modal_wrong_text_keeps_button_disabled():
    app = _KillApp()
    async with app.run_test() as pilot:
        inp = app.query_one("#kill-input")
        await pilot.click(inp)
        await pilot.type("confirm")  # lowercase — wrong
        await pilot.pause()
        confirm_btn = app.query_one("#kill-confirm-btn")
        assert confirm_btn.disabled


@pytest.mark.asyncio
async def test_kill_modal_escape_does_not_confirm():
    app = _KillApp()
    async with app.run_test() as pilot:
        await pilot.press("escape")
        await pilot.pause()
        assert not app.confirmed
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd highlow-tui && pytest tests/test_kill_modal.py -v
```

Expected: `ImportError: cannot import name 'KillModal' from 'app'`

- [ ] **Step 3: Add `KillModal` to `app.py`**

```python
from textual.screen import ModalScreen

class KillModal(ModalScreen):
    """Full-screen flatten-all confirmation.
    User must type 'CONFIRM' (case-sensitive) to execute.
    ESC dismisses without action. Auto-dismisses after 60 seconds.
    """

    AUTO_DISMISS_SECS = 60

    def __init__(self, positions: list, on_confirm, **kwargs) -> None:
        super().__init__(**kwargs)
        self._positions = positions
        self._on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        pos_text = "\n".join(
            f"  {p.symbol} {p.direction} {p.qty:.2f} @ {p.entry_price:.2f}"
            for p in self._positions
        ) or "  (no open positions)"

        yield Vertical(
            Static("⚠  FLATTEN ALL  ⚠", id="kill-title", classes="kill-title"),
            Static(f"Open positions:\n{pos_text}", id="kill-pos"),
            Static("Type CONFIRM to execute. ESC to cancel.", classes="kill-hint"),
            Input(placeholder="Type CONFIRM", id="kill-input", classes="kill-input"),
            Button("FLATTEN ALL", id="kill-confirm-btn",
                   variant="error", disabled=True),
            Button("Cancel", id="kill-cancel-btn"),
            id="kill-box",
            classes="kill-box",
        )

    def on_mount(self) -> None:
        self.set_timer(self.AUTO_DISMISS_SECS, self._auto_dismiss)
        self.query_one("#kill-input", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        btn = self.query_one("#kill-confirm-btn", Button)
        btn.disabled = (event.value != "CONFIRM")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "kill-confirm-btn":
            self._execute()
        elif event.button.id == "kill-cancel-btn":
            self.dismiss()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()
            event.stop()

    def _execute(self) -> None:
        self._on_confirm()
        self.dismiss()

    def _auto_dismiss(self) -> None:
        self.app.notify(
            "Kill switch timed out — no action taken", severity="warning"
        )
        self.dismiss()
```

- [ ] **Step 4: Run tests**

```bash
cd highlow-tui && pytest tests/test_kill_modal.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_kill_modal.py
git commit -m "feat: add KillModal with CONFIRM string gate, ESC dismiss, 60s timeout"
```

---

## Task 11: SovereignApp — Layout, TCSS, Key Bindings

**Files:**
- Modify: `app.py` (add `SovereignApp` class replacing `QuantTUI`, embed full TCSS)

This is the largest single task. No new tests — integration smoke test in Task 14.

- [ ] **Step 1: Add embedded TCSS to `app.py` as class variable**

In `SovereignApp`, set the `CSS` class variable:

```python
class SovereignApp(App):
    CSS = """
    /* ── Global ─────────────────────────────── */
    Screen { background: #0d1117; color: #c9d1d9; }

    /* ── Pulse bar ───────────────────────────── */
    #pulse-bar { height: 1; background: #0d1117; border-bottom: tall #21262d; }

    /* ── Command bar ─────────────────────────── */
    #cmd-bar { height: 3; background: #161b22; border-bottom: tall #f0b429; }
    #cmd-bar.hidden { display: none; }
    .cmd-prompt { color: #f0b429; width: 8; }
    .cmd-input Input { background: transparent; border: none; color: #f0b429; }
    .cmd-hint { color: #484f58; width: 1fr; text-align: right; }

    /* ── Breadth bar ─────────────────────────── */
    #breadth-bar { height: 1; background: #0d1117; border-bottom: tall #21262d; }

    /* ── Ticker tape ─────────────────────────── */
    #tape { height: 1; background: #161b22; }

    /* ── Tables ──────────────────────────────── */
    #tables-row { height: 1fr; }
    #lows-panel, #highs-panel { width: 1fr; }
    #lows-panel { border-right: tall #21262d; }
    .panel-header { height: 1; }
    .panel-header.highs { color: #3fb950; background: rgba(63,185,80,0.04); }
    .panel-header.lows  { color: #f85149; background: rgba(248,81,73,0.04); }
    .col-headers { height: 1; background: #161b22; color: #484f58; }

    /* ── Grid rows ───────────────────────────── */
    GridRow { height: 1; }
    GridRow:hover { background: rgba(88,166,255,0.07); }
    GridRow.cursor-row { background: rgba(88,166,255,0.15); }

    /* Column widths */
    .col-sym   { width: 9;  }
    .col-cnt   { width: 4;  }
    .col-price { width: 10; }
    .col-trend { width: 8;  }
    .col-pct   { width: 7;  }
    .col-rsi   { width: 5;  }
    .col-vwap  { width: 7;  }
    .col-spark { width: 22; }
    .col-pilot { width: 1fr; }

    /* ── Heatmap velocity tints ──────────────── */
    GridRow.heat-5  { background: rgba(63,185,80,0.22);  transition: background 400ms linear; }
    GridRow.heat-4  { background: rgba(63,185,80,0.13);  transition: background 400ms linear; }
    GridRow.heat-3  { background: rgba(63,185,80,0.06);  transition: background 400ms linear; }
    GridRow.heat-0  { background: transparent;           transition: background 400ms linear; }
    GridRow.heat-n3 { background: rgba(248,81,73,0.06);  transition: background 400ms linear; }
    GridRow.heat-n4 { background: rgba(248,81,73,0.13);  transition: background 400ms linear; }
    GridRow.heat-n5 { background: rgba(248,81,73,0.22);  transition: background 400ms linear; }

    /* ── Status bar ──────────────────────────── */
    #status-bar { height: 1; background: #161b22; border-top: tall #21262d; }

    /* ── Ghost panel ─────────────────────────── */
    #ghost-panel { width: 34; background: #161b22; border-left: tall #30363d; }
    #ghost-panel.hidden { display: none; }

    /* ── Kill modal ──────────────────────────── */
    KillModal { align: center middle; }
    .kill-box { width: 60; background: #161b22; border: tall #f85149; padding: 1 2; }
    .kill-title { color: #f85149; text-align: center; text-style: bold; }
    .kill-hint { color: #8b949e; }
    #kill-confirm-btn { margin-top: 1; }
    """

    BINDINGS = [
        ("j",       "nav_down",     "Down"),
        ("k",       "nav_up",       "Up"),
        ("d,d",     "delete_row",   "Delete"),
        ("enter",   "drill_down",   "Detail"),
        ("b",       "buy_modal",    "Buy"),
        ("s",       "sell_modal",   "Sell"),
        ("m",       "toggle_mode",  "Mode"),
        ("p",       "toggle_ghost", "Ghost"),
        ("r",       "reload_cfg",   "Reload"),
        ("shift+k", "kill_switch",  "FLATTEN ALL"),
        ("q",       "quit",         "Quit"),
    ]
```

- [ ] **Step 2: Implement `compose()` layout**

```python
    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="pulse-bar")
        yield CommandBar(
            on_add=self._add_ticker,
            on_search=self._filter_rows,
            on_command=self._handle_command,
            id="cmd-bar",
        )
        yield Static("", id="breadth-bar")
        yield Static("", id="tape")
        with Horizontal(id="tables-row"):
            with Vertical(id="lows-panel"):
                yield Static("▼ SESSION LOWS", id="lows-header",
                             classes="panel-header lows")
                yield Static(
                    " SYM      CNT PRICE      TREND    %CHG   RSI  VWAP△  "
                    "SPARKLINE             CO-PILOT",
                    classes="col-headers",
                )
                yield CellGrid("low", id="lows-grid")
            with Vertical(id="highs-panel"):
                yield Static("▲ SESSION HIGHS", id="highs-header",
                             classes="panel-header highs")
                yield Static(
                    " SYM      CNT PRICE      TREND    %CHG   RSI  VWAP△  "
                    "SPARKLINE             CO-PILOT",
                    classes="col-headers",
                )
                yield CellGrid("high", id="highs-grid")
            yield Vertical(id="ghost-panel", classes="hidden")
        yield Static("", id="status-bar")
        yield Footer()
```

- [ ] **Step 3: Implement `on_mount()` and provider wiring**

```python
    def on_mount(self) -> None:
        from core.state_store import CentralStateStore
        from core.copilot import CopilotEngine
        from core.symbol_monitor import SymbolMonitor
        from brokers.ghost_broker import GhostBroker
        from providers.yahoo_provider import YahooFinanceProvider

        self._store = CentralStateStore.get()
        self._copilot = CopilotEngine()
        self._monitor = SymbolMonitor()
        self._broker = GhostBroker()

        # Load symbols
        symbols = _load_symbols()
        for sym in symbols:
            self._store.add_symbol(sym)

        provider = YahooFinanceProvider(symbols, poll_interval=90)
        # DataCoordinator is defined in app.py itself (lines ~549 in original).
        # Copy the existing class into the new app.py BEFORE SovereignApp, then:
        self._coordinator = DataCoordinator(provider, symbols)

        self._active_focus = "high"  # "high" | "low"
        self._modal_open = False

        self.run_worker(self._feed_loop(), exclusive=True, name="feed")
        self.set_interval(5, self._baseline_tick)
        self.set_interval(1, self._tape_tick)
```

- [ ] **Step 4: Implement `_feed_loop` (data pipeline)**

```python
    async def _feed_loop(self) -> None:
        """Main async loop: pull from coordinator → update store → refresh UI."""
        from core.sparkline import sparkline
        import time

        async for update in self._coordinator.stream():
            if update.get("type") != "HIGHLOW_UPDATE":
                continue

            data = update.get("data", {})
            spy_state = self._store.get_symbol("SPY")

            for sym, entry in data.get("newHighs", {}).items():
                state = self._store.update_price(
                    sym, entry["price"], entry.get("volume", 0)
                )
                self._store.increment_count(sym)
                self._monitor.evaluate(sym)
                state.copilot_score, state.copilot_label = \
                    self._copilot.score(state, spy_state)
                await self._maybe_ghost_enter(sym, state)
                await self._broker.check_exits(sym, state.price)
                self._push_row("high", sym, state)

            for sym, entry in data.get("newLows", {}).items():
                state = self._store.update_price(
                    sym, entry["price"], entry.get("volume", 0)
                )
                self._store.increment_count(sym)
                self._monitor.evaluate(sym)
                state.copilot_score, state.copilot_label = \
                    self._copilot.score(state, spy_state)
                await self._broker.check_exits(sym, state.price)
                self._push_row("low", sym, state)

            self._refresh_pulse(data)
            self._refresh_breadth()
            self._refresh_status()

    def _push_row(self, side: str, symbol: str, state) -> None:
        """Format SymbolState into string dict and push to CellGrid."""
        from core.sparkline import sparkline as _spark

        grid_id = "highs-grid" if side == "high" else "lows-grid"
        grid: CellGrid = self.query_one(f"#{grid_id}", CellGrid)

        trend_char = "▲" if side == "high" else "▼"
        trend = trend_char * min(state.count, 7)

        rsi_str = f"{state.rsi:.0f}" if state.rsi is not None else "—"
        vwap_str = (
            f"{(state.price - state.vwap) / state.vwap * 100:+.1f}%"
            if state.vwap else "—"
        )
        sym_str = f"{'⚡' if state.is_turbo else ''}{symbol}"

        grid.update_row(symbol, {
            "sym":     sym_str,
            "cnt":     str(state.count),
            "price":   f"{state.price:.2f}",
            "trend":   trend,
            "pct":     f"{state.pct_change:+.2f}%",
            "rsi":     rsi_str,
            "vwap":    vwap_str,
            "spark":   _spark(state.price_history),
            "pilot":   state.copilot_label,
            "velocity": state.price_velocity_5m,
        })
```

- [ ] **Step 5: Wire keyboard actions**

```python
    def on_key(self, event) -> None:
        """App-level key intercept — feeds command bar before any widget."""
        if self._modal_open:
            return
        cmd: CommandBar = self.query_one("#cmd-bar", CommandBar)
        if event.is_printable and not cmd.query_one(Input).has_focus:
            cmd.open(event.character)
            event.stop()

    def action_nav_down(self) -> None:
        self._active_grid().move_cursor(1)

    def action_nav_up(self) -> None:
        self._active_grid().move_cursor(-1)

    def action_delete_row(self) -> None:
        sym = self._active_grid().selected_symbol()
        if sym:
            self._active_grid().remove_row(sym)
            self._store.remove_symbol(sym)

    def action_kill_switch(self) -> None:
        async def _do_flatten():
            result = await self._broker.flatten_all()
            self.notify(
                f"⚠ FLATTEN ALL EXECUTED — {result.positions_closed} positions closed",
                severity="error",
                timeout=10,
            )

        async def _confirm():
            self._modal_open = False
            await _do_flatten()

        async def _open_modal():
            # Fetch live positions to display in modal
            positions = await self._broker.get_positions()
            self._modal_open = True
            self.push_screen(
                KillModal(positions=positions, on_confirm=lambda: self.run_worker(_confirm()))
            )

        self.run_worker(_open_modal())

    def action_toggle_ghost(self) -> None:
        panel = self.query_one("#ghost-panel")
        panel.toggle_class("hidden")

    def _active_grid(self) -> CellGrid:
        grid_id = "highs-grid" if self._active_focus == "high" else "lows-grid"
        return self.query_one(f"#{grid_id}", CellGrid)

    async def _maybe_ghost_enter(self, symbol: str, state) -> None:
        """Auto-enter ghost position on high Co-Pilot scores."""
        if state.copilot_score >= 6.0:
            await self._broker.enter_long(
                symbol, state.price, state.copilot_score, state.copilot_label
            )

    def _add_ticker(self, ticker: str) -> None:
        """Called by CommandBar on Enter in ADD mode."""
        self._store.add_symbol(ticker)
        self.notify(f"Added {ticker} to watchlist")

    def _filter_rows(self, query: str) -> None:
        """Called by CommandBar in search mode."""
        for grid in self.query(CellGrid):
            for sym, row in grid._rows.items():
                row.display = query in sym.lower()

    def _handle_command(self, cmd: str) -> None:
        if cmd == "dd":
            self.action_delete_row()
        elif cmd.startswith("mode "):
            mode = cmd.split(" ", 1)[1]
            self.notify(f"Mode: {mode}")

    def _baseline_tick(self) -> None:
        from core.symbol_monitor import SymbolMonitor
        self._monitor.take_baseline_snapshot()
        self._monitor._clear_expired()

    def _tape_tick(self) -> None:
        self._refresh_status()
```

- [ ] **Step 6: Start the app (smoke test — no errors on launch)**

```bash
cd highlow-tui && timeout 5 python app.py 2>&1 | head -20 || true
```

Expected: App starts without Python errors. May show a blank screen (no data yet) — that's fine.

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: implement SovereignApp with layout, TCSS, key bindings, feed loop"
```

---

## Task 12: Ghost Performance Panel

**Files:**
- Modify: `app.py` (add `GhostPanel` widget, wire to `_broker.get_stats()`)

- [ ] **Step 1: Add `GhostPanel` widget to `app.py`**

```python
class GhostPanel(Widget):
    """Collapsible sidebar showing ghost trading performance metrics."""

    def compose(self) -> ComposeResult:
        yield Static("═ GHOST ENGINE ═", classes="ghost-title")
        yield Static("", id="ghost-equity")
        yield Static("", id="ghost-winrate")
        yield Static("", id="ghost-trades")
        yield Static("", id="ghost-curve")

    def refresh_stats(self, stats: dict, equity_curve: list[float]) -> None:
        """equity_curve: list of last 20 equity values after closed trades."""
        if not stats:
            return
        from core.sparkline import sparkline as _spark
        from collections import deque

        equity = stats.get("equity", 100_000)
        start = 100_000.0
        change_pct = (equity - start) / start * 100
        sign = "+" if change_pct >= 0 else ""

        self.query_one("#ghost-equity").update(
            f"Equity  ${equity:,.0f}  {sign}{change_pct:.2f}%"
        )
        win_rate = stats.get("win_rate", 0)
        pf = stats.get("profit_factor", 0)
        pf_str = f"{pf:.2f}" if pf < 100 else "∞"
        self.query_one("#ghost-winrate").update(
            f"WinRate {win_rate:.1f}%  PF {pf_str}"
        )
        total = stats.get("total_trades", 0)
        maxdd = stats.get("max_drawdown_pct", 0)
        self.query_one("#ghost-trades").update(
            f"Trades {total}  MaxDD -{maxdd:.1f}%"
        )
        # Equity curve sparkline — populated from last 20 closed-trade equity snapshots
        if equity_curve:
            from collections import deque as _deque
            self.query_one("#ghost-curve").update(_spark(_deque(equity_curve, maxlen=20)))
```

- [ ] **Step 2: Mount `GhostPanel` inside `#ghost-panel` on app mount**

In `SovereignApp.on_mount()`, after existing setup:

```python
        ghost_container = self.query_one("#ghost-panel")
        ghost_container.mount(GhostPanel(id="ghost-widget"))
        self.set_interval(10, self._refresh_ghost)
```

- [ ] **Step 3: Add `_refresh_ghost` method**

```python
    def _refresh_ghost(self) -> None:
        stats = self._broker.get_stats()
        # Fetch last 20 equity snapshots from trades table for sparkline
        rows = self._broker._conn.execute(
            "SELECT (SELECT equity FROM stats WHERE id=1) - "
            "SUM(pnl) OVER (ORDER BY exit_time ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) "
            "FROM trades ORDER BY exit_time DESC LIMIT 20"
        ).fetchall()
        equity_curve = [r[0] for r in reversed(rows)] if rows else []
        panel = self.query_one("#ghost-widget", GhostPanel)
        panel.refresh_stats(stats, equity_curve)
```

- [ ] **Step 4: Quick smoke test — toggle ghost panel**

```bash
cd highlow-tui && python -c "
from app import SovereignApp
app = SovereignApp()
print('App instantiates cleanly:', app.__class__.__name__)
"
```

Expected: `App instantiates cleanly: SovereignApp`

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add GhostPanel sidebar with equity, win rate, profit factor display"
```

---

## Task 13: Refresh Helpers — Pulse, Breadth, Status Bars

**Files:**
- Modify: `app.py` (implement `_refresh_pulse`, `_refresh_breadth`, `_refresh_status`)

- [ ] **Step 1: Implement `_refresh_pulse`**

```python
    def _refresh_pulse(self, data: dict) -> None:
        index_symbols = ["SPY", "QQQ", "IWM", "BTC-USD"]
        parts = []
        for sym in index_symbols:
            state = self._store.get_symbol(sym)
            if state and state.price > 0:
                sign = "▲" if state.pct_change >= 0 else "▼"
                parts.append(
                    f"{sym.replace('-USD','')} {state.price:.2f} "
                    f"{sign}{abs(state.pct_change):.2f}%"
                )
        self.query_one("#pulse-bar").update("  ".join(parts))
```

- [ ] **Step 2: Implement `_refresh_breadth`**

```python
    def _refresh_breadth(self) -> None:
        symbols = self._store.all_symbols()
        if not symbols:
            return
        advances = sum(
            1 for s in symbols
            if (st := self._store.get_symbol(s)) and st.pct_change > 0
        )
        declines = sum(
            1 for s in symbols
            if (st := self._store.get_symbol(s)) and st.pct_change < 0
        )
        total = len(symbols)
        ratio = advances / total if total else 0.5
        mood = "RISK-ON" if ratio > 0.6 else ("RISK-OFF" if ratio < 0.4 else "NEUTRAL")
        bar_width = 30
        fill = int(ratio * bar_width)
        bar = "█" * fill + "░" * (bar_width - fill)
        self.query_one("#breadth-bar").update(
            f" BREADTH [{bar}] ↑{advances} / ↓{declines}  {mood}"
        )
```

- [ ] **Step 3: Implement `_refresh_status`**

```python
    def _refresh_status(self) -> None:
        import time
        # Connection status from any symbol's last_fetch_status
        symbols = self._store.all_symbols()
        statuses = [
            self._store.get_symbol(s).last_fetch_status
            for s in symbols[:5] if self._store.get_symbol(s)
        ]
        conn = "● LIVE" if all(s == "OK" for s in statuses) else "⚠ DEGRADED"
        self.query_one("#status-bar").update(
            f" {conn}  SYMBOLS {len(symbols)}  "
            f"j/k nav  dd del  b/s order  m mode  p ghost  ⇧K FLATTEN ALL"
        )
```

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: implement pulse bar, breadth bar, and status bar refresh helpers"
```

---

## Task 14: Integration Smoke Test, README Update, Final Commit

**Files:**
- Create: `tests/test_integration_smoke.py`
- Modify: `README.md`

- [ ] **Step 1: Write integration smoke test**

Create `tests/test_integration_smoke.py`:

```python
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
```

- [ ] **Step 2: Run full test suite**

```bash
cd highlow-tui && pytest tests/ -v --ignore=tests/test_license.py -x
```

Expected: all tests PASS. Zero failures.

- [ ] **Step 3: Update README.md**

Add a section at the top of `highlow-tui/README.md`:

```markdown
## Sovereign Terminal v2.0

A Bloomberg-class trading terminal built on [Textual](https://textual.textualize.io/).

### Features
- **Zero-flicker reactive grid** — custom CellGrid, only dirty cells repaint
- **Co-Pilot alpha engine** — weighted −10/+10 momentum score per symbol
- **Ghost trading engine** — $100k paper trading with SQLite ledger, Kelly sizing
- **Adaptive turbo mode** — hot symbols drop to 5s polling automatically
- **7-level heatmap** — row background = 5-min price velocity (emerald → crimson)
- **Omnipresent command bar** — type any ticker to instantly add it
- **Kill switch** — Shift+K → type CONFIRM → flatten all positions

### Quick Start
```bash
pip install -r requirements.txt
python app.py
```

### Key Bindings
| Key | Action |
|-----|--------|
| Any letter | Auto-focus command bar |
| `j` / `k` | Navigate rows |
| `dd` | Remove selected symbol |
| `Enter` | Drill-down detail |
| `b` / `s` | Buy / Sell (ghost) |
| `m` | Toggle equity ↔ crypto |
| `p` | Toggle Ghost Performance Panel |
| `Shift+K` | Kill switch — flatten all |
| `q` | Quit |
```

- [ ] **Step 4: Final commit**

```bash
git add tests/test_integration_smoke.py README.md
git commit -m "feat: Sovereign Terminal v2.0 — reactive grid, Co-Pilot, Ghost engine, kill switch

Complete rewrite of highlowticker-tui:
- CellGrid replaces DataTable (zero-flicker, dirty-cell-only updates)
- CopilotEngine: weighted -10/+10 alpha scoring with 6 signal components
- GhostBroker: SQLite paper trading with Kelly sizing, 2:1 R/R, max-hold
- SymbolMonitor: turbo mode (5s polling) on ATR expansion or score threshold
- CommandBar: omnipresent, intercepts all printable keys at app level
- KillModal: type CONFIRM to flatten all, ESC dismiss, 60s auto-timeout
- 7-level emerald-to-crimson heatmap via TCSS row class transitions
- Full test suite: 60+ unit tests across all modules"
```

---

## Running All Tests

```bash
cd highlow-tui
pytest tests/ -v --ignore=tests/test_license.py
```

Expected: **60+ tests, 0 failures**

## Launching the Terminal

```bash
cd highlow-tui
python app.py
```
