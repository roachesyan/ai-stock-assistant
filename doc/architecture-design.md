# Architecture Design: AI Quant Agent v1.4 MVP

## 1. System Overview

AI Quant Agent 是一个基于 LangGraph + LangChain 的多智能体系统，用于追踪全球 Top 10 AI 公司，聚合每日新闻与金融数据。**分析师 Agent** 生成交易建议，**风控 Agent** 做 AI 审查（替代人工事前审批），通过后**自动模拟执行**买入/卖出。人工不事前审批，而是事后**撤销**已执行的交易，且**仅限当天的交易可撤销**。系统提供 **REST API** 与 **Web 前端**（Vue3 + Ant Design Vue），供人工查询推荐历史、查看 AI 风控结论、查看当日已执行交易并一键撤销。所有结果持久化到 **SQLite**。

项目采用 **monorepo** 结构：`backend/`（Python/FastAPI/LangGraph）与 `frontend/`（Vue3）。

整体编排是一个**带三个有界循环的状态机**：
1. 结构化输出自修复（节点内）；2. 证据补充环（图循环）；3. 风控反思环（图循环）。
这些「循环 + 条件分支 + 终止条件」正是 LangGraph 的核心价值所在。由于无人工中断，所有循环在单次 `invoke` 内同步完成，**不需要 Checkpointer**。

### 目标股票

| Ticker | Company |
|--------|---------|
| AAPL | Apple Inc. |
| MSFT | Microsoft Corp. |
| NVDA | NVIDIA Corp. |
| GOOGL | Alphabet Inc. |
| META | Meta Platforms |
| TSLA | Tesla Inc. |
| AMD | Advanced Micro Devices |
| TSM | Taiwan Semiconductor |
| ASML | ASML Holding |
| AVGO | Broadcom Inc. |

---

## 2. Tech Stack

### 2.1 Backend (`backend/`)

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Language | Python 3.10+ | Runtime |
| Framework | LangGraph 0.2+ | 状态图编排（**带循环 + 条件分支**） |
| LLM Abstraction | LangChain 0.3+ | LLM 调用封装（结构化输出） |
| LLM Provider | 默认 GLM (glm-5.1, Anthropic 兼容端点) / 官方 Anthropic / OpenAI | 分析师 / 风控双 Agent 推理 |
| Data Validation | Pydantic v2 | LLM 结构化输出 & API 模型 |
| API Framework | FastAPI + Uvicorn | REST API 服务（含 CORS） |
| Database | SQLite + aiosqlite | 数据持久化（异步） |
| Stock Data | yfinance | 实时股价与基础数据 |
| News Search | Tavily / DuckDuckGo Search | 新闻抓取（含证据补充环） |
| Config | python-dotenv | 环境变量管理 |

> **相比 v1.3：** 图从线性流水线升级为带三个有界循环的状态机（见 §3）。仍无需 `langgraph-checkpoint-sqlite`——循环在单次 invoke 内完成。

### 2.2 Frontend (`frontend/`)

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | Vue 3 (Composition API) | SPA 前端 |
| UI Library | Ant Design Vue 4.x | 组件库 |
| Build Tool | Vite | 构建 / dev server / 代理 |
| Router | Vue Router 4 | 页面路由 |
| State | Pinia | 状态管理 |
| HTTP | axios | 调用后端 REST API |
| Language | TypeScript | 类型安全 |
| Auth | 无（MVP） | 不引入登录/鉴权 |

---

