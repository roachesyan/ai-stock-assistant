# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Pre-implementation. The full spec is in `spec.md` (v1.4); design docs are in `doc/`. No source code or project scaffolding exists yet.

## What We're Building

A **monorepo** with a Python multi-agent backend (LangGraph + LangChain) and a Vue3 web frontend. The backend tracks the Top 10 global AI companies, aggregates news/financial data, and runs a **two-agent pipeline with three bounded loops**: an Analyst agent proposes trades, a Risk Reviewer agent vets them (AI replaces the old human approval), and approved trades are **auto-executed**. Humans intervene only **after the fact by cancelling trades, and only for the same day**. Results are persisted in SQLite and exposed via a REST API. The frontend lets a human browse recommendation history, read the AI risk verdict, view today's auto-executed trades, and cancel same-day trades.

> Disclaimer: research/demo only. All "trades" are simulated AND auto-executed after AI risk review. Not investment advice. No auth in MVP.

## Monorepo Layout

```
ai-stock-assistant/
├── backend/    # Python / FastAPI / LangGraph (code under backend/src/)
└── frontend/   # Vue3 + Ant Design Vue + Vite + TS
```

## Why LangGraph/LangChain

v1.4 reintroduces real graph value: three bounded loops (cycles + conditional edges + termination conditions). LangGraph orchestrates the loops; LangChain handles the LLM abstraction and structured output. No Checkpointer needed — all loops complete within a single `invoke` (no human interrupts).

## Tech Stack

Backend:
- Python 3.10+, LangGraph / LangChain (StateGraph **with cycles + conditional edges**)
- LLM: **GLM (glm-5.1) by default via its Anthropic-compatible endpoint** (reuses `langchain-anthropic`); also supports official Anthropic Claude or OpenAI GPT-4o. Switch via `LLM_PROVIDER` (glm | anthropic | openai). Structured output via Pydantic; two agents: analyst + risk reviewer.
- FastAPI + Uvicorn (REST API, CORS enabled), SQLite + aiosqlite
- `yfinance` for stock data, `Tavily` or `DuckDuckGo Search` for news

Frontend:
- Vue 3 (Composition API, `<script setup>`), Ant Design Vue 4.x
- Vite, Vue Router 4, Pinia, axios, TypeScript
- No authentication in MVP

## Target Tickers

AAPL, MSFT, NVDA, GOOGL, META, TSLA, AMD, TSM, ASML, AVGO

## Graph Architecture (Multi-Agent, Three Bounded Loops)

Nodes: news_scraper → quant_analyst → (evidence/risk loops) → data_persistence → auto_execution → END; exceptions → error_handler → END.

Three bounded loops:
1. **Structured-output self-repair** (inside `quant_analyst`): on Pydantic schema validation failure, retry with the error as feedback, up to `MAX_SCHEMA_RETRIES` (default 2).
2. **Evidence-gathering loop**: analyst returns `needs_more_evidence`; if non-empty and `evidence_rounds < MAX_EVIDENCE_ROUNDS` (default 2) → `evidence_gatherer` does extra searches → back to analyst.
3. **Risk-reflection loop**: `risk_reviewer` (independent agent) checks over-aggressive positioning, contradiction with news, sentiment/action consistency. If rejected and `risk_rounds < MAX_RISK_ROUNDS` (default 3) → back to analyst with `risk_feedback`; if approved or rounds exhausted → proceed.

Routing: `route_after_analyst` (evidence vs risk), `route_after_risk` (approve→persist | reject&under-limit→analyst | reject&limit→persist).

**Risk limit policy** (`RISK_LIMIT_POLICY`):
- `EXECUTE_AND_FLAG` (default): execute anyway, mark `analysis_runs.risk_verdict = REJECTED_AT_LIMIT`, frontend warns, human can cancel same-day.
- `DOWNGRADE_TO_HOLD`: drop risk-rejected BUY/SELL (no trade); execute the rest.

Approved runs get `risk_verdict = APPROVED`.

**Cancellation (post-hoc, not part of the graph):** a trade is cancellable only if it exists, `run_date == server today`, and `status == EXECUTED`. Cancelling sets `trades.status = CANCELLED` (+ `cancelled_at`) and never modifies recommendations/runs.

## State Shape

```python
class AgentState(TypedDict):
    tickers: List[str]
    raw_news_data: Dict[str, TickerNews]      # news + price (evidence loop appends)
    analyses: List[TickerAnalysis]            # revised each loop
    analysis_report: str
    needs_more_evidence: List[str]            # evidence loop trigger
    evidence_rounds: int                      # evidence loop counter
    risk_review: Optional[RiskReview]         # approved / issues / overall_notes
    risk_feedback: Optional[str]              # back to analyst on reject
    risk_rounds: int                          # risk loop counter
    risk_verdict: Optional[str]               # APPROVED | REJECTED_AT_LIMIT
    executed_trades: List[TradeExecution]
    run_id: Optional[str]  # UUID at init
    error_message: Optional[str]
```

