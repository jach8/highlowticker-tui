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
