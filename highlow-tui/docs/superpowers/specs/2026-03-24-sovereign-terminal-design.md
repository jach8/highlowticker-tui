# Sovereign Terminal v2.0 — Design Specification

**Date:** 2026-03-24
**Status:** Approved
**Architect:** Principal Quant / Lead TUI Designer
**Approved Approach:** A — Reactive CellGrid Engine

---

## 1. Executive Summary

A total architectural evolution of `highlowticker-tui` into a **Sovereign Trading Terminal** — a Bloomberg-class, single-file Python TUI that provides total situational awareness for real-time equity and crypto markets. The terminal must feel zero-latency, look institutional, and generate actionable alpha signals via a weighted Co-Pilot engine. It must also run a Ghost (paper) trading engine that proves or disproves the Co-Pilot's edge in real time.

**Deliverable:** A single `app.py` (~2,200 lines) with embedded TCSS that runs with `python app.py` on any machine with `pip install -r requirements.txt`.

---

## 2. Architecture

### 2.1 Reactive CellGrid Engine (Approach A)

Replace the existing `DataTable` entirely with a custom `CellGrid` widget built from individual `Static` reactive widgets — one widget per visible cell.

**Rationale:** `DataTable.update_cell()` triggers internal row reflow even for single-cell changes. The root cause of all "glitchy" behavior. Individual `Static` widgets with Textual `reactive()` properties re-render at the pixel level — only the exact cell that changed.

**Data flow:**

```
Provider (Yahoo / Coinbase WS)
    ↓ asyncio.Queue (maxsize=20, drop-oldest on overflow)
DataCoordinator  ←→  Semaphore rate-limiter (max 3 concurrent fetches)
    ↓
SymbolMonitor  (tracks ATR + velocity → Turbo Mode trigger)
    ↓
CentralStateStore  (singleton, pure dict, immutable snapshots)
    ↓  diff engine (new_snap vs prev_snap)
CellGrid  →  only dirty Cell widgets receive .value = new_val
    ↓
CopilotEngine  →  score each symbol (-10 → +10)
    ↓
GhostBroker  →  auto-enter signals above threshold, track PnL
```

### 2.2 CentralStateStore

A pure-Python singleton holding the current terminal state. **No Textual reactives at this level** — the store is plain Python for speed. The UI layer reads from it; the data pipeline writes to it.

```python
@dataclass
class SymbolState:
    symbol: str
    price: float
    prev_price: float
    pct_change: float
    count: int                    # session high/low hit count
    price_history: deque          # maxlen=20, for sparkline
    volume: float
    avg_volume: float             # 20-period average
    vwap: float
    rsi: float
    atr_1m: float
    velocity_5m: float            # (price_now - price_5m_ago) / price_5m_ago
    copilot_score: float          # -10.0 to +10.0
    copilot_label: str
    is_turbo: bool                # Turbo mode active
    turbo_until: float            # epoch timestamp
    last_updated: float           # epoch timestamp
```

### 2.3 CellGrid Widget

```
CellGrid (ScrollView)
└── GridRow (Horizontal, one per symbol)
    ├── SymCell(symbol)       reactive: str
    ├── CntCell(count)        reactive: int
    ├── PriceCell(price)      reactive: float
    ├── TrendCell(trend)      reactive: str
    ├── PctCell(pct)          reactive: float
    ├── RsiCell(rsi)          reactive: float
    ├── VwapDeltaCell(delta)  reactive: float
    ├── SparkCell(history)    reactive: tuple
    └── CopilotCell(score, label)  reactive: (float, str)
```

Each `Cell` subclass implements `watch_value(old, new)` — if `old == new`, the method body is a no-op (`return`). Textual only calls `watch_` when the reactive changes, so truly unchanged cells never touch the terminal buffer.

### 2.4 Command Bar

A `CommandBar` widget sits at the top of the layout, always visible. It intercepts `on_key` at the **app level** before any other widget. If the key is an alphanumeric character and no modal is open, it:
1. Sets focus to the `CommandBar` input
2. Pre-fills the character
3. Shows the `ADD ▸` prompt

On `Enter`: validates the ticker (sync fetch via executor thread), adds to watchlist if valid, clears input.
On `Escape`: clears and returns focus to grid.
On `/`: switches to search mode (filters visible rows by substring).
On `:`: switches to command mode (`:dd` = delete, `:mode crypto` = switch provider).

---

## 3. Co-Pilot Alpha Engine

### 3.1 Weighted Scoring System

Score range: **−10.0 to +10.0**. Computed fresh on every data tick for each symbol.

