#!/usr/bin/env python3
"""
HighLow TUI: terminal UI for session highs/lows.
Run from highlow-tui directory: python app.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import os, certifi                             
os.environ.setdefault("SSL_CERT_FILE", certifi.where())                                  
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where()) 

# Ensure project root and core are on path
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / 'core'))

from dataclasses import dataclass, field

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Static, Header, Footer, Button, Input
from textual.reactive import reactive
from textual.widget import Widget
from textual.screen import Screen
from rich.text import Text
from rich.style import Style

MAX_TABLE_ROWS = 50
RATE_BAR_WIDTH = 18
RATE_TIMEFRAMES = ["20m", "5m", "1m", "30s"]


def make_bar(value: float, max_val: float, width: int = RATE_BAR_WIDTH, reverse: bool = False) -> str:
    filled = min(int(value / max_val * width), width) if max_val > 0 else 0
    bar = "█" * filled + "░" * (width - filled)
    return bar[::-1] if reverse else bar


HIGHLIGHT_STYLES = {
    "flash_high": Style(),
    "flash_low": Style(),
    "week52_high": Style(color="white", bgcolor="rgb(20,83,45)"),
    "week52_low": Style(color="white", bgcolor="rgb(127,29,29)"),
    "yellow": Style(color="black", bgcolor="yellow"),
    "orange": Style(color="black", bgcolor="orange1"),
    "purple":       Style(color="white", bgcolor="purple"),
    "volume_spike": Style(color="black", bgcolor="rgb(244,114,182)"),
    "default":      Style(),
}


def load_highlight_config():
    path = _ROOT / "config" / "highlight.json"
    default = {
        "thresholds": {
            "consecutiveCount": 1,
            "significantPercentChange": 0.5,
            "volumeSpikeRatio": 2.0,
            "volumeSpikeWindow": 60,
        },
        "colors": {},
    }
    if not path.exists():
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default


def save_highlight_config(config):
    path = _ROOT / "config" / "highlight.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def compute_highlights(data, is_highs, week52_set, thresholds, suppress_yellow=False, volume_spikes=None):
    """Return highlight type for every entry in O(n) — no per-row scanning."""
    if not data:
        return []
    volume_spikes = volume_spikes or set()
    n = len(data)
    consec_threshold = thresholds.get("consecutiveCount", 1) + 1
    sig_pct = thresholds.get("significantPercentChange", 0.5)
    flash_type = "flash_high" if is_highs else "flash_low"
    week52_type = "week52_high" if is_highs else "week52_low"

    # Two-pass O(n) contiguous run-size: run_size[i] = length of the same-symbol
    # run that contains index i (both directions from i).
    run_end = [1] * n
    for i in range(1, n):
        if data[i]["symbol"] == data[i - 1]["symbol"]:
            run_end[i] = run_end[i - 1] + 1
    run_size = list(run_end)
    for i in range(n - 2, -1, -1):
        if data[i]["symbol"] == data[i + 1]["symbol"]:
            run_size[i] = run_size[i + 1]

    highlights = []
    last_pct: dict = {}  # nearest lower-index pct per symbol (for purple)
    for i, e in enumerate(data):
        sym = e["symbol"]
        pct = e.get("percentChange") or 0
        if i == 0:
            h = flash_type
        elif sym in week52_set:
            h = week52_type
        elif e.get("count") == 1 and not suppress_yellow:
            h = "yellow"
        elif run_size[i] >= consec_threshold:
            h = "orange"
        elif sym in last_pct and abs(pct - last_pct[sym]) > sig_pct:
            h = "purple"
        elif sym in volume_spikes:
            h = "volume_spike"
        else:
            h = "default"
        highlights.append(h)
        last_pct[sym] = pct
    return highlights


@dataclass
class SessionState:
    session_highs: list = field(default_factory=list)
    session_lows:  list = field(default_factory=list)
    prev_highs:    dict = field(default_factory=dict)
    prev_lows:     dict = field(default_factory=dict)
    prev_entries_highs: dict = field(default_factory=dict)
    prev_entries_lows:  dict = field(default_factory=dict)
    week52_highs: set = field(default_factory=set)
    week52_lows:  set = field(default_factory=set)


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


class GridRow(Horizontal):
    """One row in the CellGrid — holds all Cell widgets for one symbol."""

    HEAT_CLASSES = {
        "heat-5", "heat-4", "heat-3", "heat-0",
        "heat-n3", "heat-n4", "heat-n5"
    }

    def __init__(self, symbol: str, side: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.symbol = symbol
        self.side = side  # "high" | "low"
        self._current_heat = "heat-0"
        self.cells: dict[str, _Cell] = {}

    def compose(self) -> ComposeResult:
        yield SymCell("—",       classes="col-sym",   id=f"{self.symbol}-sym-{self.side}")
        yield CntCell("—",       classes="col-cnt",   id=f"{self.symbol}-cnt-{self.side}")
        yield PriceCell("—",     classes="col-price", id=f"{self.symbol}-price-{self.side}")
        yield TrendCell("—",     classes="col-trend", id=f"{self.symbol}-trend-{self.side}")
        yield PctCell("—",       classes="col-pct",   id=f"{self.symbol}-pct-{self.side}")
        yield RsiCell("—",       classes="col-rsi",   id=f"{self.symbol}-rsi-{self.side}")
        yield VwapDeltaCell("—", classes="col-vwap",  id=f"{self.symbol}-vwap-{self.side}")
        yield SparkCell("—",     classes="col-spark", id=f"{self.symbol}-spark-{self.side}")
        yield CopilotCell("—",   classes="col-pilot", id=f"{self.symbol}-pilot-{self.side}")

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
    """Zero-flicker reactive grid. Only dirty cells repaint."""

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

    def selected_symbol(self) -> "str | None":
        if not self._symbol_order:
            return None
        return self._symbol_order[self._cursor_idx]


class HighLowTUI(App):
    CSS = """
    Screen {
        layout: vertical;
    }
    #header-row {
        height: 1;
        padding: 0 1;
        layout: horizontal;
    }
    #app-title {
        width: 1fr;
    }
    #ticker {
        height: 1;
        padding: 0 0;
    }
    #rate-bars {
        height: auto;
        padding: 0 0;
        margin: 0 0;
    }
    #tables-container {
        height: 1fr;
        layout: horizontal;
    }
    .table-box {
        width: 1fr;
        height: 1fr;
        border: solid cyan;
        margin: 0 0;
    }
    DataTable {
        height: 1fr;
    }
    #connection-status {
        width: auto;
        text-align: right;
    }
    #mode-toggle {
        width: auto;
        padding: 0 2;
    }
    """

    BINDINGS = [
        ("s", "settings", "Settings"),
        ("q", "quit", "Quit"),
        ("m", "switch_mode", "Mode"),
    ]

    def __init__(
        self,
        equity_provider=None,
        crypto_provider=None,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._equity_provider = equity_provider
        self._crypto_provider = crypto_provider
        self._active_mode = "crypto" if crypto_provider and not equity_provider else "equity"
        self._provider = equity_provider or crypto_provider  # active provider
        self.last_state = {}
        # Per-mode session state
        self._states = {
            "equity": SessionState(),
            "crypto": SessionState(),
        }
        # Flat attributes mirror the active state (unchanged hot path)
        self.session_highs = self._states[self._active_mode].session_highs
        self.session_lows  = self._states[self._active_mode].session_lows
        self.prev_highs    = self._states[self._active_mode].prev_highs
        self.prev_lows     = self._states[self._active_mode].prev_lows
        self.prev_entries_highs = self._states[self._active_mode].prev_entries_highs
        self.prev_entries_lows  = self._states[self._active_mode].prev_entries_lows
        self.week52_highs  = self._states[self._active_mode].week52_highs
        self.week52_lows   = self._states[self._active_mode].week52_lows
        self.volume_spikes: set = set()
        self.connection_status = "connecting"
        self.last_update_time = None
        self._highs_dirty = False
        self._lows_dirty  = False
        self.highlight_config = load_highlight_config()
        self._w_status = None
        self._w_rate_bars = None
        self._w_highs = None
        self._w_lows  = None
        self._w_ticker = None
        self._w_mode_toggle = None
        self._ticker_text    = Text("")
        self._ticker_doubled = Text("")
        self._ticker_offset  = 0
        self._stream_task = None
        self._start_time = time.time()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="header-row"):
            yield Static("[bold]HighLow TUI[/]  [dim]s: Settings  q: Quit[/]", id="app-title")
            if self._equity_provider and self._crypto_provider:
                mode_label = "[bold cyan][Equity][/]  Crypto" if self._active_mode == "equity" else "Equity  [bold cyan][Crypto][/]"
                yield Static(mode_label, id="mode-toggle")
            yield Static("● connecting", id="connection-status")
        yield Static("", id="ticker")
        yield Static(id="rate-bars")
        with Horizontal(id="tables-container"):
            with Vertical(classes="table-box"):
                yield Static("Session new lows", id="lows-label")
                yield DataTable(id="lows-table", cursor_type="row", zebra_stripes=True)
            with Vertical(classes="table-box"):
                yield Static("Session new highs", id="highs-label")
                yield DataTable(id="highs-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._w_status    = self.query_one("#connection-status", Static)
        self._w_ticker    = self.query_one("#ticker", Static)
        self._w_rate_bars = self.query_one("#rate-bars", Static)
        self._w_highs     = self.query_one("#highs-table", DataTable)
        self._w_lows      = self.query_one("#lows-table", DataTable)
        if self._equity_provider and self._crypto_provider:
            self._w_mode_toggle = self.query_one("#mode-toggle", Static)
        for table in (self._w_highs, self._w_lows):
            table.add_column("Symbol", width=6)
            table.add_column("Count",  width=5)
            table.add_column("Price",  width=9)
            table.add_column("% Chg", width=8)
        self.set_interval(1 / 12, self._scroll_ticker)
        self._stream_task = asyncio.create_task(self._data_loop())

    async def _data_loop(self) -> None:
        try:
            await self._provider.connect()
            self.connection_status = "connected"
            self._refresh_status()
            async for data in self._provider.stream():
                if data.get("type") == "HIGHLOW_UPDATE":
                    self._apply_highlow_update(data.get("data", {}))
                    self.last_update_time = time.time()
                    self._refresh_ui()
                    await asyncio.sleep(0)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.connection_status = f"error: {e}"
            self._refresh_status()

    def _apply_highlow_update(self, data):
        if not data:
            return
        self.last_state = data
        new_highs = data.get("newHighs") or {}
        new_lows = data.get("newLows") or {}
        last_high = data.get("lastHigh") or {}
        last_low = data.get("lastLow") or {}
        percent_change = data.get("percentChange") or {}
        ts = time.time()

        # New high entries
        new_high_entries = []
        for symbol, count in new_highs.items():
            if count <= 0 or symbol not in last_high:
                continue
            if count <= self.prev_highs.get(symbol, 0):
                continue
            prev_entry = self.prev_entries_highs.get(symbol, {})
            new_high_entries.append({
                "symbol": symbol,
                "count": count,
                "timestamp": ts,
                "price": last_high[symbol],
                "percentChange": percent_change.get(symbol, 0.0),
                "prevCount": prev_entry.get("count", 0),
                "prevPercentChange": prev_entry.get("percentChange", 0),
            })
        for e in new_high_entries:
            self.session_highs.insert(0, e)
            self.prev_entries_highs[e["symbol"]] = {
                "count": e["count"],
                "percentChange": e["percentChange"],
                "timestamp": e["timestamp"],
            }
        self.prev_highs = dict(new_highs)
        self.session_highs = self.session_highs[:MAX_TABLE_ROWS]

        # New low entries
        new_low_entries = []
        for symbol, count in new_lows.items():
            if count <= 0 or symbol not in last_low:
                continue
            if count <= self.prev_lows.get(symbol, 0):
                continue
            prev_entry = self.prev_entries_lows.get(symbol, {})
            new_low_entries.append({
                "symbol": symbol,
                "count": count,
                "timestamp": ts,
                "price": last_low[symbol],
                "percentChange": percent_change.get(symbol, 0.0),
                "prevCount": prev_entry.get("count", 0),
                "prevPercentChange": prev_entry.get("percentChange", 0),
            })
        for e in new_low_entries:
            self.session_lows.insert(0, e)
            self.prev_entries_lows[e["symbol"]] = {
                "count": e["count"],
                "percentChange": e["percentChange"],
                "timestamp": e["timestamp"],
            }
        self.prev_lows = dict(new_lows)
        self.session_lows = self.session_lows[:MAX_TABLE_ROWS]

        self.week52_highs = set(data.get("week52Highs") or [])
        self.week52_lows = set(data.get("week52Lows") or [])
        spike_ratio = self.highlight_config.get("thresholds", {}).get("volumeSpikeRatio", 2.0)
        self.volume_spikes = {
            sym for sym, ratio in (data.get("volumeSpikes") or {}).items()
            if ratio >= spike_ratio
        }
        self._highs_dirty = len(new_high_entries) > 0
        self._lows_dirty = len(new_low_entries) > 0

    def _refresh_status(self):
        dot = "[green]●[/green]" if self.connection_status == "connected" else "[red]●[/red]"
        name = self._provider.get_metadata()["name"]
        self._w_status.update(f"{dot} [dim]{name}[/dim]  {self.connection_status}")

    def _scroll_ticker(self) -> None:
        n = len(self._ticker_text)
        if not n:
            return
        w = self._w_ticker.size.width or 80
        self._w_ticker.update(self._ticker_doubled[self._ticker_offset : self._ticker_offset + w])
        self._ticker_offset = (self._ticker_offset + 1) % n

    def _build_ticker_text(self) -> None:
        t = Text()
        for e in self.session_highs[:25]:
            pct = e.get("percentChange") or 0
            t.append(f"  {e['symbol']} ▲{e['price']:.2f} ({pct:+.2f}%)  ", style="green")
        for e in self.session_lows[:25]:
            pct = e.get("percentChange") or 0
            t.append(f"  {e['symbol']} ▼{e['price']:.2f} ({pct:+.2f}%)  ", style="red")
        if not len(t):
            t.append("  Waiting for data...  ", style="dim")
        self._ticker_text = t
        self._ticker_doubled = t + t
        self._ticker_offset = min(self._ticker_offset, max(1, len(t)) - 1)

    @staticmethod
    def _render_rate_bars(high_counts: dict, low_counts: dict, width: int) -> str:
        max_val = max(
            max((high_counts.get(t, 0) for t in RATE_TIMEFRAMES), default=1),
            max((low_counts.get(t, 0) for t in RATE_TIMEFRAMES), default=1),
            1,
        )
        # Fixed non-bar chars per line: count(3) + sp(1) + bar + sp(1) + label(3) + sp(1) + bar + sp(1) + count(3) = 13
        bar_w = max(4, (width - 13) // 2)
        lines = [f"[dim]{'Lows':>{bar_w + 4}}  Highs[/dim]"]
        for tf in RATE_TIMEFRAMES:
            lc = low_counts.get(tf, 0)
            hc = high_counts.get(tf, 0)
            l_bar = make_bar(lc, max_val, bar_w, reverse=True)
            h_bar = make_bar(hc, max_val, bar_w)
            lines.append(
                f"[dim]{lc:>3d}[/dim] [red]{l_bar}[/red] [dim]{tf:>3s}[/dim] [green]{h_bar}[/green] [dim]{hc:<3d}[/dim]"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_table(table: DataTable, entries, is_highs, week52_set, thresholds, prefix, suppress_yellow=False, volume_spikes=None):
        table.clear()
        highlights = compute_highlights(entries, is_highs, week52_set, thresholds, suppress_yellow=suppress_yellow, volume_spikes=volume_spikes)
        for i, (e, h) in enumerate(zip(entries, highlights)):
            style = HIGHLIGHT_STYLES.get(h, HIGHLIGHT_STYLES["default"])
            pct = e.get("percentChange") or 0
            sign = "+" if pct >= 0 else ""
            pct_style = style + Style(color="green" if pct >= 0 else "red")
            table.add_row(
                Text(f"{e['symbol']:<6}", style=style),
                Text(f"{e['count']:>5}", style=style),
                Text(f"{e.get('price', 0):>9.2f}", style=style),
                Text(f"{sign}{pct:.2f}%".rjust(8), style=pct_style),
                key=f"{prefix}_{i}_{e['symbol']}",
            )

    def _refresh_ui(self):
        self._refresh_status()
        # Rate bars — use live widget width so bars fill the terminal
        high_counts = self.last_state.get("highCounts") or {}
        low_counts = self.last_state.get("lowCounts") or {}
        bar_width = self._w_rate_bars.size.width or 80
        self._w_rate_bars.update(self._render_rate_bars(high_counts, low_counts, bar_width))

        thresholds = self.highlight_config.get("thresholds", {})

        if self._highs_dirty or self._lows_dirty:
            self._build_ticker_text()

        suppress = time.time() - self._start_time < 300
        if self._highs_dirty:
            self._build_table(self._w_highs, self.session_highs, True,  self.week52_highs, thresholds, "h", suppress_yellow=suppress, volume_spikes=self.volume_spikes)
            self._highs_dirty = False

        if self._lows_dirty:
            self._build_table(self._w_lows,  self.session_lows,  False, self.week52_lows,  thresholds, "l", suppress_yellow=suppress, volume_spikes=self.volume_spikes)
            self._lows_dirty = False

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen(self.highlight_config, self._on_settings_save))

    def _on_settings_save(self, config):
        self.highlight_config = config
        save_highlight_config(config)
        self._refresh_ui()

    def check_action(self, action: str, parameters: tuple):
        if action == "switch_mode":
            return bool(self._equity_provider and self._crypto_provider)
        return True

    async def action_switch_mode(self) -> None:
        await self._switch_mode()

    async def _switch_mode(self) -> None:
        """5-step provider switch: cancel stream → disconnect → swap state → reconnect → restart stream."""
        # Step 1: cancel the active stream task
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        self._stream_task = None

        # Step 2+3: disconnect active provider
        await self._provider.disconnect()

        # Step 4: swap mode and session state
        new_mode = "crypto" if self._active_mode == "equity" else "equity"
        # Save current state
        self._states[self._active_mode].session_highs = self.session_highs
        self._states[self._active_mode].session_lows  = self.session_lows
        self._states[self._active_mode].prev_highs    = self.prev_highs
        self._states[self._active_mode].prev_lows     = self.prev_lows
        self._states[self._active_mode].prev_entries_highs = self.prev_entries_highs
        self._states[self._active_mode].prev_entries_lows  = self.prev_entries_lows
        self._states[self._active_mode].week52_highs  = self.week52_highs
        self._states[self._active_mode].week52_lows   = self.week52_lows
        # Restore new mode state
        self._active_mode  = new_mode
        self.session_highs = self._states[new_mode].session_highs
        self.session_lows  = self._states[new_mode].session_lows
        self.prev_highs    = self._states[new_mode].prev_highs
        self.prev_lows     = self._states[new_mode].prev_lows
        self.prev_entries_highs = self._states[new_mode].prev_entries_highs
        self.prev_entries_lows  = self._states[new_mode].prev_entries_lows
        self.week52_highs  = self._states[new_mode].week52_highs
        self.week52_lows   = self._states[new_mode].week52_lows
        # Switch active provider
        self._provider = self._equity_provider if new_mode == "equity" else self._crypto_provider
        # Clear tables
        self._w_highs.clear()
        self._w_lows.clear()
        # Update mode toggle label
        if self._w_mode_toggle:
            label = "[bold cyan][Equity][/]  Crypto" if new_mode == "equity" else "Equity  [bold cyan][Crypto][/]"
            self._w_mode_toggle.update(label)

        # Step 5: reconnect and restart stream
        await self._provider.connect()
        self.connection_status = "connecting"
        self._stream_task = asyncio.create_task(self._data_loop())


class SettingsScreen(Screen):
    def __init__(self, initial_config, on_save, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial_config = initial_config
        self.on_save_cb = on_save

    def compose(self) -> ComposeResult:
        t = self.initial_config.get("thresholds", {})
        yield Static("[bold]Highlight settings[/] (edit config/highlight.json for colors)")
        yield Static(f"Consecutive count (orange): {t.get('consecutiveCount', 1)}")
        yield Static(f"Significant % change (purple): {t.get('significantPercentChange', 0.5)}")
        yield Static("\n[dim]Close with Escape. Edit config/highlight.json and press s again to reload.[/]")
        yield Button("Close", variant="primary", id="close-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            try:
                cfg = load_highlight_config()
                if self.on_save_cb:
                    self.on_save_cb(cfg)
            except Exception:
                pass
            self.dismiss()


def main():
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")

    import json as _json
    from core.app_config import load_config, get_equity_broker, get_crypto_broker, ConfigError
    from core.provider_loader import load_equity_provider, load_crypto_provider, ProviderLoadError
    from core.license import get_license_key, validate, activate, save_license_key
    from providers.yahoo_provider import YahooFinanceProvider

    # --activate <key>  — bind key to this machine and exit
    if "--activate" in sys.argv:
        idx = sys.argv.index("--activate")
        key = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else get_license_key()
        if not key:
            print("Usage: python app.py --activate <key>", file=sys.stderr)
            sys.exit(1)
        try:
            bound_key = activate(key)
            save_license_key(bound_key)
            print("Key activated and saved to ~/.highlowticker/config.toml")
        except RuntimeError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    # Validate key if present — warn only, never block
    result = validate(get_license_key())
    if result.message:
        print(f"[license] {result.message}", file=sys.stderr)
    if result.valid and not result.machine_bound:
        print("[license] Key not yet bound to this machine. Run: python app.py --activate", file=sys.stderr)

    equity_symbols = _load_symbols()
    crypto_symbols = _load_crypto_symbols()

    try:
        cfg = load_config()
        equity_broker = get_equity_broker(cfg)
        crypto_broker = get_crypto_broker(cfg)
    except ConfigError as e:
        print(f"[HighlowTicker] Config error: {e}", file=sys.stderr)
        sys.exit(1)

    equity_provider = None
    crypto_provider = None

    if equity_broker:
        try:
            equity_provider = load_equity_provider(equity_broker, equity_symbols)
        except ProviderLoadError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    if crypto_broker:
        try:
            crypto_provider = load_crypto_provider(crypto_broker, crypto_symbols)
        except ProviderLoadError as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)

    # Fallback: neither configured → Yahoo free tier
    if not equity_provider and not crypto_provider:
        equity_provider = YahooFinanceProvider(equity_symbols)

    app = HighLowTUI(
        equity_provider=equity_provider,
        crypto_provider=crypto_provider,
    )
    app.run()


def _load_symbols() -> list[str]:
    """Load equity symbol list from tickers.json with a safe fallback."""
    import json as _json
    tickers_path = _ROOT / "tickers" / "tickers.json"
    try:
        return _json.loads(tickers_path.read_text())["symbols"]
    except Exception:
        return ["SPY", "QQQ", "DIA", "AAPL", "MSFT", "NVDA", "TSLA", "AMZN"]


def _load_crypto_symbols() -> list[str]:
    """Load crypto symbol list from crypto_tickers.json with a safe fallback."""
    import json as _json
    tickers_path = _ROOT / "tickers" / "crypto_tickers.json"
    try:
        return _json.loads(tickers_path.read_text())["symbols"]
    except Exception:
        return ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD"]


if __name__ == "__main__":
    main()
