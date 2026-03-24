# Sovereign Terminal v2.0 — Design Specification

**Date:** 2026-03-24
**Status:** Approved (v2 — post spec-review)
**Architect:** Principal Quant / Lead TUI Designer
**Approved Approach:** A — Reactive CellGrid Engine

---

## 1. Executive Summary

A total architectural evolution of `highlowticker-tui` into a **Sovereign Trading Terminal** — a Bloomberg-class Python TUI that provides total situational awareness for real-time equity and crypto markets. The terminal generates actionable alpha signals via a weighted Co-Pilot engine and runs a Ghost (paper) trading engine that proves the Co-Pilot's edge in real time.

**Deliverable:** A Python package under `highlow-tui/` with `app.py` as the entry point and TCSS embedded as the `CSS` class variable on the App. Run with `python app.py`.

---

## 2. Architecture

### 2.1 Reactive CellGrid Engine (Approach A)

Replace the existing `DataTable` entirely with a custom `CellGrid` widget. The root cause of all "glitchy" behavior is that `DataTable.update_cell()` triggers internal row reflow even for single-cell changes. The new system uses **explicit `Static` subclasses** with Textual `reactive()` properties declared at the class level — only the exact cell that changed re-renders.

**Critical implementation note:** `reactive()` descriptors must be declared at the class level, not on instances. Each cell type is its own subclass:

```python
class PriceCell(Static):
    value: reactive[str] = reactive("—")
    def watch_value(self, new: str) -> None:
        self.update(new)

class RsiCell(Static):
    value: reactive[str] = reactive("—")
    def watch_value(self, new: str) -> None:
        self.update(new)
# ... one subclass per column type
```

Textual's `reactive` suppresses `watch_*` callbacks when the value does not change (`always_update` defaults to `False`). Do **not** set `always_update=True` on any cell.

**Data flow:**

```
Provider (Yahoo / Coinbase WS)
    ↓ asyncio.Queue (maxsize=20, drop-oldest on overflow)
DataCoordinator  ←→  Semaphore(3) rate-limiter + exponential backoff on HTTP 429
    ↓
SymbolMonitor  (ATR / velocity → Turbo Mode trigger)
    ↓
CentralStateStore  (singleton, pure dict — no Textual reactives at this level)
    ↓  diff engine: new_snap vs prev_snap
CellGrid  →  only dirty Cell widgets receive .value = new_val
    ↓
CopilotEngine  →  score each symbol (clamped −10 → +10)
    ↓
GhostBroker  →  auto-enter signals above threshold, track PnL
```

### 2.2 CentralStateStore

A pure-Python singleton. The UI reads; the data pipeline writes. No Textual reactives at this level (for speed).

```python
@dataclass
class SymbolState:
    symbol: str
    price: float
    prev_price: float
    pct_change: float
    count: int                       # session high/low hit count
    session_high: float              # rolling max since market open
    session_low: float               # rolling min since market open
    price_history: deque             # maxlen=20, 1 entry per poll — for sparkline
    volume: float
    avg_volume: float                # 20-day ADV fetched on symbol add; updated each session
    price_velocity_5m: float         # (price_now - price_5m_ago) / price_5m_ago × 100
    count_velocity_5m: int           # hit count increments in last 5 minutes
    vwap: float                      # cumulative (price×vol) / cumulative_vol since open; None during warmup
    rsi: float | None                # None until 14+ data points accumulated
    atr_est: float | None            # Estimated ATR: mean(abs(price_i - price_{i-1})) over price_history; None until warmup_ticks >= 5
    atr_baseline: float | None       # Snapshot of atr_est taken every 5 min by SymbolMonitor (turbo denominator: atr_est/atr_baseline > 1.5 triggers turbo). Reset to current atr_est on each 5-min snapshot. None until first snapshot.
    copilot_score: float             # clamped to [-10, +10]
    copilot_label: str
    is_turbo: bool
    turbo_until: float               # epoch — reset to now()+300 on each new trigger
    last_fetch_status: str           # Enumerated values: "OK" (success), "429" (rate-limited), "TIMEOUT" (request exceeded 3s), "ERR" (any other exception). Default: "OK". Used to dim cells and show ⚠ in SymCell after 3× poll interval without "OK".
    last_updated: float              # epoch timestamp
    warmup_ticks: int                # ticks since add; indicators disabled until ≥ 14
    market_open: bool                # False = market closed / pre-market; suppresses scoring
```

### 2.3 CellGrid Widget

