"""YahooFinanceProvider — free tier, 90-second polling via yfinance."""
import asyncio
import time
from typing import AsyncIterator, Dict, List, Optional

import yfinance as yf

from providers._subscription import wall_clock_counts
from providers._volume import VolumeTracker

PRUNE_WINDOW = 1200  # seconds


class YahooFinanceProvider:
    def __init__(self, symbols: List[str], poll_interval: float = 90.0) -> None:
        self.symbols = list(symbols)
        self.poll_interval = poll_interval
        self._session_highs: Dict[str, float] = {}
        self._session_lows: Dict[str, float] = {}
        self._high_counts: Dict[str, int] = {}  # cumulative per session
        self._low_counts: Dict[str, int] = {}
        self._high_timestamps: List[float] = []
        self._low_timestamps: List[float] = []
        self._vol_tracker = VolumeTracker()
        self._volume_spikes: Dict[str, float] = {}
        # NOTE: _poll() must only be called from a single executor at a time.
        # _high_timestamps and _low_timestamps are not thread-safe for concurrent mutation.
        # Rate-limit backoff state
        self._backoff_until: float = 0.0
        self._backoff_secs: float = 5.0
        self._semaphore = asyncio.Semaphore(3)

    async def connect(self) -> None:
        pass  # no persistent connection needed for polling

    async def stream(self) -> AsyncIterator[dict]:
        while True:
            try:
                # Single producer: only one executor call in flight at a time (await ensures this).
                result = await asyncio.get_running_loop().run_in_executor(
                    None, self._poll
                )
                if result is not None:
                    yield {"type": "HIGHLOW_UPDATE", "data": result}
            except Exception as e:
                import sys
                print(f"[YahooFinanceProvider] poll error: {e}", file=sys.stderr)
            await asyncio.sleep(self.poll_interval)

    async def disconnect(self) -> None:
        pass

    def get_metadata(self) -> dict:
        return {
            "name": "Yahoo Finance",
            "refresh_rate": self.poll_interval,
            "is_realtime": False,
        }

    def _mark_rate_limited(self) -> None:
        """Called on HTTP 429. Doubles backoff, caps at 60s."""
        self._backoff_until = time.time() + self._backoff_secs
        self._backoff_secs = min(self._backoff_secs * 2, 60.0)

    def is_rate_limited(self) -> bool:
        return time.time() < self._backoff_until

    def _reset_backoff(self) -> None:
        self._backoff_secs = 5.0
        self._backoff_until = 0.0

    def _poll(self) -> Optional[dict]:
        if self.is_rate_limited():
            return None  # Skip poll, return stale

        try:
            data = yf.download(
                tickers=self.symbols,
                period="1d",
                interval="1m",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as e:
            if "429" in str(e) or "Too Many" in str(e):
                self._mark_rate_limited()
            return None

        if data is None or data.empty:
            return None

        last_high: Dict[str, float] = {}
        last_low: Dict[str, float] = {}
        current_prices: Dict[str, float] = {}
        percent_change: Dict[str, float] = {}
        ts = time.time()

        for sym in self.symbols:
            try:
                sym_data = data[sym]
                if sym_data.empty:
                    continue

                session_high = float(sym_data["High"].max())
                session_low = float(sym_data["Low"].min())
                current_price = float(sym_data["Close"].iloc[-1])
                open_price = float(sym_data["Open"].iloc[0])
                bar_volume = float(sym_data["Volume"].iloc[-1] or 0)

                ratio = self._vol_tracker.record(sym, bar_volume, ts)
                if ratio is not None:
                    if ratio > 1.0:
                        self._volume_spikes[sym] = ratio
                    else:
                        self._volume_spikes.pop(sym, None)

                pct = (
                    round((current_price - open_price) / open_price * 100, 2)
                    if open_price else 0.0
                )
                percent_change[sym] = pct
                current_prices[sym] = current_price
                last_high[sym] = session_high
                last_low[sym] = session_low

                if sym not in self._session_highs:
                    # First poll — set baseline, emit nothing
                    self._session_highs[sym] = session_high
                    self._session_lows[sym] = session_low
                    self._high_counts[sym] = 0
                    self._low_counts[sym] = 0
                else:
                    if session_high > self._session_highs[sym]:
                        self._high_counts[sym] += 1
                        self._session_highs[sym] = session_high
                        self._high_timestamps.append(ts)

                    if session_low < self._session_lows[sym]:
                        self._low_counts[sym] += 1
                        self._session_lows[sym] = session_low
                        self._low_timestamps.append(ts)

            except Exception as e:
                import sys
                print(f"[YahooFinanceProvider] error processing {sym}: {e}", file=sys.stderr)
                continue

        # Pass full cumulative count dicts — _apply_highlow_update computes delta
        new_highs = {s: c for s, c in self._high_counts.items() if c > 0}
        new_lows = {s: c for s, c in self._low_counts.items() if c > 0}

        cutoff = ts - PRUNE_WINDOW
        self._high_timestamps = [t for t in self._high_timestamps if t > cutoff]
        self._low_timestamps = [t for t in self._low_timestamps if t > cutoff]

        high_counts = wall_clock_counts(self._high_timestamps)
        low_counts  = wall_clock_counts(self._low_timestamps)

        self._reset_backoff()
        return {
            "newHighs": new_highs,
            "newLows": new_lows,
            "lastHigh": last_high,
            "lastLow": last_low,
            "week52Highs": [],  # not computed in free tier
            "week52Lows": [],
            "percentChange": percent_change,
            "highCounts": high_counts,
            "lowCounts": low_counts,
            "indexPrices": {
                "SPY": current_prices.get("SPY", 0.0),
                "DIA": current_prices.get("DIA", 0.0),
                "QQQ": current_prices.get("QQQ", 0.0),
            },
            "volumeSpikes": dict(self._volume_spikes),
        }
