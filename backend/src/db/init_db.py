"""数据库建表与索引初始化。"""
from __future__ import annotations

import aiosqlite

from src.db.connection import get_connection

SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    id              TEXT PRIMARY KEY,
    run_date        TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'EXECUTED',
    risk_verdict    TEXT,
    risk_rounds     INTEGER NOT NULL DEFAULT 0,
    evidence_rounds INTEGER NOT NULL DEFAULT 0,
    review_notes    TEXT,
    error_message   TEXT,
    created_at      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            TEXT    NOT NULL,
    run_date          TEXT    NOT NULL,
    ticker            TEXT    NOT NULL,
    reasoning         TEXT    NOT NULL,
    sentiment_score   INTEGER NOT NULL CHECK(sentiment_score BETWEEN 1 AND 10),
    action            TEXT    NOT NULL CHECK(action IN ('BUY', 'HOLD', 'SELL')),
    price_at_analysis REAL    NOT NULL,
    created_at        TEXT    NOT NULL,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trades (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL,
    run_date     TEXT    NOT NULL,
    ticker       TEXT    NOT NULL,
    side         TEXT    NOT NULL CHECK(side IN ('BUY', 'SELL')),
    price        REAL    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'EXECUTED' CHECK(status IN ('EXECUTED', 'CANCELLED')),
    executed_at  TEXT    NOT NULL,
    cancelled_at TEXT,
    FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recommendations_run_id      ON recommendations(run_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_ticker      ON recommendations(ticker);
CREATE INDEX IF NOT EXISTS idx_recommendations_run_date    ON recommendations(run_date);
CREATE INDEX IF NOT EXISTS idx_recommendations_ticker_date ON recommendations(ticker, run_date);
CREATE INDEX IF NOT EXISTS idx_trades_run_id               ON trades(run_id);
CREATE INDEX IF NOT EXISTS idx_trades_run_date             ON trades(run_date);
CREATE INDEX IF NOT EXISTS idx_trades_ticker               ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_status               ON trades(status);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_date          ON analysis_runs(run_date);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_status        ON analysis_runs(status);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_risk_verdict  ON analysis_runs(risk_verdict);
"""


async def init_db(conn: aiosqlite.Connection | None = None) -> None:
    """创建所有表与索引（幂等）。

    若不传 conn，则自建一个连接并在结束时关闭。
    """
    own = conn is None
    db = conn or await get_connection()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
    finally:
        if own:
            await db.close()
