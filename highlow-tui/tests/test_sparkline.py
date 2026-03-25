import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import deque
from core.sparkline import sparkline

def test_empty_returns_dashes():
    assert sparkline(deque()) == "—" * 20

def test_single_value_returns_mid_blocks():
    result = sparkline(deque([100.0]))
    assert all(c == "▄" for c in result)
    assert len(result) == 1

def test_all_same_price_returns_mid_block():
    d = deque([50.0, 50.0, 50.0, 50.0], maxlen=20)
    result = sparkline(d)
    assert all(c == "▄" for c in result)

def test_rising_prices_end_with_high_block():
    d = deque([1.0, 2.0, 3.0, 4.0, 5.0], maxlen=20)
    result = sparkline(d)
    assert result[-1] == "█"  # highest block for max price
    assert result[0] == "▁"   # lowest block for min price

def test_output_width_capped_at_20():
    d = deque(range(50), maxlen=20)
    result = sparkline(d)
    assert len(result) <= 20

def test_uses_last_20_prices():
    # 25 items but maxlen=20 keeps last 20
    d = deque(range(25), maxlen=20)
    result = sparkline(d)
    assert len(result) == 20
