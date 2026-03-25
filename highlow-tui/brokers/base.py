"""Abstract broker interface — implement for Alpaca, Binance, Ghost, etc."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Order:
    order_id: str
    symbol: str
    side: str           # 'buy' | 'sell'
    qty: float
    order_type: str     # 'market' | 'limit'
    status: str         # 'pending' | 'filled' | 'cancelled'
    limit_price: Optional[float] = None


@dataclass
class Position:
    symbol: str
    qty: float
    direction: str      # 'LONG' | 'SHORT'
    entry_price: float
    current_price: float

    @property
    def unrealized_pnl(self) -> float:
        if self.direction == "LONG":
            return (self.current_price - self.entry_price) * self.qty
        return (self.entry_price - self.current_price) * self.qty


@dataclass
class FlattenResult:
    positions_closed: int
    orders_cancelled: int
    total_exposure: float


class BrokerBase(ABC):
    @abstractmethod
    async def submit_order(
        self, symbol: str, side: str, qty: float,
        order_type: str, limit_price: Optional[float] = None,
    ) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    async def get_positions(self) -> list[Position]: ...

    @abstractmethod
    async def flatten_all(self) -> FlattenResult: ...

    @abstractmethod
    async def get_equity(self) -> float: ...