## 3. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                Web Frontend (Vue3 + Ant Design Vue)              │
│   推荐历史(含风控结论) / 今日交易(撤销) / 运行详情(风控卡片)         │
└───────────────────────────┬──────────────────────────────────────┘
                            │ axios (REST/JSON, /api, CORS)
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                     FastAPI Server Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │ /api/recom-  │  │ /api/runs/*  │  │ /api/trades/*           │ │
│  │ mendations/* │  │ /api/run/... │  │ (today, cancel)         │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬──────────────┘ │
└─────────┼─────────────────┼─────────────────────┼───────────────┘
          │                 │                     │
          ▼                 ▼                     ▼
┌──────────────────────────────────────────────────────────────────┐
│                       Database Layer (SQLite)                     │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│  │ analysis_runs│  │ recommendations  │  │ trades (BUY/SELL)  │  │
│  │ (+risk_*)    │  │                  │  │                    │  │
│  └──────────────┘  └──────────────────┘  └────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
          ▲                                           ▲
          │ (query / cancel trades)                   │ (write run + recs + trades)
          │                                           │
┌──────────────────────────────────────────────────────────────────┐
│         LangGraph StateGraph (Multi-Agent, Bounded Loops)         │
│                                                                   │
│  news_scraper ─▶ quant_analyst ◀──────────────┐                  │
│                      │ (route_after_analyst)   │ risk_feedback    │
│            ┌─────────┴──────────┐              │ (risk_rounds++)  │
│       证据不足&未超轮          证据充分          │                  │
│            ▼                    ▼              │                  │
│   evidence_gatherer ──回到──▶ risk_reviewer ───┘ (驳回&未超轮)     │
│   (evidence_rounds++)             │ (route_after_risk)            │
│                       ┌───────────┴────────────┐                 │
│                  通过 / 轮次用尽            （上面的回边）           │
│                       ▼                                           │
│              data_persistence ─▶ auto_execution ─▶ END           │
│                                                                   │
│  schema 校验失败 → quant_analyst 内部重试（≤ MAX_SCHEMA_RETRIES）  │
│  任意节点异常 ─▶ error_handler (status=ERROR) ─▶ END               │
└──────────────────────────────────────────────────────────────────┘

事后人工撤销（不属于图流程）：
  Frontend「今日交易」 ─▶ POST /api/trades/{id}/cancel ─▶ 校验当日 ─▶ trades.status=CANCELLED
```

> **关键变更（v1.4）：** 引入 `Evidence_Gatherer_Node` 与 `Risk_Reviewer_Node`（独立风控 Agent）及两条回边，构成三个有界循环；`analysis_runs` 增加 `risk_verdict` / `risk_rounds` / `evidence_rounds` / `review_notes`。

### 3.1 三个有界循环

| 循环 | 类型 | 触发 / 终止 | 上限 |
|------|------|------------|------|
| 结构化输出自修复 | 节点内 | schema 校验失败带反馈重试；合法或超限即停 | `MAX_SCHEMA_RETRIES`（默认 2） |
| 证据补充环 | 图循环 | `needs_more_evidence` 非空且未超限 → evidence_gatherer → 回 analyst | `MAX_EVIDENCE_ROUNDS`（默认 2） |
| 风控反思环 | 图循环 | 风控驳回且未超限 → 带 feedback 回 analyst | `MAX_RISK_ROUNDS`（默认 3） |

### 3.2 路由函数

- `route_after_analyst(state)`：`needs_more_evidence` 非空且 `evidence_rounds < MAX_EVIDENCE_ROUNDS` → `evidence_gatherer`；否则 → `risk_reviewer`。
- `route_after_risk(state)`：`risk_review.approved` → `data_persistence`；否则若 `risk_rounds < MAX_RISK_ROUNDS` → `quant_analyst`（带 risk_feedback）；否则（轮次用尽）→ `data_persistence`（`risk_verdict=REJECTED_AT_LIMIT`）。

### 3.3 轮次用尽策略

`RISK_LIMIT_POLICY` 配置：
- `EXECUTE_AND_FLAG`（默认）：风控未通过仍执行，run 标 `risk_verdict=REJECTED_AT_LIMIT`，前端警示，人工可当日撤销。
- `DOWNGRADE_TO_HOLD`：被风控否决的 BUY/SELL 降级为 HOLD，不下单；其余正常执行。

---

## 4. Component Architecture

### 4.1 Layered Structure

```
┌─────────────────────────────────────┐
│        Frontend (Vue3 SPA)           │  pages, components, router, pinia stores, api client
├─────────────────────────────────────┤
│           Presentation Layer         │  FastAPI endpoints, CORS, CLI I/O, report formatting
├─────────────────────────────────────┤
│           Orchestration Layer        │  LangGraph StateGraph（多 Agent + 有界循环 + 条件路由）
├─────────────────────────────────────┤
│           Business Logic Layer       │  scraping, analysis, evidence-gathering, risk-review, auto-exec, cancel
├─────────────────────────────────────┤
│           Data Access Layer          │  SQLite repository, CRUD operations
├─────────────────────────────────────┤
│           Integration Layer          │  yfinance, Tavily/DuckDuckGo, LLM API
├─────────────────────────────────────┤
│           Infrastructure Layer       │  Config, logging, state definition, DB migrations
└─────────────────────────────────────┘
```

### 4.2 Backend Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `config/` | 环境变量加载、常量定义（含三个循环上限/风控策略）、LLM 客户端初始化 |
| `models/` | State TypedDict、Pydantic 模型定义（分析师 + 风控） |
| `nodes/` | 各 Graph Node 实现 + 路由函数 |
| `graph/` | StateGraph 构建（节点 + 条件边/回边）与编译 |
| `tools/` | yfinance、Tavily/DuckDuckGo 的封装 |
| `prompts/` | 分析师 / 风控 prompt 模板 |
| `db/` | SQLite 连接管理、数据库初始化、Repository（runs / recs / trades） |
| `api/` | FastAPI 路由、请求/响应模型、CORS、依赖注入 |
| `utils/` | 格式化、当日判定、错误处理等 |
| `tests/` | 单元测试、集成测试 |

### 4.3 Frontend Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `api/` | axios 实例、拦截器、按资源划分的 API 封装（runs / recommendations / trades） |
| `types/` | 与后端响应模型对应的 TS 类型（含 RiskReview） |
| `stores/` | Pinia stores（runs、recommendations、trades） |
| `router/` | 路由表 |
| `views/` | HistoryView、TodayTradesView、RunDetailView |
| `components/` | RunTable、RecommendationTable、TradeTable、RiskReviewCard、ActionTag、CancelButton |
| `App.vue` / `main.ts` | 布局、Ant Design Vue 注册、应用入口 |

---

## 5. Database Design (SQLite)

> **通用约定：** 连接时开启 `PRAGMA foreign_keys = ON;`，并启用 WAL 模式支持并发读。

### 5.1 Schema

**analysis_runs** — 分析运行记录（含 AI 风控结论）

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | TEXT | PK | UUID |
| run_date | TEXT | NOT NULL | 运行日期 (YYYY-MM-DD) |
| status | TEXT | NOT NULL | "EXECUTED", "ERROR" |
| risk_verdict | TEXT | | "APPROVED" / "REJECTED_AT_LIMIT"（ERROR 时可空） |
| risk_rounds | INTEGER | NOT NULL DEFAULT 0 | 风控反思环轮数 |
| evidence_rounds | INTEGER | NOT NULL DEFAULT 0 | 证据补充环轮数 |
| review_notes | TEXT | | 风控最终意见摘要（nullable） |
| error_message | TEXT | | 错误原因（仅 status=ERROR，nullable） |
| created_at | TEXT | NOT NULL | ISO 8601 创建时间 |

> **状态流转：** 自动跑完为 `EXECUTED`（risk_verdict=APPROVED 或 REJECTED_AT_LIMIT），异常为 `ERROR`；撤销交易不改变 run 状态/风控结论。

**recommendations** — 逐 ticker 分析结果（含 HOLD，存最终修订版）

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | 自增主键 |
| run_id | TEXT | FK → analysis_runs.id, ON DELETE CASCADE | 关联运行记录 |
| run_date | TEXT | NOT NULL | 冗余运行日期，按日期高效查询 |
| ticker | TEXT | NOT NULL | 股票代码 |
| reasoning | TEXT | NOT NULL | LLM 分析文本 |
| sentiment_score | INTEGER | NOT NULL, CHECK(1-10) | 情绪评分 |
| action | TEXT | NOT NULL, CHECK | "BUY", "HOLD", "SELL" |
| price_at_analysis | REAL | NOT NULL | 分析时股价 |
| created_at | TEXT | NOT NULL | ISO 8601 创建时间 |

**trades** — 由 BUY/SELL 自动执行产生的模拟交易（可撤销）

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO | 自增主键 |
| run_id | TEXT | FK → analysis_runs.id, ON DELETE CASCADE | 关联运行记录 |
| run_date | TEXT | NOT NULL | 冗余运行日期，「当日撤销」判定 + 按日期查询 |
| ticker | TEXT | NOT NULL | 股票代码 |
| side | TEXT | NOT NULL, CHECK(BUY/SELL) | 交易方向 |
| price | REAL | NOT NULL | 执行价格 |
| status | TEXT | NOT NULL, CHECK(EXECUTED/CANCELLED) | 交易状态 |
| executed_at | TEXT | NOT NULL | ISO 8601 执行时间 |
| cancelled_at | TEXT | | ISO 8601 撤销时间 (nullable) |

> **设计说明：** AI 风控逐条 issues 的 MVP 做法是序列化进 `review_notes`；后续可拆出独立 `risk_issues` 表（FK run_id）。三表均冗余 `run_date`，按日期/当日查询走单表索引、免 join。

### 5.2 Indexes

```sql
CREATE INDEX idx_recommendations_run_id      ON recommendations(run_id);
CREATE INDEX idx_recommendations_ticker      ON recommendations(ticker);
CREATE INDEX idx_recommendations_run_date    ON recommendations(run_date);
CREATE INDEX idx_recommendations_ticker_date ON recommendations(ticker, run_date);
CREATE INDEX idx_trades_run_id               ON trades(run_id);
CREATE INDEX idx_trades_run_date             ON trades(run_date);
CREATE INDEX idx_trades_ticker               ON trades(ticker);
CREATE INDEX idx_trades_status               ON trades(status);
CREATE INDEX idx_analysis_runs_date          ON analysis_runs(run_date);
CREATE INDEX idx_analysis_runs_status        ON analysis_runs(status);
CREATE INDEX idx_analysis_runs_risk_verdict  ON analysis_runs(risk_verdict);
```

### 5.3 ER Diagram

```
┌──────────────────────┐       ┌──────────────────────────┐
│  analysis_runs       │       │    recommendations        │
├──────────────────────┤       ├──────────────────────────┤
│ id (PK)        TEXT  │───┬──▶│ run_id (FK)     TEXT     │ ON DELETE CASCADE
│ run_date       TEXT  │   │   │ run_date / ticker / ...  │
│ status         TEXT  │   │   └──────────────────────────┘
│ risk_verdict   TEXT  │   │   ┌──────────────────────────┐
│ risk_rounds    INT   │   │   │    trades                 │
│ evidence_rounds INT  │   └──▶│ run_id (FK)     TEXT     │ ON DELETE CASCADE
│ review_notes   TEXT  │       │ run_date / ticker        │
│ error_message  TEXT  │       │ side / price             │
│ created_at     TEXT  │       │ status / executed_at     │
└──────────────────────┘       │ cancelled_at             │
                               └──────────────────────────┘
```

---

## 6. API Design

### 6.1 Endpoint Overview

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | `/api/recommendations/latest` | 最新全部 ticker 建议 | None (MVP) |
| GET | `/api/recommendations/{date}` | 指定日期全部建议 | None (MVP) |
| GET | `/api/recommendations/ticker/{ticker}/latest` | 指定 ticker 最新建议 | None (MVP) |
| GET | `/api/recommendations/ticker/{ticker}/history` | 指定 ticker 历史建议（分页） | None (MVP) |
| POST | `/api/run/trigger` | 触发分析运行（异步，202 + run_id；跑完三循环 + 执行） | None (MVP) |
| GET | `/api/runs` | 列出分析运行（分页，status/date/risk_verdict 筛选） | None (MVP) |
| GET | `/api/runs/{run_id}` | run 状态 + 风控结论 + recommendations + trades | None (MVP) |
| GET | `/api/trades/today` | 当天已执行、可撤销的交易列表 | None (MVP) |
| GET | `/api/trades` | 列出交易（分页，run_id/ticker/status/date 筛选） | None (MVP) |
| POST | `/api/trades/{trade_id}/cancel` | 撤销单笔交易（仅当天） | None (MVP) |
| POST | `/api/runs/{run_id}/cancel` | 批量撤销该 run 当天未撤销的交易 | None (MVP) |

### 6.2 Response Envelope

统一信封；分页类在 `meta` 携带 `total / page / page_size / total_pages`：

```json
{ "success": true, "data": {}, "error": null, "meta": {} }
```

失败响应通过 `error.code` + `error.message` 返回。

### 6.3 Error Codes

| HTTP | error.code | 说明 |
|------|------------|------|
| 400 | `INVALID_PARAMETER` | 参数非法（如日期格式错误） |
| 404 | `RESOURCE_NOT_FOUND` | 日期/ticker 无数据 |
| 404 | `RUN_NOT_FOUND` | run_id 不存在 |
| 404 | `TRADE_NOT_FOUND` | trade_id 不存在 |
| 409 | `TRADE_NOT_CANCELLABLE` | 交易非当日、或已撤销，不可撤销 |
| 422 | `VALIDATION_ERROR` | 请求参数校验失败 |
| 500 | `INTERNAL_ERROR` | 服务内部错误 |
| 502 | `UPSTREAM_ERROR` | 上游依赖（yfinance/搜索/LLM）失败 |

### 6.4 Pagination, Cancellation & CORS

- 分页接口（`/recommendations/ticker/{ticker}/history`、`/runs`、`/trades`）统一支持 `page`（默认 1）与 `page_size`（默认 20，最大 100）。`/runs` 额外支持 `status`、`date`、`risk_verdict`；`/trades` 额外支持 `run_id`、`ticker`、`status`、`date`。
- **撤销规则（当日限制）：** 交易可撤销当且仅当存在、`run_date == 服务器当天`、且 `status == EXECUTED`；否则 `404 TRADE_NOT_FOUND` / `409 TRADE_NOT_CANCELLABLE`。撤销只改 `trades`，不改写 `recommendations` / `analysis_runs`（审计可追溯）。run 级批量撤销跳过不满足条件者并返回实际撤销数量。
- 服务器模式启用 `CORSMiddleware`，允许来源由 `CORS_ORIGINS` 配置（默认 `http://localhost:5173`）。

---

## 7. Frontend Architecture

### 7.1 Pages & Routes

| Page | Route | Purpose |
|------|-------|---------|
| HistoryView | `/` / `/history` | 推荐历史列表（分页、status/date/risk_verdict 筛选），点击进详情 |
| TodayTradesView | `/today` | 当天已执行交易，「撤销」按钮（仅当天） |
| RunDetailView | `/runs/:runId` | run 详情：风控卡片 + recommendations + trades；当天 trade 可撤销 |

### 7.2 Pipeline + Cancel Flow (前后端)

```
触发分析 (POST /api/run/trigger, 202)
        │  后台跑完：抓取 →(分析↔证据补充)→(分析↔风控反思)→ 落库 → 自动执行
        │  风控通过 → risk_verdict=APPROVED；轮次用尽 → REJECTED_AT_LIMIT(+警示)
        ▼
RunDetailView ── GET /api/runs/{id} ──▶ 风控卡片(issues/notes) + 推荐 + 交易
TodayTradesView ── GET /api/trades/today ──▶ 当天交易
        │ 点击「撤销」(a-popconfirm)
        ▼
POST /api/trades/{trade_id}/cancel
        ├── 通过 → status=CANCELLED → 列表刷新
        └── 不通过 → 409 / 404 → message 提示
```

### 7.3 Dev Proxy & Types

- Vite dev server 将 `/api` 代理到 `http://localhost:8000`；后端 `CORSMiddleware` 兜底。
- 前端 TS 类型与后端 Pydantic 模型一一对应（`ApiResponse<T>`、`RunOut`/`RunDetailOut`、`RecommendationOut`、`TradeOut`、`RiskReviewOut`、`PaginationMeta`）。
- axios 响应拦截器统一解析信封，`success=false` 抛错并提示。
- 「当天可撤销」由后端权威判定（`TradeOut.cancellable`）；前端据此控制按钮可用性。

---

## 8. State Flow

```
AgentState（关键字段）
┌────────────────────────────────────────────────────────────┐
│ raw_news_data        ──▶ 证据补充环会追加更新                  │
│ analyses             ──▶ 分析师每轮修订                        │
│ needs_more_evidence  ──▶ 触发证据补充环                        │
│ evidence_rounds      ──▶ 证据环计数（终止条件）                │
│ risk_review          ──▶ 风控结论（approved/issues/notes）     │
│ risk_feedback        ──▶ 驳回时回传分析师                      │
│ risk_rounds          ──▶ 风控环计数（终止条件）                │
│ risk_verdict         ──▶ APPROVED / REJECTED_AT_LIMIT         │
│ executed_trades      ──▶ 自动执行的 BUY/SELL                  │
│ run_id / error_message                                       │
└────────────────────────────────────────────────────────────┘

news_scraper      ─▶ raw_news_data
quant_analyst     ─▶ analyses + needs_more_evidence (+ 消费 risk_feedback)
  ├─(证据不足&未超轮)─▶ evidence_gatherer ─▶ raw_news_data 更新, evidence_rounds++ ─▶ 回 quant_analyst
  └─(证据充分)──────▶ risk_reviewer ─▶ risk_review
        ├─(通过)──────────────▶ data_persistence ─▶ auto_execution ─▶ END
        ├─(驳回&未超轮)────────▶ risk_feedback, risk_rounds++ ─▶ 回 quant_analyst
        └─(驳回&轮次用尽)──────▶ risk_verdict=REJECTED_AT_LIMIT ─▶ data_persistence ─▶ auto_execution ─▶ END
error_handler     ─▶ status=ERROR
```

### State Immutability

每个 Node 返回 **新的 State partial dict**，LangGraph 自动合并：

```python
def news_scraper_node(state: AgentState) -> dict:
    return {"raw_news_data": fetch_all_news(state["tickers"])}
```

---

## 9. Error Handling Strategy

```
┌──────────────┐
│  Node Error  │
└──────┬───────┘
       ▼
┌─────────────────────┐    YES    ┌──────────────────┐
│ Retriable? (network)│──────────▶│ Retry with backoff│
└──────┬──────────────┘           └──────────────────┘
       │ NO
       ▼
┌─────────────────────────────┐
│ Route to Error_Handler_Node │
│  - set status = "ERROR"     │
│  - persist error_message    │
└─────────────────────────────┘
```

- **API 调用失败**：重试 3 次，指数退避；超限路由到 Error_Handler。
- **LLM 结构化输出失败**：结构化输出自修复循环（≤ MAX_SCHEMA_RETRIES）；仍失败 → ERROR。
- **循环防失控**：三个循环均有硬上限，路由函数基于 `*_rounds` 计数终止。
- **数据库写入失败**：记录日志并标记 run 状态。
- **自动执行/撤销**：使用事务；撤销严格校验「当日 + EXECUTED」。
- **超时控制**：所有网络/LLM 调用设置超时。
- **部分失败**：单 ticker 抓取失败可记录并继续。
- **前端**：统一拦截 `error` 提示；`REJECTED_AT_LIMIT` 给醒目警示。

---

## 10. Security Design

| Concern | Mitigation |
|---------|-----------|
| API Keys | `.env` 管理，`.gitignore` 排除，提供 `.env.example` |
| LLM Prompt Injection | 新闻内容只作为 data context，不注入 system prompt |
| Input Validation | API 路径/请求参数经 Pydantic / FastAPI 校验 |
| Auto-Execution Risk | AI 风控前置把关 + 轮次用尽标记/降级；撤销受「当日」严格约束，事务保证一致性 |
| Loop Abuse | 三循环硬上限，防止 LLM 驱动的无限循环耗尽配额 |
| Rate Limiting | 对外部 API 设置速率限制与重试退避 |
| SQL Injection | 参数化查询，Repository 模式 |
| CORS | 服务器模式限定允许来源（CORS_ORIGINS） |
| API Auth | MVP 无认证；预留中间件接口 |

> **注意：** 自动执行 + 无鉴权意味着任何能访问 API 的人都可触发分析与撤销。生产化前应至少加入鉴权与操作审计。AI 风控降低但不消除错误交易风险。

---

## 11. Run Modes

### 11.1 CLI Mode

```bash
cd backend
python -m src.main
```

非交互单次运行：抓取 →(分析↔证据补充)→(分析↔风控反思)→ 落库 → 自动执行 → 打印风控结论与已执行交易 → 退出。

### 11.2 Server Mode

```bash
cd backend
python -m src.main --serve [--port 8000]
```

- `POST /api/run/trigger` **异步**启动分析（后台任务），立即返回 `202 Accepted` + `run_id`；后台**完整跑完**（三循环 + 自动执行）。
- 前端通过 `/api/runs`、`/api/runs/{run_id}`、`/api/trades/today` 查询，并对当天交易执行撤销。

### 11.3 Frontend Dev

```bash
cd frontend
npm install
npm run dev          # Vite dev server, 默认 http://localhost:5173, 代理 /api → :8000
```

---

## 12. Monorepo Directory Structure

```
ai-stock-assistant/
├── README.md                       # monorepo 总览 + 启动说明（含 Docker）
├── docker-compose.yml              # 一键启动 backend + frontend
├── spec.md
├── CLAUDE.md
├── doc/                            # 设计文档
│   ├── architecture-design.md
│   └── detailed-design.md
│
├── backend/                        # Python / FastAPI / LangGraph
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── .env.example
│   ├── .gitignore
│   ├── data/                       # SQLite 数据库文件目录
│   │   └── .gitkeep
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py                 # CLI + Server 入口
│   │   ├── config/
│   │   │   ├── settings.py         # 环境变量 & 常量（CORS、循环上限、风控策略）
│   │   │   └── llm.py              # LLM 客户端工厂
│   │   ├── models/
│   │   │   ├── state.py            # AgentState + TickerNews/TickerAnalysis/RiskReview/TradeExecution
│   │   │   └── schemas.py          # Pydantic API + LLM models（QuantReport / RiskReview / TradeOut ...）
│   │   ├── nodes/
│   │   │   ├── news_scraper.py     # Node 1
│   │   │   ├── quant_analyst.py    # Node 2（含 schema 自修复）
│   │   │   ├── evidence_gatherer.py# Node 3（证据补充环）(NEW)
│   │   │   ├── risk_reviewer.py    # Node 4（风控 Agent）(NEW)
│   │   │   ├── data_persistence.py # Node 5
│   │   │   ├── auto_execution.py   # Node 6
│   │   │   ├── error_handler.py    # Node E
│   │   │   └── routing.py          # route_after_analyst / route_after_risk (NEW)
│   │   ├── graph/
│   │   │   └── builder.py          # StateGraph 构建（节点 + 条件边/回边）
│   │   ├── tools/
│   │   │   ├── stock_data.py       # yfinance 封装
│   │   │   └── news_search.py      # Tavily/DuckDuckGo 封装
│   │   ├── db/
│   │   │   ├── connection.py       # SQLite 连接管理
│   │   │   ├── init_db.py          # 建表 & 索引（含 risk_* 列 + trades）
│   │   │   └── repository.py       # 数据访问层 (runs / recs / trades)
│   │   ├── api/
│   │   │   ├── app.py              # FastAPI app factory（含 CORS）
│   │   │   ├── routes/
│   │   │   │   ├── recommendations.py
│   │   │   │   ├── runs.py          # 运行管理 + run 级撤销
│   │   │   │   └── trades.py        # 交易查询 + 撤销
│   │   │   └── dependencies.py     # 依赖注入
│   │   ├── prompts/
│   │   │   ├── quant_analyst.py    # 分析师 prompt
│   │   │   └── risk_reviewer.py    # 风控 prompt (NEW)
│   │   └── utils/
│   │       ├── formatting.py
│   │       └── dates.py            # 当日判定工具
│   └── tests/
│       ├── test_news_scraper.py
│       ├── test_quant_analyst.py
│       ├── test_evidence_gatherer.py   # (NEW)
│       ├── test_risk_reviewer.py       # (NEW)
│       ├── test_routing.py             # 路由/循环终止 (NEW)
│       ├── test_data_persistence.py
│       ├── test_auto_execution.py
│       ├── test_error_handler.py
│       ├── test_graph_builder.py
│       ├── test_repository.py
│       ├── test_trades_cancel.py
│       └── test_api.py
│
└── frontend/                       # Vue3 + Ant Design Vue
    ├── package.json
    ├── Dockerfile                  # 多阶段：build + nginx
    ├── nginx.conf                  # 静态托管 + /api 反代到 backend
    ├── .dockerignore
    ├── vite.config.ts              # dev server + /api 代理
    ├── tsconfig.json
    ├── index.html
    ├── .env.development
    ├── .env.production
    └── src/
        ├── main.ts                 # 应用入口，注册 Ant Design Vue / Pinia / Router
        ├── App.vue                 # 布局（顶部导航 + 触发分析按钮）
        ├── router/
        │   └── index.ts
        ├── api/
        │   ├── client.ts           # axios 实例 + 拦截器
        │   ├── runs.ts             # runs / trigger / run 级 cancel API
        │   ├── recommendations.ts  # recommendations API
        │   └── trades.ts           # trades / today / cancel API
        ├── types/
        │   └── index.ts            # ApiResponse / RunOut / RecommendationOut / TradeOut / RiskReview
        ├── stores/
        │   ├── runs.ts
        │   ├── recommendations.ts
        │   └── trades.ts
        ├── views/
        │   ├── HistoryView.vue
        │   ├── TodayTradesView.vue
        │   └── RunDetailView.vue
        └── components/
            ├── RunTable.vue
            ├── RecommendationTable.vue
            ├── TradeTable.vue
            ├── RiskReviewCard.vue  # AI 风控结论卡片 (NEW)
            ├── ActionTag.vue
            └── CancelButton.vue
```
