"""AlpacaBroker stub — implement for live trading."""
from .base import BrokerBase, FlattenResult, Order, Position
from typing import Optional


class AlpacaBroker(BrokerBase):
    """Live equity/crypto broker via Alpaca Markets.

    Setup:
        pip install alpaca-py
        .env: ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER=true
    """

    async def submit_order(self, symbol, side, qty, order_type, limit_price=None):
        raise NotImplementedError("AlpacaBroker not configured. See brokers/alpaca_broker.py")

    async def cancel_order(self, order_id):
        raise NotImplementedError

    async def get_positions(self):
        raise NotImplementedError

    async def flatten_all(self):
        raise NotImplementedError

    async def get_equity(self):
        raise NotImplementedError