## Database (SQLite)

Three tables:
- `analysis_runs` — status EXECUTED/ERROR; plus `risk_verdict` (APPROVED/REJECTED_AT_LIMIT), `risk_rounds`, `evidence_rounds`, `review_notes` (serialized risk review).
- `recommendations` — one row per ticker per run (incl. HOLD), final revised version; redundant `run_date`.
- `trades` — one row per auto-executed BUY/SELL; `side`, `price`, `status` (EXECUTED/CANCELLED), `executed_at`, `cancelled_at`; redundant `run_date` for same-day cancel checks.

FK `run_id` uses `ON DELETE CASCADE`; enable `PRAGMA foreign_keys=ON`.

## REST API (under `/api/`, CORS enabled)

- `GET /api/recommendations/latest | /{date} | /ticker/{ticker}/latest | /ticker/{ticker}/history` (paginated)
- `GET /api/runs` (paginated, filter status/date/risk_verdict), `GET /api/runs/{run_id}` (run + risk_review + recommendations + trades)
- `POST /api/run/trigger` (async, 202 + run_id; runs all loops + auto-execution to completion)
- `POST /api/runs/{run_id}/cancel` (batch-cancel same-day EXECUTED trades)
- `GET /api/trades` (paginated, filter run_id/ticker/status/date), `GET /api/trades/today` (with `cancellable` flag)
- `POST /api/trades/{trade_id}/cancel` (same-day only; 404 TRADE_NOT_FOUND / 409 TRADE_NOT_CANCELLABLE)

Unified response envelope with structured `error.code`/`error.message`; pagination via `page`/`page_size` in `meta`.

## Config (LLM provider + loop bounds + risk policy)

LLM provider (default GLM):
- `LLM_PROVIDER=glm` (default) | `anthropic` | `openai`
- GLM uses the Anthropic-compatible endpoint, so `get_llm()` returns `ChatAnthropic(model=GLM_MODEL, api_key=GLM_API_KEY, base_url=GLM_BASE_URL)`.
- Env: `GLM_API_KEY` (form `id.secret`), `GLM_BASE_URL=https://open.bigmodel.cn/api/anthropic`, `GLM_MODEL=glm-5.1`, `LLM_TIMEOUT_MS` (GLM can be slow, e.g. 3000000).
- These are the project's OWN vars — NOT Claude Code CLI's `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_DEFAULT_*_MODEL` / `CLAUDE_CODE_*`.
- Fallback if GLM's tool-calling (used by `with_structured_output`) is unstable: switch to GLM's OpenAI-compatible endpoint (`LLM_PROVIDER=openai`, `OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4`, `OPENAI_MODEL=glm-5.1`).
- Never commit real tokens; `.env` is gitignored.

Loop bounds / risk policy: `MAX_SCHEMA_RETRIES` (2), `MAX_EVIDENCE_ROUNDS` (2), `MAX_RISK_ROUNDS` (3), `RISK_LIMIT_POLICY` (EXECUTE_AND_FLAG | DOWNGRADE_TO_HOLD).

Scheduling (server mode only, APScheduler in-process): `SCHEDULE_ENABLED` (false), `SCHEDULE_CRON` (`30 9 * * 1-5`), `SCHEDULE_TIMEZONE` (`America/New_York`), `MARKET_CALENDAR` (`XNYS`), `SKIP_NON_TRADING_DAYS` (true). The scheduled job (`src/scheduler.py`) gates on `is_trading_day` (pandas-market-calendars, skips weekends + holidays), then calls the same `run_pipeline` as the trigger API. Single-instance assumption; re-entrancy guarded.

## Frontend Pages

- `/history` — run history (filter by status/date/risk_verdict; risk verdict shown as a tag)
- `/today` — today's auto-executed trades with cancel buttons (same-day only)
- `/runs/:runId` — run detail: RiskReviewCard (verdict/issues/notes) + recommendations + trades; same-day trades cancellable

## Run Modes

- **CLI**: `cd backend && python -m src.main` — single non-interactive run; scrape →(analyst↔evidence)→(analyst↔risk)→ persist → auto-execute → exit
- **Server**: `cd backend && python -m src.main --serve` — FastAPI server; runs trigger async and complete (all loops + auto-execution); humans cancel same-day trades via API
- **Frontend dev**: `cd frontend && npm run dev` — Vite dev server on :5173, proxies `/api` → :8000
```
