"""数据访问层（Repository 模式）。封装 runs / recommendations / trades 的 CRUD。"""
from __future__ import annotations

import math
from typing import Any

import aiosqlite

from src.utils.dates import now_iso


def _row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _rows_to_dicts(rows) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


class AnalysisRepository:
    """所有数据库读写的入口。持有一个 aiosqlite 连接。"""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    # ----------------------------------------------------------------
    # analysis_runs
    # ----------------------------------------------------------------
    async def create_run(
        self,
        run_id: str,
        run_date: str,
        status: str = "EXECUTED",
        risk_verdict: str | None = None,
        risk_rounds: int = 0,
        evidence_rounds: int = 0,
        review_notes: str | None = None,
        created_at: str | None = None,
    ) -> None:
        await self.conn.execute(
            """
            INSERT INTO analysis_runs
                (id, run_date, status, risk_verdict, risk_rounds,
                 evidence_rounds, review_notes, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                risk_verdict=excluded.risk_verdict,
                risk_rounds=excluded.risk_rounds,
                evidence_rounds=excluded.evidence_rounds,
                review_notes=excluded.review_notes
            """,
            (
                run_id, run_date, status, risk_verdict, risk_rounds,
                evidence_rounds, review_notes, created_at or now_iso(),
            ),
        )
        await self.conn.commit()

    async def update_run_status(
        self, run_id: str, status: str, error_message: str | None = None
    ) -> None:
        await self.conn.execute(
            "UPDATE analysis_runs SET status = ?, error_message = ? WHERE id = ?",
            (status, error_message, run_id),
        )
        await self.conn.commit()

    async def ensure_run(self, run_id: str, run_date: str) -> None:
        """若 run 不存在则以 ERROR 占位创建（供 Error_Handler 兜底）。"""
        await self.conn.execute(
            """
            INSERT INTO analysis_runs (id, run_date, status, created_at)
            VALUES (?, ?, 'ERROR', ?)
            ON CONFLICT(id) DO NOTHING
            """,
            (run_id, run_date, now_iso()),
        )
        await self.conn.commit()

    async def get_run_by_id(self, run_id: str) -> dict[str, Any] | None:
        async with self.conn.execute(
            "SELECT * FROM analysis_runs WHERE id = ?", (run_id,)
        ) as cur:
            return _row_to_dict(await cur.fetchone())

    async def _counts_for_run(self, run_id: str) -> tuple[int, int]:
        async with self.conn.execute(
            "SELECT COUNT(*) AS c FROM recommendations WHERE run_id = ?", (run_id,)
        ) as cur:
            rec_count = (await cur.fetchone())["c"]
        async with self.conn.execute(
            "SELECT COUNT(*) AS c FROM trades WHERE run_id = ?", (run_id,)
        ) as cur:
            trade_count = (await cur.fetchone())["c"]
        return rec_count, trade_count

    async def get_run_with_details(self, run_id: str) -> dict[str, Any] | None:
        run = await self.get_run_by_id(run_id)
        if run is None:
            return None
        async with self.conn.execute(
            "SELECT * FROM recommendations WHERE run_id = ? ORDER BY ticker", (run_id,)
        ) as cur:
            recs = _rows_to_dicts(await cur.fetchall())
        async with self.conn.execute(
            "SELECT * FROM trades WHERE run_id = ? ORDER BY id", (run_id,)
        ) as cur:
            trades = _rows_to_dicts(await cur.fetchall())
        run["recommendations"] = recs
        run["trades"] = trades
        run["recommendation_count"] = len(recs)
        run["trade_count"] = len(trades)
        return run

    async def list_runs(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        date: str | None = None,
        risk_verdict: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if date:
            where.append("run_date = ?")
            params.append(date)
        if risk_verdict:
            where.append("risk_verdict = ?")
            params.append(risk_verdict)
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        async with self.conn.execute(
            f"SELECT COUNT(*) AS c FROM analysis_runs {clause}", params
        ) as cur:
            total = (await cur.fetchone())["c"]

        offset = (page - 1) * page_size
        async with self.conn.execute(
            f"""
            SELECT * FROM analysis_runs {clause}
            ORDER BY created_at DESC, run_date DESC
            LIMIT ? OFFSET ?
            """,
            [*params, page_size, offset],
        ) as cur:
            runs = _rows_to_dicts(await cur.fetchall())

        for run in runs:
            rec_count, trade_count = await self._counts_for_run(run["id"])
            run["recommendation_count"] = rec_count
            run["trade_count"] = trade_count
        return runs, total

    # ----------------------------------------------------------------
    # recommendations
    # ----------------------------------------------------------------
    async def save_recommendations(
        self, run_id: str, run_date: str, recommendations: list[dict[str, Any]]
    ) -> None:
        created = now_iso()
        await self.conn.executemany(
            """
            INSERT INTO recommendations
                (run_id, run_date, ticker, reasoning, sentiment_score,
                 action, price_at_analysis, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id, run_date, r["ticker"], r["reasoning"],
                    int(r["sentiment_score"]), r["action"],
                    float(r["price_at_analysis"]), created,
                )
                for r in recommendations
            ],
        )
        await self.conn.commit()

    async def get_latest_recommendations(self) -> list[dict[str, Any]]:
        async with self.conn.execute(
            "SELECT run_date FROM analysis_runs ORDER BY created_at DESC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return []
        return await self.get_recommendations_by_date(row["run_date"])

    async def get_recommendations_by_date(self, date: str) -> list[dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM recommendations WHERE run_date = ? ORDER BY ticker", (date,)
        ) as cur:
            return _rows_to_dicts(await cur.fetchall())

    async def get_latest_by_ticker(self, ticker: str) -> dict[str, Any] | None:
        async with self.conn.execute(
            """
            SELECT * FROM recommendations WHERE ticker = ?
            ORDER BY run_date DESC, id DESC LIMIT 1
            """,
            (ticker,),
        ) as cur:
            return _row_to_dict(await cur.fetchone())

    async def get_ticker_history(
        self, ticker: str, page: int = 1, page_size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        async with self.conn.execute(
            "SELECT COUNT(*) AS c FROM recommendations WHERE ticker = ?", (ticker,)
        ) as cur:
            total = (await cur.fetchone())["c"]
        offset = (page - 1) * page_size
        async with self.conn.execute(
            """
            SELECT * FROM recommendations WHERE ticker = ?
            ORDER BY run_date DESC, id DESC LIMIT ? OFFSET ?
            """,
            (ticker, page_size, offset),
        ) as cur:
            return _rows_to_dicts(await cur.fetchall()), total

    # ----------------------------------------------------------------
    # trades
    # ----------------------------------------------------------------
    async def save_trades(
        self, run_id: str, run_date: str, trades: list[dict[str, Any]]
    ) -> None:
        if not trades:
            return
        executed = now_iso()
        await self.conn.executemany(
            """
            INSERT INTO trades
                (run_id, run_date, ticker, side, price, status, executed_at, cancelled_at)
            VALUES (?, ?, ?, ?, ?, 'EXECUTED', ?, NULL)
            """,
            [
                (run_id, run_date, t["ticker"], t["side"], float(t["price"]), executed)
                for t in trades
            ],
        )
        await self.conn.commit()

    async def get_trade_by_id(self, trade_id: int) -> dict[str, Any] | None:
        async with self.conn.execute(
            "SELECT * FROM trades WHERE id = ?", (trade_id,)
        ) as cur:
            return _row_to_dict(await cur.fetchone())

    async def list_trades(
        self,
        page: int = 1,
        page_size: int = 20,
        run_id: str | None = None,
        ticker: str | None = None,
        status: str | None = None,
        date: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        params: list[Any] = []
        if run_id:
            where.append("run_id = ?")
            params.append(run_id)
        if ticker:
            where.append("ticker = ?")
            params.append(ticker)
        if status:
            where.append("status = ?")
            params.append(status)
        if date:
            where.append("run_date = ?")
            params.append(date)
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        async with self.conn.execute(
            f"SELECT COUNT(*) AS c FROM trades {clause}", params
        ) as cur:
            total = (await cur.fetchone())["c"]
        offset = (page - 1) * page_size
        async with self.conn.execute(
            f"SELECT * FROM trades {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, page_size, offset],
        ) as cur:
            return _rows_to_dicts(await cur.fetchall()), total

    async def list_today_trades(self, today: str) -> list[dict[str, Any]]:
        async with self.conn.execute(
            "SELECT * FROM trades WHERE run_date = ? ORDER BY id DESC", (today,)
        ) as cur:
            return _rows_to_dicts(await cur.fetchall())

    async def cancel_trade(self, trade_id: int, cancelled_at: str) -> None:
        await self.conn.execute(
            "UPDATE trades SET status = 'CANCELLED', cancelled_at = ? WHERE id = ?",
            (cancelled_at, trade_id),
        )
        await self.conn.commit()

    async def cancel_run_trades(self, run_id: str, today: str, cancelled_at: str) -> int:
        cur = await self.conn.execute(
            """
            UPDATE trades SET status = 'CANCELLED', cancelled_at = ?
            WHERE run_id = ? AND run_date = ? AND status = 'EXECUTED'
            """,
            (cancelled_at, run_id, today),
        )
        await self.conn.commit()
        return cur.rowcount


def total_pages(total: int, page_size: int) -> int:
    return max(1, math.ceil(total / page_size)) if total else 0