```
CellGrid (VerticalScroll)              ← NOT ScrollView (removed in Textual ≥0.30)
└── GridRow (Horizontal, one per symbol)
    ├── SymCell(symbol)                class-level reactive: str
    ├── CntCell(count)                 class-level reactive: str
    ├── PriceCell(price)               class-level reactive: str
    ├── TrendCell(trend)               class-level reactive: str
    ├── PctCell(pct)                   class-level reactive: str
    ├── RsiCell(rsi)                   class-level reactive: str
    ├── VwapDeltaCell(delta)           class-level reactive: str
    ├── SparkCell(history)             class-level reactive: str  (pre-rendered string)
    └── CopilotCell(score, label)      class-level reactive: str
```

All reactive values are **strings** (pre-formatted before assignment). This avoids float equality edge cases and keeps `watch_value` as a simple `self.update(new)` with no formatting logic inside the widget.

Heatmap is applied at the **`GridRow` level** via `row.set_class(True, heat_class)` after removing the previous heat class. TCSS handles the visual fade via `transition: background 0.4s;`. No cell content repaint occurs.

### 2.4 Command Bar

`CommandBar` is always rendered in the layout. App-level `on_key` handler fires first:

```python
def on_key(self, event: Key) -> None:
    if self._modal_open:
        return  # modal handles its own input
    if event.is_printable and not self.query_one(CommandBar).has_focus:
        self.query_one(CommandBar).open(event.character)
        event.stop()  # ← prevents key from reaching focused widget
```

`event.stop()` is **required** — without it, the key fires twice (command bar + currently focused widget).

**Modes inside CommandBar:**
- Default (`ADD ▸`): Enter → validate (3s timeout, executor thread) → add; ESC → close
- `/` prefix: Search mode — filters CellGrid rows by substring match
- `:` prefix: Command mode — `:dd` delete, `:mode crypto`, `:clear`, `:export`

**Validation flow:** Fetch single-ticker data with 3s timeout. If timeout/error, show inline error text ("symbol not found") and re-focus input. Do not add unvalidated tickers.

---

## 3. Co-Pilot Alpha Engine

### 3.1 Weighted Scoring System

Score is computed from components, then **clamped to [−10.0, +10.0]**. Components are mutually exclusive where noted to prevent stacking.

| Signal | Rule | Weight |
|--------|------|--------|
| **RS vs SPY — divergence** | ticker_pct > 0 AND spy_pct < 0 | +3 |
| **RS vs SPY — acceleration** | \|ticker_pct\| > 2× \|spy_pct\| (same direction or opposite) | +2 (mutually exclusive with divergence; use `elif`) |
| **Volume — extreme spike** | current_vol > 3× avg_volume_20d | +3 |
| **Volume — moderate spike** | current_vol > 2× avg_volume_20d (elif above) | +2 |
| **VWAP — above** | price > vwap | +2 |
| **VWAP — below** | price < vwap | −2 |
| **RSI — momentum zone** | rsi 55–70 (rising on session high context) | +2 |
| **RSI — oversold bounce** | rsi < 30 (on session low context) | +2 (mutually exclusive with momentum zone) |
| **RSI — overbought** | rsi > 80 | −3 |
| **RSI — extreme overbought** | rsi > 85 | −4 (elif above) |
| **Count velocity** | count_velocity_5m > 3 | +1 |
| **Trend alignment** | price > session open AND price > vwap | +1 |
| **Market closed** | market_open == False | Score = 0 (suppress all) |
| **Warmup** | warmup_ticks < 14 | Omit RSI, ATR components; proceed with others |

**Max possible raw score:** +3 (RS) + 3 (vol) + 2 (VWAP) + 2 (RSI) + 1 (velocity) + 1 (trend) = **+12 → clamped to +10**
**Min possible raw score:** −2 (VWAP) − 4 (RSI) = **−6 → clamped to −6** (floor clamp applied: `max(min(raw, 10), -10)`)

**Score display range:** The Co-Pilot bar widget renders on a **symmetric [−10, +10] axis**. Because the current minimum raw score is −6, the bar will never reach its leftmost extreme under current rules. This is intentional — the terminal is a session-highs/lows scanner; lows already appear in the Lows panel and the Co-Pilot adds context rather than a full bear thesis. If future rules increase negative weights, the bar is already correctly calibrated. Do **not** rescale the bar to [−6, +10].

**Warmup behavior for ALL indicators:** When `warmup_ticks < 14`, any scoring component that depends on a `None`-valued indicator is skipped entirely (not treated as 0). Display "—" in that cell. Applies to: RSI (requires ≥ 14 ticks), `atr_est` (requires ≥ 5 ticks), VWAP (requires market open + ≥ 1 tick since open), `avg_volume` (requires bootstrap fetch to complete). The `CopilotEngine.score()` method must check `is None` before applying any component and skip if None.

