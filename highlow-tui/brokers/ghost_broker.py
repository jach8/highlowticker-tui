"""GhostBroker — SQLite-backed paper trading engine."""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from .base import BrokerBase, FlattenResult, Order, Position

_DEFAULT_DB = Path.home() / ".sovereign" / "ghost_trades.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT    NOT NULL,
    direction     TEXT    NOT NULL,
    entry_price   REAL    NOT NULL,
    qty           REAL    NOT NULL,
    entry_time    REAL    NOT NULL,
    score_at_entry REAL   NOT NULL,
    label_at_entry TEXT   NOT NULL,
    algo_version  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT,
    direction     TEXT,
    entry_price   REAL,
    exit_price    REAL,
    qty           REAL,
    pnl           REAL,
    entry_time    REAL,
    exit_time     REAL,
    duration_secs REAL,
    exit_reason   TEXT,
    score_at_entry REAL,
    label_at_entry TEXT,
    algo_version  INTEGER DEFAULT 1,
    slippage_pct  REAL
);

CREATE TABLE IF NOT EXISTS stats (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    equity          REAL    DEFAULT 100000.0,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    gross_profit    REAL    DEFAULT 0.0,
    gross_loss      REAL    DEFAULT 0.0,
    max_drawdown_pct REAL   DEFAULT 0.0,
    peak_equity     REAL    DEFAULT 100000.0,
    updated_at      REAL    DEFAULT 0
);