| Signal | Weight | Logic |
|--------|--------|-------|
| Relative Strength vs SPY | +3 / −3 | If `ticker_pct > 0` and `spy_pct < 0` → +3 (divergence). If ticker pct > 2× SPY pct → +2. |
| Volume Profile | +2 | If `current_volume > 2× avg_volume_20p` → +2. If `> 3×` → +3 (institutional print). |
| Price vs VWAP | +2 / −2 | If `price > vwap` → +2 bullish bias. If `price < vwap` → −2. |
| RSI Momentum | +2 / −2 | RSI 55–70 rising → +2. RSI < 30 on a session low → +2 (oversold bounce). RSI > 75 → −1 (overbought). |
| Session Count Velocity | +1 | Count increments > 3 in 5 minutes → +1 (acceleration signal). |
| Trend Alignment | +1 / −1 | Price above open + above 5-min VWAP → +1. |

**Score → Label mapping:**

| Score | Label |
|-------|-------|
| ≥ 8.0 | `💎 INSTITUTIONAL` |
| 6.0–7.9 | `🟢 BULL BREAKOUT` |
| 4.0–5.9 | `🟢 STRENGTH` |
| 2.0–3.9 | `● WATCH` |
| −1.9–1.9 | `— NEUTRAL` |
| −2.0 to −3.9 | `● FADE` |
| −4.0 to −5.9 | `🔴 WEAK` |
| −6.0 to −7.9 | `🔴 BREAKDOWN` |
| ≤ −8.0 | `⚠ LIQUIDITY TRAP` |

### 3.2 Ghost Auto-Entry Logic

When `copilot_score >= 6.0` on a session high: Ghost broker enters LONG at current price, size = 1% of $100k equity (Kelly-lite: 0.5× Kelly fraction based on score).

When `copilot_score <= -6.0` on a session low: Ghost broker enters SHORT.

Exit rules:
- Stop loss: 0.75% adverse move
- Take profit: 1.5% favorable move (2:1 R/R)
- Max hold: 30 minutes

---

## 4. Heatmap System

### 4.1 Velocity Calculation

```python
velocity_5m = (price_now - price_5m_ago) / price_5m_ago * 100
# Uses deque(maxlen=5) of 1-minute prices
```

### 4.2 TCSS Class Mapping

| Class | Velocity | Background |
|-------|----------|------------|
| `heat-5` | > +1.5% | `rgba(63,185,80,0.22)` — emerald bright |
| `heat-4` | +0.8% to +1.5% | `rgba(63,185,80,0.13)` |
| `heat-3` | +0.3% to +0.8% | `rgba(63,185,80,0.06)` |
| `heat-0` | ±0.3% | transparent |
| `heat-n3` | −0.3% to −0.8% | `rgba(248,81,73,0.06)` |
| `heat-n4` | −0.8% to −1.5% | `rgba(248,81,73,0.13)` |
| `heat-n5` | < −1.5% | `rgba(248,81,73,0.22)` — crimson bright |

The class is set via `row.add_class(heat_class); row.remove_class(old_heat_class)`. TCSS transitions handle the visual fade. No repaint of cell content.

---

## 5. Adaptive Polling — SymbolMonitor

`SymbolMonitor` runs as a background asyncio task. On each tick it evaluates every tracked symbol:

**Turbo Mode trigger (any one condition):**
- 1-minute ATR expands > 50% from its 5-minute baseline
- Price moves > 1.0% in a single poll cycle
- Volume spike > 3× 20-period average
- Co-Pilot score crosses ±6.0 threshold

**Turbo Mode behavior:**
- That symbol's fetch interval drops from the global poll interval (90s) to **5 seconds**
- Duration: 5 minutes from last trigger
- A `⚡` badge appears in the symbol cell
- `DataCoordinator` uses a `asyncio.Semaphore(3)` — max 3 concurrent symbol fetches — to prevent Yahoo Finance rate-limiting

**Normal mode:** Batch fetch via `yf.download()` (existing pattern, preserved).

---

## 6. Ghost Trading Engine

### 6.1 Storage

SQLite database: `~/.sovereign/ghost_trades.db`

Tables:
- `positions`: open virtual positions (symbol, entry_price, size, direction, entry_time, score_at_entry)
- `trades`: closed trades (+ exit_price, pnl, duration, exit_reason)
- `stats`: rolling win_rate, profit_factor, sharpe_ratio (updated on each close)

### 6.2 Performance HUD

A collapsible sidebar panel (toggle with `p` key) showing:
- Account equity curve (ASCII sparkline)
- Win Rate %
- Profit Factor (gross_profit / gross_loss)
- Total trades
- Max drawdown %
- Top 3 performing signals by label

### 6.3 BrokerBase ABC