### 3.2 Dynamic Labels

| Score (clamped) | Label |
|-----------------|-------|
| ≥ 8.0 | `💎 INSTITUTIONAL` |
| 6.0 – 7.9 | `🟢 BULL BREAKOUT` |
| 4.0 – 5.9 | `🟢 STRENGTH` |
| 2.0 – 3.9 | `● WATCH` |
| > −2.0 – < 2.0 | `— NEUTRAL` |
| −3.9 – −2.0 | `● FADE` |
| −5.9 – −4.0 | `🔴 WEAK` |
| ≤ −6.0 | `⚠ LIQUIDITY TRAP` |

All boundaries use `>=` / `<` consistently (float-safe).

### 3.3 Ghost Auto-Entry Logic

Entry condition: `copilot_score >= 6.0` on a symbol that just printed a session high → Ghost enters LONG.
Entry condition: `copilot_score <= -4.0` on a session low → Ghost enters SHORT.

**Sizing:** Kelly-lite = `0.5 × (win_rate - (1 - win_rate) / payoff_ratio) × equity`.
- Warmup (< 10 closed trades): Fixed 1% of current ghost equity.
- Post-warmup: Kelly fraction, floored at 0.25%, capped at 2%.
- Equity is the **live ghost balance** from SQLite `stats` table, not hardcoded $100k.

**Exit rules (evaluated at each new data tick):**
- Stop loss: 0.75% adverse. **Important:** At 90s polling, SL checks happen at next observed price. Ghost HUD displays "SL±slippage" badge showing actual slippage vs target. This is documented as an approximation.
- Take profit: 1.5% favorable (2:1 R/R).
- Max hold: 30 minutes → market exit at next tick.
- Kill switch → all ghost positions closed at last price, `exit_reason = "KILL_SWITCH"`.

---

## 4. Heatmap System

### 4.1 Velocity Calculation

```python
price_velocity_5m = (price_now - price_5m_ago) / price_5m_ago * 100
# price_5m_ago = price_history[-5] if len(price_history) >= 5 else price_history[0]
```

### 4.2 TCSS Class Mapping

| Class | Velocity | Background |
|-------|----------|------------|
| `heat-5` | > +1.5% | `rgba(63,185,80,0.22)` — emerald |
| `heat-4` | +0.8% to +1.5% | `rgba(63,185,80,0.13)` |
| `heat-3` | +0.3% to +0.8% | `rgba(63,185,80,0.06)` |
| `heat-0` | ±0.3% | transparent |
| `heat-n3` | −0.3% to −0.8% | `rgba(248,81,73,0.06)` |
| `heat-n4` | −0.8% to −1.5% | `rgba(248,81,73,0.13)` |
| `heat-n5` | < −1.5% | `rgba(248,81,73,0.22)` — crimson |

Applied via: `row.set_class(True, new_heat); row.remove_class(old_heat)`. TCSS `transition: background 0.4s linear;` handles visual fade.

---

## 5. Adaptive Polling — SymbolMonitor

`SymbolMonitor` runs as a background asyncio task alongside the main feed loop.

**Turbo Mode triggers (any one):**
- `atr_est` expands > 50% vs `atr_baseline` (5-min baseline snapshot)
- Price moves > 1.0% in a single poll cycle
- Volume > 3× avg_volume
- Co-Pilot score crosses ±6.0

**Turbo behavior:**
- Symbol fetch interval → 5 seconds
- Duration: `turbo_until = now() + 300` — **reset to now()+300 on each new trigger** (not additive)
- `⚡` badge in SymCell
- `DataCoordinator` wraps fetches in `asyncio.Semaphore(3)` — max 3 concurrent per cycle

**Rate limit handling:**
- HTTP 429 response: exponential backoff starting at 5s, doubling to 60s max, then resume normal
- `last_fetch_status` updated to `"429"` during backoff; cell dims via CSS class `stale`
- After 3× normal poll interval with no successful update, SymCell shows `⚠` suffix

**Normal mode:** Batch fetch via `yf.download()`.

---

## 6. Ghost Trading Engine

### 6.1 SQLite Schema

Database: `~/.sovereign/ghost_trades.db`