INSERT OR IGNORE INTO stats (id) VALUES (1);
"""

_SL_PCT = 0.75   # stop-loss %
_TP_PCT = 1.5    # take-profit %
_MAX_HOLD_SECS = 1800  # 30 minutes


class GhostBroker(BrokerBase):
    def __init__(self, db_path: Path = _DEFAULT_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ── BrokerBase interface ──────────────────────────────────────────

    async def submit_order(
        self, symbol: str, side: str, qty: float,
        order_type: str, limit_price: Optional[float] = None,
    ) -> Order:
        return Order(
            order_id=uuid.uuid4().hex[:8], symbol=symbol,
            side=side, qty=qty, order_type=order_type, status="filled",
        )

    async def cancel_order(self, order_id: str) -> bool:
        return True

    async def get_positions(self) -> list[Position]:
        rows = self._conn.execute(
            "SELECT symbol, direction, entry_price, qty FROM positions"
        ).fetchall()
        return [
            Position(symbol=r[0], direction=r[1], entry_price=r[2],
                     qty=r[3], current_price=r[2])  # paper broker: current_price = entry_price (no live feed)
            for r in rows
        ]

    async def flatten_all(self) -> FlattenResult:
        rows = self._conn.execute(
            "SELECT id, symbol, direction, entry_price, qty, entry_time, "
            "score_at_entry, label_at_entry "
            "FROM positions"
        ).fetchall()
        count = len(rows)
        exposure = sum(r[3] * r[4] for r in rows)  # entry_price * qty
        now = time.time()
        for pos_id, symbol, direction, entry_price, qty, entry_time, score, label in rows:
            # Record as a flat exit (PnL=0, exit at entry price — no live feed)
            self._conn.execute(
                "INSERT INTO trades "
                "(symbol, direction, entry_price, exit_price, qty, pnl, "
                "entry_time, exit_time, duration_secs, exit_reason, "
                "score_at_entry, label_at_entry, slippage_pct) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (symbol, direction, entry_price, entry_price, qty,
                 0.0, entry_time, now, now - entry_time, "FLATTEN",
                 score, label, 0.0),
            )
            self._update_stats(0.0)
        self._conn.execute("DELETE FROM positions")
        self._conn.commit()
        return FlattenResult(
            positions_closed=count, orders_cancelled=0, total_exposure=exposure
        )

    async def get_equity(self) -> float:
        row = self._conn.execute(
            "SELECT equity FROM stats WHERE id=1"
        ).fetchone()
        return row[0] if row else 100_000.0

    # ── Ghost-specific methods ───────────────────────────────────────

    async def enter_long(
        self, symbol: str, price: float, score: float, label: str
    ) -> None:
        equity = await self.get_equity()
        qty = self._kelly_size(equity) / max(price, 0.01)
        self._conn.execute(
            "INSERT INTO positions "
            "(symbol, direction, entry_price, qty, entry_time, score_at_entry, label_at_entry) "
            "VALUES (?,?,?,?,?,?,?)",
            (symbol, "LONG", price, qty, time.time(), score, label),
        )
        self._conn.commit()

    async def check_exits(self, symbol: str, current_price: float) -> None:
        """Evaluate SL / TP / max-hold for all open positions in symbol."""
        now = time.time()
        rows = self._conn.execute(
            "SELECT id, direction, entry_price, qty, entry_time, "
            "score_at_entry, label_at_entry "
            "FROM positions WHERE symbol=?",
            (symbol,),
        ).fetchall()

        for pos_id, direction, entry_price, qty, entry_time, score, label in rows:
            if direction == "LONG":
                pnl_pct = (current_price - entry_price) / entry_price * 100
            else:
                pnl_pct = (entry_price - current_price) / entry_price * 100

            exit_reason: Optional[str] = None
            target_pct: float = 0.0
            if pnl_pct <= -_SL_PCT:
                exit_reason, target_pct = "SL", -_SL_PCT
            elif pnl_pct >= _TP_PCT:
                exit_reason, target_pct = "TP", _TP_PCT
            elif (now - entry_time) >= _MAX_HOLD_SECS:
                exit_reason, target_pct = "MAX_HOLD", pnl_pct

            if exit_reason:
                raw_pnl = pnl_pct / 100 * entry_price * qty
                slippage = abs(pnl_pct - target_pct)
                self._conn.execute(
                    "INSERT INTO trades "
                    "(symbol, direction, entry_price, exit_price, qty, pnl, "
                    "entry_time, exit_time, duration_secs, exit_reason, "
                    "score_at_entry, label_at_entry, slippage_pct) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        symbol, direction, entry_price, current_price, qty,
                        raw_pnl, entry_time, now, now - entry_time, exit_reason,
                        score, label, slippage,
                    ),
                )
                self._conn.execute(
                    "DELETE FROM positions WHERE id=?", (pos_id,)
                )
                self._update_stats(raw_pnl)

        self._conn.commit()

    def get_stats(self) -> dict:
        row = self._conn.execute(
            "SELECT equity, total_trades, winning_trades, "
            "gross_profit, gross_loss, max_drawdown_pct "
            "FROM stats WHERE id=1"
        ).fetchone()
        if not row:
            return {}
        equity, total, wins, gp, gl, maxdd = row
        win_rate = (wins / total * 100) if total > 0 else 0.0
        losses = total - wins
        profit_factor = (gp / abs(gl)) if gl != 0 and losses > 0 else (float("inf") if wins > 0 else 0.0)
        return {
            "equity": equity,
            "total_trades": total,
            "winning_trades": wins,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "max_drawdown_pct": maxdd,
            "gross_profit": gp,
            "gross_loss": gl,
        }

    def close(self) -> None:
        self._conn.close()

    # ── Private ───────────────────────────────────────────────────────

    def _kelly_size(self, equity: float) -> float:
        row = self._conn.execute(
            "SELECT total_trades, winning_trades, gross_profit, gross_loss "
            "FROM stats WHERE id=1"
        ).fetchone()
        if not row or row[0] < 10:
            return equity * 0.01  # Warmup: fixed 1%
        total, wins, gp, gl = row
        losses = total - wins
        if wins == 0 or losses == 0 or gl == 0:
            return equity * 0.01
        win_rate = wins / total
        payoff = (gp / wins) / (abs(gl) / losses)
        kelly = 0.5 * (win_rate - (1 - win_rate) / payoff)
        kelly = max(0.0025, min(0.02, kelly))
        return equity * kelly

    def _update_stats(self, pnl: float) -> None:
        row = self._conn.execute(
            "SELECT equity, total_trades, winning_trades, "
            "gross_profit, gross_loss, peak_equity "
            "FROM stats WHERE id=1"
        ).fetchone()
        equity, total, wins, gp, gl, peak = row
        equity += pnl
        total += 1
        if pnl > 0:
            wins += 1
            gp += pnl
        else:
            gl += pnl
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100 if peak > 0 else 0.0
        self._conn.execute(
            "UPDATE stats SET equity=?, total_trades=?, winning_trades=?, "
            "gross_profit=?, gross_loss=?, "
            "max_drawdown_pct=MAX(max_drawdown_pct, ?), "
            "peak_equity=?, updated_at=? WHERE id=1",
            (equity, total, wins, gp, gl, drawdown, peak, time.time()),
        )
        self._conn.commit()
