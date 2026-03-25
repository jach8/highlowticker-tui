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
            if ratio >= 3.0:
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
