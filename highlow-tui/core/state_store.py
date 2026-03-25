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
