# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Pre-implementation. The full spec is in `spec.md` (v1.2); design docs are in `doc/`. No source code or project scaffolding exists yet.

## What We're Building

A **monorepo** with a Python multi-agent backend (LangGraph + LangChain) and a Vue3 web frontend. The backend tracks the Top 10 global AI companies, aggregates news/financial data, generates quant analysis, and requires human approval before simulated trade execution. Results are persisted in SQLite and exposed via a REST API. The frontend lets a human browse recommendation history, review the AI analysis, and click to approve/reject today's trades.

> Disclaimer: research/demo only. All "trades" are simulated and this is not investment advice. No auth in MVP.

## Monorepo Layout

```
ai-stock-assistant/
├── backend/    # Python / FastAPI / LangGraph (code under backend/src/)
└── frontend/   # Vue3 + Ant Design Vue + Vite + TS
```

## Tech Stack

Backend:
- Python 3.10+, LangGraph / LangChain (StateGraph, conditional edges)
- LangGraph Checkpointer (SqliteSaver / AsyncSqliteSaver) for interrupt/resume
- LLM: Anthropic Claude or OpenAI GPT-4o (structured output via Pydantic)
- FastAPI + Uvicorn (REST API, CORS enabled), SQLite + aiosqlite
- `yfinance` for stock data, `Tavily` or `DuckDuckGo Search` for news

Frontend:
- Vue 3 (Composition API, `<script setup>`), Ant Design Vue 4.x
- Vite, Vue Router 4, Pinia, axios, TypeScript
- No authentication in MVP

## Target Tickers

AAPL, MSFT, NVDA, GOOGL, META, TSLA, AMD, TSM, ASML, AVGO

## Graph Architecture (Conditional State Machine)

A LangGraph StateGraph with conditional branching. **Persistence is placed BEFORE approval** so the frontend can display pending analyses for review:

1. **News_Scraper_Node** — top 3 news + current price per ticker
2. **Quant_Analyst_Node** — LLM structured output (Pydantic): `Reasoning`, `Sentiment_Score` (1-10), `Action` (BUY/HOLD/SELL)
3. **Data_Persistence_Node** — writes `analysis_runs` (status=PENDING) + `recommendations` BEFORE approval
4. **Human_Approval_Node** — `interrupt_before` + checkpointer; CLI waits for Y/N, server mode resumes via approve API
5. **Finalize_Node** — updates run status to APPROVED/REJECTED (+ approved_at)
6. **Mock_Execution_Node** — runs only on APPROVED
7. **Error_Handler_Node** — marks run ERROR on exception

Flow: scraper → analyst → persist(PENDING) → [interrupt] approval → finalize → (APPROVED→mock_execution→END | REJECTED→END). Exceptions → error_handler → END.

## State Shape

```python
class AgentState(TypedDict):
    tickers: List[str]
    raw_news_data: Dict[str, TickerNews]      # news + price
    analyses: List[TickerAnalysis]            # structured results
    analysis_report: str
    approval_status: str  # "PENDING" | "APPROVED" | "REJECTED" | "ERROR"
    run_id: Optional[str]  # UUID generated at init, also LangGraph thread_id
    error_message: Optional[str]
```

## Database (SQLite)

Two tables: `analysis_runs` (one row per run; status PENDING→APPROVED/REJECTED/ERROR; `error_message`) and `recommendations` (one row per ticker per run; redundant `run_date` for efficient date queries). FK `run_id` uses `ON DELETE CASCADE`; enable `PRAGMA foreign_keys=ON`. LangGraph checkpoints persisted to SQLite (thread_id = run_id).

## REST API (under `/api/`, CORS enabled)

- `GET /api/recommendations/latest | /{date} | /ticker/{ticker}/latest | /ticker/{ticker}/history` (paginated)
- `GET /api/runs` (paginated, filter by status/date), `GET /api/runs/{run_id}` (run + its recommendations), `GET /api/runs/pending`
- `POST /api/run/trigger` (async, 202 + run_id)
- `POST /api/run/{run_id}/approve` (body `{"decision": "APPROVED" | "REJECTED"}`, resumes interrupted graph)

Unified response envelope with structured `error.code`/`error.message`; pagination via `page`/`page_size` in `meta`.

## Frontend Pages

- `/history` — recommendation history table (filter by status/date, paginated)
- `/pending` — PENDING runs awaiting review
- `/runs/:runId` — run detail / review; PENDING runs show approve/reject buttons calling the approve API

## Run Modes

- **CLI**: `cd backend && python -m src.main` — single interactive run with Y/N approval
- **Server**: `cd backend && python -m src.main --serve` — FastAPI server; runs trigger async, write PENDING, interrupt, then resume via approve API
- **Frontend dev**: `cd frontend && npm run dev` — Vite dev server on :5173, proxies `/api` → :8000
