# Sovereign Terminal

> A Bloomberg-class stock screener TUI for independent traders. Zero-flicker. Algo-scored. Ghost-traded.

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![Textual](https://img.shields.io/badge/textual-8.x-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

```
pip install -r requirements.txt && python app.py
```

---

## Features

### ⚡ Zero-Flicker Reactive Grid
Replaces DataTable with a custom `CellGrid` built from `Static` subclasses, each carrying a class-level `reactive(value)`. Only cells whose values actually changed get repainted — the rest stay frozen. On a 50-symbol watchlist, this cuts render work by ~90% vs a full table refresh.

### 🧠 Co-Pilot Alpha Engine (−10 → +10)
Every symbol gets a real-time momentum score computed from six weighted signals:

| Signal | Bullish | Bearish |
|--------|---------|---------|
| RS vs SPY | +3 (divergence) / +2 (acceleration) | — |
| Volume | +3 (≥3× ADV) / +2 (≥2× ADV) | — |
| VWAP | +2 (price above) | −2 (price below) |
| RSI | +2 (55–70 momentum zone) / +2 (oversold <30) | −4 (extreme overbought >85) |
| Count Velocity | +1 (>3 hits/5min) | — |
| Trend Alignment | +1 (price > session low & VWAP) | — |

Score is clamped to `max(min(raw, 10.0), −10.0)`. Labels: 💎 INSTITUTIONAL → ⚠ LIQUIDITY TRAP.

### 👻 Ghost Trading Engine
$100,000 simulated paper account backed by SQLite. Auto-enters long positions when Co-Pilot score ≥ 6.0, one position per symbol.

- **Kelly-lite sizing**: fixed 1% during warmup (<10 trades), then 0.5× Kelly capped at 0.25–2%
- **Exit rules**: Stop-loss 0.75% | Take-profit 1.50% | Max hold 30 min
- **Slippage tracking**: logs delta between target and actual exit pct
- **Live stats**: Win Rate %, Profit Factor, Max Drawdown, Equity Curve sparkline

### 🔥 Adaptive Turbo Mode
Normal polling: 5s per symbol batch. Turbo mode: 1s, auto-triggered when any of these fire:

- ATR expansion > 1.5× 5-minute baseline
- Single-tick price move > 1%
- Volume spike > 3× ADV
- Co-Pilot score crosses ±6

Turbo stays active for 5 minutes, resets on each re-trigger.

### 🌡️ 7-Level Heatmap
Row background = 5-minute price velocity. 400ms CSS transition, emerald → crimson.

```
heat-5   rgba(63,185,80, 0.22)    > +1.5% velocity
heat-4   rgba(63,185,80, 0.13)    > +0.8%
heat-3   rgba(63,185,80, 0.06)    > +0.3%
heat-0   transparent              neutral
heat-n3  rgba(248,81,73, 0.06)    < −0.3%
heat-n4  rgba(248,81,73, 0.13)    < −0.8%
heat-n5  rgba(248,81,73, 0.22)    < −1.5%
```

### ⌨️ Command Bar
Omnipresent bottom bar. Type any letter — the app intercepts it at the `App.on_key` level before any widget. Three modes:
- **ADD** (default): ticker → add to watchlist
- **SEARCH** (`/`): filter visible rows
- **COMMAND** (`:`): `:dd` delete, `:mode` switch

### ☢️ Kill Switch
`Shift+K` → `KillModal` → type `CONFIRM` (case-sensitive) → flatten all ghost positions. ESC dismisses. Auto-timeout: 60 seconds.

---

## Quick Start

```bash
git clone https://github.com/jach8/highlowticker-tui.git
cd highlowticker-tui/highlow-tui
pip install -r requirements.txt
python app.py
```

**Requirements:** Python 3.11+, internet connection for Yahoo Finance data.

---

## Key Bindings

| Key | Action |
|-----|--------|
| Any letter | Open command bar |
| `j` / `k` | Navigate rows |
| `/` | Search / filter |
| `:` | Command mode |
| `m` | Toggle highs ↔ lows focus |
| `p` | Toggle Ghost Performance Panel |
| `Shift+K` | Kill switch — flatten all |
| `q` | Quit |

---

## Writing Your Own Co-Pilot Logic

The `CopilotEngine` is fully swappable. It's a stateless class with one method:

```python
# core/copilot.py
class CopilotEngine:
    def score(
        self,
        state: SymbolState,     # all market data for this symbol
        spy_state: Optional[SymbolState],  # SPY context
    ) -> tuple[float, str]:     # (score -10..+10, label)
        ...
```

To add your own alpha signal, subclass it:

```python
from core.copilot import CopilotEngine
from core.state_store import SymbolState
from typing import Optional

class MyCopilot(CopilotEngine):
    def score(self, state: SymbolState, spy_state: Optional[SymbolState]):
        score, label = super().score(state, spy_state)

        # Add your signal — e.g., options flow proxy via put/call ratio
        if state.count_velocity_5m > 10 and state.rsi and state.rsi < 40:
            score = min(score + 2.0, 10.0)
            label = "🔥 FLOW CONFIRMED"

        return score, label
```

Then pass it to `SovereignApp`:

```python
app = SovereignApp()
app._copilot = MyCopilot()
app.run()
```

---

## Architecture

```
providers/yahoo_provider.py   ← market data (429 backoff, Semaphore(3))
        ↓
DataCoordinator.stream()      ← async generator, yields HIGHLOW_UPDATE dicts
        ↓
CentralStateStore             ← singleton, all SymbolState objects
        ↓
CopilotEngine.score()         ← stateless, reads SymbolState → score
SymbolMonitor.evaluate()      ← turbo mode trigger
GhostBroker.enter_long()      ← SQLite paper trades
        ↓
CellGrid.update_row()         ← diff engine → only dirty cells repaint
```

---

## Ghost Trading Database

Stored at `~/.sovereign/ghost_trades.db` (SQLite). Three tables:
- `positions` — open positions
- `trades` — closed trade ledger with slippage tracking
- `stats` — running equity, win/loss counters, drawdown

```bash
# Inspect your ghost trading history
sqlite3 ~/.sovereign/ghost_trades.db "SELECT symbol, pnl, exit_reason FROM trades ORDER BY exit_time DESC LIMIT 20;"
```

---

## Building in Public 🏗️

This terminal is built in public as part of the **X Developer** series — shipping real tools, not demos.

- Follow the build thread: [@TheRealDX](https://x.com/TheRealDX)
- Star the repo if the reactive grid or Co-Pilot engine helped you
- PRs welcome — especially new Co-Pilot signal implementations

```
The best way to learn algo trading is to build the tools yourself.
```

---

## License

MIT — use it, fork it, ship it.