```sql
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,          -- 'LONG' | 'SHORT'
    entry_price REAL NOT NULL,
    qty REAL NOT NULL,
    entry_time REAL NOT NULL,         -- epoch
    score_at_entry REAL NOT NULL,
    label_at_entry TEXT NOT NULL,
    algo_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL,
    exit_price REAL,
    qty REAL,
    pnl REAL,
    entry_time REAL,
    exit_time REAL,
    duration_secs REAL,
    exit_reason TEXT,                 -- 'SL' | 'TP' | 'MAX_HOLD' | 'KILL_SWITCH' | 'MANUAL'
    score_at_entry REAL,
    label_at_entry TEXT,
    algo_version INTEGER DEFAULT 1,
    slippage_pct REAL                 -- actual exit vs target SL/TP
);

CREATE TABLE stats (
    id INTEGER PRIMARY KEY DEFAULT 1,
    equity REAL DEFAULT 100000.0,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    gross_profit REAL DEFAULT 0.0,
    gross_loss REAL DEFAULT 0.0,
    max_drawdown_pct REAL DEFAULT 0.0,
    peak_equity REAL DEFAULT 100000.0,
    updated_at REAL
);
```

### 6.2 Performance Metrics

- **Win Rate:** `winning_trades / total_trades × 100`
- **Profit Factor:** `gross_profit / abs(gross_loss)` (undefined / shown as "—" until ≥5 losses)
- **Max Drawdown:** `(peak_equity - trough_equity) / peak_equity × 100`
- Equity curve: sparkline from last 20 closed-trade equity values

### 6.3 BrokerBase ABC

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Order:
    order_id: str
    symbol: str
    side: str       # 'buy' | 'sell'
    qty: float
    order_type: str # 'market' | 'limit'
    status: str     # 'pending' | 'filled' | 'cancelled'

@dataclass
class Position:
    symbol: str
    qty: float
    direction: str
    entry_price: float
    current_price: float
    unrealized_pnl: float

@dataclass
class FlattenResult:
    positions_closed: int
    orders_cancelled: int
    total_exposure: float

class BrokerBase(ABC):
    @abstractmethod
    async def submit_order(self, symbol: str, side: str, qty: float,
                           order_type: str, limit_price: float | None = None) -> Order: ...
    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...
    @abstractmethod
    async def get_positions(self) -> list[Position]: ...
    @abstractmethod
    async def flatten_all(self) -> FlattenResult: ...
    @abstractmethod
    async def get_equity(self) -> float: ...
```

`GhostBroker(BrokerBase)` — in-process, SQLite-backed.
`AlpacaBroker(BrokerBase)` — stub that raises `NotImplementedError` with setup link.

---

## 7. Kill Switch — Shift+K

1. `on_key` at App level intercepts `Key("K", shift=True)` regardless of current focus
2. Any open modal is dismissed first
3. `KillModal` mounts full-screen (red overlay, `z-index: 1000`)
4. KillModal displays: open position list, total exposure, warning text
5. Input field accepts text — **disabled until** user types "CONFIRM" (case-sensitive)
6. Confirm button enables only when input value == "CONFIRM" exactly
7. ESC dismisses without action (no flat)
8. 60-second auto-dismiss timeout (toast: "Kill switch timed out — no action taken")
9. On confirm: `broker.flatten_all()` → dismiss modal → `app.notify("⚠ FLATTEN ALL EXECUTED", severity="error", timeout=10)`
10. Ghost positions closed at last price, `exit_reason = "KILL_SWITCH"`

---

## 8. Layout Specification

```
┌─ Header: SOVEREIGN TERMINAL v2.0 — [MODE] — [TIME] ───────────────────┐
│ Pulse Bar: SPY  QQQ  IWM  BTC  VIX  (live prices + % change)         │
│ Command Bar: ⌨ ADD ▸ [input________________] hints  [ESC cancel]     │
│ Breadth: advances/declines bar + mood + heatmap legend + rate counts  │
│ Ticker Tape: scrolling top movers                                     │
├───────────────────────────┬───────────────────────────────────────────┤
│ ▼ SESSION LOWS (N)        │ ▲ SESSION HIGHS (N)                       │
│ SYM CNT PRICE TRD %CHG    │ SYM CNT PRICE TRD %CHG                   │
│     RSI VWAP△ SPARK PILOT │     RSI VWAP△ SPARK PILOT                │
│ [heatmap rows]            │ [heatmap rows]                            │
├───────────────────────────┴───────────────────────────────────────────┤
│ Status: ● YAHOO 87ms │ NEXT 14s │ SYMBOLS 105 │ …keys… │ ⇧K FLATTEN │
└────────────────────────────────────────────────────────────────────────┘
```

**Breadth Bar data sources:**
- Advances: count of tracked symbols with `pct_change > 0`
- Declines: count with `pct_change < 0`
- Mood: "RISK-ON" if advances > 60% of total; "RISK-OFF" if < 40%; "NEUTRAL" otherwise
- Rate counts: cumulative session high/low hits in last 30s / 1m / 5m / 20m windows

**Ghost Performance Panel** (toggle `p`):
```
╔═ GHOST ENGINE ═══════════════╗
║ Equity  $101,240  +1.24%     ║
║ WinRate 62.5%   PF 1.84      ║
║ Trades  16  MaxDD -1.2%      ║
║ ▁▂▃▄▅▆▇█ equity curve (20t) ║
╚══════════════════════════════╝
```

---

## 9. Sparkline Format

```python
BLOCKS = "▁▂▃▄▅▆▇█"  # 8 levels

