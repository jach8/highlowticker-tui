import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from unittest.mock import patch
import pandas as pd
from providers.yahoo_provider import YahooFinanceProvider

SYMBOLS = ["SPY", "AAPL", "TSLA"]


def _make_df(sym_data: dict) -> pd.DataFrame:
    """Build a fake multi-ticker yfinance DataFrame (MultiIndex columns)."""
    frames = {}
    for sym, (open_, high, low, close) in sym_data.items():
        frames[sym] = pd.DataFrame({
            "Open":  [open_],
            "High":  [high],
            "Low":   [low],
            "Close": [close],
            "Volume": [1_000_000],
        })
    return pd.concat(frames, axis=1)


def test_first_poll_initializes_no_new_highs_lows():
    """First poll sets baseline — no newHighs or newLows emitted."""
    provider = YahooFinanceProvider(SYMBOLS, poll_interval=90)
    fake_df = _make_df({
        "SPY":  (500.0, 502.0, 498.0, 501.0),
        "AAPL": (180.0, 182.0, 179.0, 181.0),
        "TSLA": (250.0, 253.0, 248.0, 251.0),
    })
    with patch("yfinance.download", return_value=fake_df):
        result = provider._poll()
    assert result is not None
    assert result["newHighs"] == {}
    assert result["newLows"] == {}


def test_second_poll_detects_new_high_and_low():
    """Second poll with higher/lower prices should produce newHighs/newLows."""
    provider = YahooFinanceProvider(SYMBOLS, poll_interval=90)
    baseline = _make_df({
        "SPY":  (500.0, 502.0, 498.0, 501.0),
        "AAPL": (180.0, 182.0, 179.0, 181.0),
        "TSLA": (250.0, 253.0, 248.0, 251.0),
    })
    updated = _make_df({
        "SPY":  (500.0, 505.0, 498.0, 504.0),   # new session high
        "AAPL": (180.0, 182.0, 179.0, 181.5),   # no change
        "TSLA": (250.0, 253.0, 246.0, 247.0),   # new session low
    })
    with patch("yfinance.download", return_value=baseline):
        provider._poll()
    with patch("yfinance.download", return_value=updated):
        result = provider._poll()

    assert "SPY" in result["newHighs"]
    assert result["newHighs"]["SPY"] == 1
    assert "AAPL" not in result["newHighs"]
    assert "TSLA" in result["newLows"]
    assert result["newLows"]["TSLA"] == 1


def test_cumulative_count_increments_across_polls():
    """newHighs count must be cumulative — not reset each poll."""
    provider = YahooFinanceProvider(["SPY"], poll_interval=90)
    poll_data = [
        {"SPY": (500.0, 502.0, 498.0, 501.0)},  # baseline
        {"SPY": (500.0, 505.0, 498.0, 504.0)},  # new high → count=1
        {"SPY": (500.0, 508.0, 498.0, 507.0)},  # new high again → count=2
    ]
    last_result = None
    for snap in poll_data:
        with patch("yfinance.download", return_value=_make_df(snap)):
            last_result = provider._poll()

    assert last_result["newHighs"]["SPY"] == 2


def test_output_shape_matches_highlow_update_contract():
    """Output must contain every key that _apply_highlow_update reads."""
    provider = YahooFinanceProvider(["SPY"], poll_interval=90)
    snap = {"SPY": (500.0, 502.0, 498.0, 501.0)}
    with patch("yfinance.download", return_value=_make_df(snap)):
        provider._poll()
    with patch("yfinance.download", return_value=_make_df({"SPY": (500.0, 506.0, 498.0, 505.0)})):
        result = provider._poll()

    required_keys = {"newHighs", "newLows", "lastHigh", "lastLow",
                     "percentChange", "highCounts", "lowCounts",
                     "week52Highs", "week52Lows", "indexPrices"}
    assert required_keys.issubset(result.keys())
    for tf in ("30s", "1m", "5m", "20m"):
        assert tf in result["highCounts"]
        assert tf in result["lowCounts"]


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