```python
class BrokerBase(ABC):
    @abstractmethod
    async def submit_order(self, symbol, side, qty, order_type, limit_price=None) -> Order: ...
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
`AlpacaBroker(BrokerBase)` — stub, raises `NotImplementedError` with setup instructions.

---

## 7. Kill Switch — Shift+K

1. `on_key("K")` with shift modifier → dismiss any open modal → mount `KillModal` (full-screen red overlay)
2. `KillModal` displays open positions and total exposure
3. User must type the exact string `CONFIRM` in an input field (no button clicking)
4. On match → `broker.flatten_all()` → dismiss modal → fire `Notify("⚠ FLATTEN ALL EXECUTED", severity="error")` toast
5. Ghost positions are closed at last market price with `exit_reason="KILL_SWITCH"`

---

## 8. Layout Specification

```
┌─ Header: SOVEREIGN TERMINAL v2.0 — [MODE] — [TIME] ────────────────────┐
│ Pulse Bar: SPY QQQ IWM BTC VIX (live prices + % change)               │
│ Command Bar: ⌨ ADD ▸ [input] ─── hints ─── [ESC cancel]              │
│ Breadth: ▓░ advances/declines + RISK-ON/OFF mood + heatmap legend     │
│ Rate Bars: 30s / 1m / 5m / 20m breakout counts                        │
│ Ticker Tape: scrolling top movers                                      │
├────────────────────────────────┬───────────────────────────────────────┤
│ ▼ SESSION LOWS (N symbols)     │ ▲ SESSION HIGHS (N symbols)           │
│ SYM CNT PRICE TRD %CHG RSI VWAP△ SPARK CO-PILOT               │
│ [rows with heatmap tinting]    │ [rows with heatmap tinting]           │
├────────────────────────────────┴───────────────────────────────────────┤
│ Status: ● YAHOO 87ms │ NEXT 14s │ SYMBOLS 105 │ keys…  ⇧K FLATTEN   │
└────────────────────────────────────────────────────────────────────────┘
```

Ghost Performance Panel (toggled with `p`):
```
╔═ GHOST ENGINE ═══════════════╗
║ Equity  $101,240  +1.24%     ║
║ WinRate 62.5%   PF 1.84      ║
║ Trades  16  MaxDD -1.2%      ║
║ ▁▂▃▄▅▆▇█ equity curve        ║
╚══════════════════════════════╝
```

---

## 9. Sparkline Format

Use Unicode block characters `▁▂▃▄▅▆▇█` (8 levels) mapped from `deque(maxlen=20)` of prices, normalized to min/max of the window. 20 characters = 20 bars. Displayed in a fixed-width `SparkCell`.

---

## 10. Key Bindings

| Key | Action |
|-----|--------|
| Any alpha/num | Auto-focus Command Bar, pre-fill character |
| Enter (in grid) | Drill-down detail modal for selected symbol |
| j / k | Navigate grid rows |
| dd | Remove selected symbol from watchlist |
| b | Buy modal (Ghost or live if broker configured) |
| s | Sell modal |
| m | Toggle Equity ↔ Crypto mode |
| p | Toggle Ghost Performance Panel |
| r | Reload highlight config |
| Shift+K | Kill switch — KillModal |
| q | Quit |
| / | Command bar search mode |
| : | Command bar command mode |
| Escape | Cancel / return focus to grid |

---

## 11. File Structure

```
highlow-tui/
├── app.py                     # Single-file entry point — all UI + logic
├── brokers/
│   ├── base.py                # BrokerBase ABC
│   ├── ghost_broker.py        # GhostBroker(BrokerBase) — SQLite
│   └── alpaca_broker.py       # Stub
├── providers/                 # Existing — enhanced with SymbolMonitor
│   ├── base.py
│   ├── yahoo_provider.py
│   └── coinbase_provider.py
├── core/
│   ├── state_store.py         # CentralStateStore + SymbolState
│   ├── copilot.py             # CopilotEngine
│   ├── symbol_monitor.py      # SymbolMonitor (turbo mode)
│   └── sparkline.py           # Unicode block sparkline util
├── requirements.txt           # Updated
└── style.tcss                 # Fallback external TCSS (app.py embeds it)
```

---

## 12. Dependencies

```
textual>=0.65.0
yfinance>=0.2.40
python-dotenv>=1.0.0
httpx>=0.27.0
aiohttp>=3.9.0
websockets>=12.0
cryptography>=42.0.0
tomli>=2.0.0
```

---

## 13. Success Criteria

- [ ] Zero flicker on high-volatility updates (verified by visual inspection)
- [ ] Typing any ticker auto-focuses command bar within one keypress
- [ ] Co-Pilot scores update on every data tick
- [ ] Heatmap tint changes are visually instant (CSS transition, no repaint)
- [ ] Ghost engine opens and closes positions with correct PnL math
- [ ] Shift+K → CONFIRM string → flatten executes correctly
- [ ] App starts from cold with `python app.py` in under 3 seconds
- [ ] No blank screen on API timeout (graceful degradation with last-known prices)
- [ ] Performance Panel shows accurate Win Rate and Profit Factor