def sparkline(prices: deque) -> str:
    if len(prices) < 2:
        return "—" * 20
    lo, hi = min(prices), max(prices)
    if hi == lo:
        return "▄" * len(prices)
    return "".join(
        BLOCKS[round((p - lo) / (hi - lo) * 7)]
        for p in prices
    )
```

20 characters wide. Normalized to min/max of the 20-tick window.

---

## 10. Market Hours & Warmup Handling

**Market hours detection:** Check `market_open` flag derived from `exchange_calendars` or a simple time-based check (NYSE: 9:30–16:00 ET Mon–Fri excluding holidays). Set `SymbolState.market_open = False` outside hours.

**During market close:**
- Data polling continues at reduced 5-minute interval
- Co-Pilot scores suppressed (set to 0, label "CLOSED")
- Ghost engine does not enter new positions
- Heatmap shows neutral (heat-0) for all rows

**Indicator warmup (first 14 ticks after symbol add):**
- RSI: display "—"; skip RSI scoring components
- ATR: display "—"; Turbo ATR trigger disabled
- VWAP: display "—" (requires market open + cumulative volume)
- avg_volume: bootstrapped from `yf.Ticker(sym).fast_info['three_month_average_volume']` on symbol add (async, non-blocking); display "—" until returned

---

## 11. File Structure

```
highlow-tui/
├── app.py                     # Entry point; App class with CSS embedded as class variable
├── brokers/
│   ├── base.py                # BrokerBase ABC + Order, Position, FlattenResult dataclasses
│   ├── ghost_broker.py        # GhostBroker(BrokerBase) — SQLite-backed
│   └── alpaca_broker.py       # AlpacaBroker(BrokerBase) — stub
├── providers/                 # Existing — enhanced
│   ├── base.py
│   ├── yahoo_provider.py      # + Semaphore(3) + 429 backoff
│   └── coinbase_provider.py
├── core/
│   ├── state_store.py         # CentralStateStore + SymbolState dataclass
│   ├── copilot.py             # CopilotEngine.score(state, spy_state) → float
│   ├── symbol_monitor.py      # SymbolMonitor — turbo mode + market hours
│   └── sparkline.py           # sparkline(deque) → str
├── requirements.txt
└── style.tcss                 # External TCSS fallback (app.py uses CSS class variable)
```

**Note:** TCSS is embedded as `CSS = "..."` on the App class for single-file portability. `style.tcss` is a development reference copy.

---

## 12. Dependencies

```
textual>=0.65.0
yfinance>=0.2.50
python-dotenv>=1.0.0
httpx>=0.27.0
aiohttp>=3.9.0
websockets>=12.0
cryptography>=42.0.0
tomli>=2.0.0
```

---

## 13. Success Criteria

- [ ] Zero flicker on high-volatility updates
- [ ] Typing any ticker auto-focuses command bar within one keypress
- [ ] Co-Pilot scores update on every data tick; `INSTITUTIONAL` signals visible on breakouts
- [ ] Heatmap tint changes are visually instant (CSS transition, no content repaint)
- [ ] Ghost engine opens/closes positions with PnL math verified against manual calculation
- [ ] Shift+K → type CONFIRM → flatten executes; ESC dismisses safely
- [ ] 60-second kill modal timeout auto-dismisses
- [ ] App starts from cold with `python app.py` in under 3 seconds
- [ ] No blank screen on API timeout (last-known prices shown with stale indicator)
- [ ] Performance Panel shows accurate Win Rate, Profit Factor, and Max Drawdown
- [ ] HTTP 429 triggers backoff; affected cells show stale indicator
- [ ] Turbo mode activates correctly; timer resets on re-trigger
- [ ] RSI/ATR/VWAP show "—" during warmup and do not affect scoring
