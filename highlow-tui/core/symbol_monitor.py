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

    def clear_expired(self) -> None:
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
