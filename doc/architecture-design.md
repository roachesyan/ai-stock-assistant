# Architecture Design: AI Quant Agent v1.2 MVP

## 1. System Overview

AI Quant Agent 是一个基于 LangGraph + LangChain 的多智能体系统，用于追踪全球 Top 10 AI 公司，聚合每日新闻与金融数据，生成量化分析及交易建议，并通过 Human-in-the-Loop (HITL) 机制在模拟执行前要求人工审批。系统提供 **REST API** 与 **Web 前端**（Vue3 + Ant Design Vue），供人工查询推荐历史、审阅 AI 分析并点击确认/拒绝今日交易。所有分析结果持久化到 **SQLite** 数据库。

项目采用 **monorepo** 结构：`backend/`（Python/FastAPI/LangGraph）与 `frontend/`（Vue3）。

整体编排是一个**带条件分支的状态机**（而非纯线性 DAG）。为支持 Web 审批工作流，**持久化节点前置到人工审批之前**：分析结果先以 `PENDING` 落库，审批后由 `Finalize` 节点更新状态。服务器模式下借助 LangGraph Checkpointer 支持「中断 → 审批 → 恢复」。

> ⚠️ **免责声明：** 本系统仅用于技术研究与学习目的，所有分析结果与「交易操作」均为**模拟**，不构成任何投资建议。

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
| Framework | LangGraph 0.2+ | 状态图编排（条件分支 + HITL 中断） |
| State Persistence | LangGraph SqliteSaver / AsyncSqliteSaver | Checkpointer，支持中断恢复 |
| LLM Abstraction | LangChain 0.3+ | LLM 调用封装（结构化输出） |
| LLM Provider | Anthropic Claude / OpenAI GPT-4o | 分析推理 |
| Data Validation | Pydantic v2 | LLM 结构化输出 & API 模型 |
| API Framework | FastAPI + Uvicorn | REST API 服务（含 CORS） |
| Database | SQLite + aiosqlite | 数据持久化（异步） |
| Stock Data | yfinance | 实时股价与基础数据 |
| News Search | Tavily / DuckDuckGo Search | 新闻抓取 |
| Config | python-dotenv | 环境变量管理 |

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
│   推荐历史 / 待审批队列 / 运行详情·审阅（确认买入·拒绝）             │
└───────────────────────────┬──────────────────────────────────────┘
                            │ axios (REST/JSON, /api, CORS)
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                     FastAPI Server Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐    │
│  │ /api/recom-  │  │ /api/runs/*  │  │ /api/run/trigger    │    │
│  │ mendations/* │  │ (+pending,id)│  │ /api/run/{id}/approve│    │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬──────────┘    │
└─────────┼─────────────────┼─────────────────────┼───────────────┘
          │                 │                     │
          ▼                 ▼                     ▼
┌──────────────────────────────────────────────────────────────────┐
│                       Database Layer (SQLite)                     │
│  ┌──────────────────┐  ┌──────────────────────────────────┐     │
│  │  analysis_runs   │  │  recommendations (per ticker)    │     │
│  └──────────────────┘  └──────────────────────────────────┘     │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  langgraph checkpoints (SqliteSaver, thread_id=run_id)│       │
│  └──────────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────┘
          ▲                                           ▲
          │ (query)                          (write PENDING then finalize)
          │                                           │
┌──────────────────────────────────────────────────────────────────┐
│           LangGraph StateGraph (Conditional State Machine)        │
│                                                                   │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐      │
│  │ News_Scraper │──▶│ Quant_Analyst│──▶│ Data_Persistence │      │
│  │    _Node     │   │    _Node     │   │ (status=PENDING) │      │
│  └──────────────┘   └──────────────┘   └────────┬─────────┘      │
│                                                  ▼                │
│                                        ┌──────────────────┐       │
│                                        │ Human_Approval   │ ◀─HITL│
│                                        │  _Node (interrupt)│      │
│                                        └────────┬─────────┘       │
│                                                 ▼                 │
│                                        ┌──────────────────┐       │
│                                        │ Finalize_Node    │       │
│                                        │ (update status)  │       │
│                                        └────────┬─────────┘       │
│                                  conditional edge│                │
│                            ┌─────────────────────┴───────┐        │
│                        APPROVED                       REJECTED     │
│                            ▼                              ▼        │
│                  ┌──────────────────┐                   END        │
│                  │ Mock_Execution   │                              │
│                  └────────┬─────────┘                              │
│                           ▼                                        │
│                          END                                       │
│                                                                   │
│  任意节点异常 ──▶ Error_Handler_Node (status=ERROR) ──▶ END        │
└──────────────────────────────────────────────────────────────────┘
```

> **关键变更（v1.2）：** 持久化节点移至审批之前（写入 `PENDING`），新增 `Finalize_Node` 在审批后更新 run 状态。这样前端在审批前即可查询并展示分析内容。

---

## 4. Component Architecture

### 4.1 Layered Structure

```
┌─────────────────────────────────────┐
│        Frontend (Vue3 SPA)           │  pages, components, router, pinia stores, api client
├─────────────────────────────────────┤
│           Presentation Layer         │  FastAPI endpoints, CORS, CLI I/O, report formatting
├─────────────────────────────────────┤
│           Orchestration Layer        │  LangGraph StateGraph, conditional edges, checkpointer
├─────────────────────────────────────┤
│           Business Logic Layer       │  News scraping, quant analysis, finalize, execution
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
| `config/` | 环境变量加载、常量定义、LLM 客户端初始化 |
| `models/` | State TypedDict、Pydantic 模型定义 |
| `nodes/` | 各 Graph Node 的实现（纯函数，接收 State 返回新 State） |
| `graph/` | StateGraph 构建、条件边连接、checkpointer 编译 |
| `tools/` | yfinance、Tavily/DuckDuckGo 的封装 |
| `prompts/` | LLM prompt 模板 |
| `db/` | SQLite 连接管理、数据库初始化、Repository 模式数据访问 |
| `api/` | FastAPI 路由定义、请求/响应模型、CORS、依赖注入 |
| `utils/` | 格式化、错误处理等工具函数 |
| `tests/` | 单元测试、集成测试 |

### 4.3 Frontend Module Responsibilities

| Module | Responsibility |
|--------|---------------|
| `api/` | axios 实例、拦截器、按资源划分的 API 调用封装 |
| `types/` | 与后端响应模型对应的 TypeScript 类型 |
| `stores/` | Pinia stores（runs、recommendations） |
| `router/` | 路由表 |
| `views/` | 页面：HistoryView、PendingView、RunDetailView |
| `components/` | 复用组件：RunTable、RecommendationTable、ActionTag、ApprovalBar |
| `App.vue` / `main.ts` | 布局、Ant Design Vue 注册、应用入口 |

---

## 5. Database Design (SQLite)

> **通用约定：** 连接时开启 `PRAGMA foreign_keys = ON;`，并启用 WAL 模式支持并发读。

### 5.1 Schema

**analysis_runs** — 分析运行记录

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | TEXT | PK | UUID（同时用作 LangGraph thread_id） |
| run_date | TEXT | NOT NULL | 运行日期 (YYYY-MM-DD) |
| status | TEXT | NOT NULL | "PENDING", "APPROVED", "REJECTED", "ERROR" |
| error_message | TEXT | | 错误原因（仅 status=ERROR，nullable） |
| created_at | TEXT | NOT NULL | ISO 8601 创建时间 |
| approved_at | TEXT | | ISO 8601 审批时间 (nullable) |

> **状态流转：** 创建时 `PENDING`（数据已写入）→ 审批后 `APPROVED`/`REJECTED` → 异常 `ERROR`。

**recommendations** — 逐 ticker 分析结果

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

> **设计说明：** `recommendations` 冗余 `run_date`，按日期查询可走单表索引，无需 join `analysis_runs`。

### 5.2 Indexes

```sql
CREATE INDEX idx_recommendations_run_id      ON recommendations(run_id);
CREATE INDEX idx_recommendations_ticker      ON recommendations(ticker);
CREATE INDEX idx_recommendations_run_date    ON recommendations(run_date);
CREATE INDEX idx_recommendations_ticker_date ON recommendations(ticker, run_date);
CREATE INDEX idx_analysis_runs_date          ON analysis_runs(run_date);
CREATE INDEX idx_analysis_runs_status        ON analysis_runs(status);
```

### 5.3 ER Diagram

```
┌──────────────────────┐       ┌──────────────────────────┐
│  analysis_runs       │       │    recommendations        │
├──────────────────────┤       ├──────────────────────────┤
│ id (PK)        TEXT  │───┐   │ id (PK)         INTEGER  │
│ run_date       TEXT  │   │   │ run_id (FK)     TEXT     │◀─┐
│ status         TEXT  │   └──▶│ run_date        TEXT     │  │ ON DELETE
│ error_message  TEXT  │       │ ticker          TEXT     │  │ CASCADE
│ created_at     TEXT  │       │ reasoning       TEXT     │  │
│ approved_at    TEXT  │       │ sentiment_score INTEGER  │  │
└──────────────────────┘       │ action          TEXT     │  │
                               │ price_at_analysis REAL   │  │
                               │ created_at      TEXT     │  │
                               └──────────────────────────┘  │
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
| POST | `/api/run/trigger` | 手动触发分析运行（异步，202 + run_id） | None (MVP) |
| GET | `/api/runs` | 列出所有分析运行（分页，支持 status/date 筛选） | None (MVP) |
| GET | `/api/runs/{run_id}` | 查询指定 run 的状态、详情及其全部 recommendations | None (MVP) |
| GET | `/api/runs/pending` | 获取待审批（PENDING）队列 | None (MVP) |
| POST | `/api/run/{run_id}/approve` | 提交审批结果，恢复中断的图执行 | None (MVP) |

### 6.2 Response Envelope

所有 API 响应使用统一的信封格式；分页类接口在 `meta` 中携带 `total / page / page_size / total_pages`：

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": {}
}
```

失败响应通过 `error.code` + `error.message` 返回结构化错误。

### 6.3 Error Codes

| HTTP | error.code | 说明 |
|------|------------|------|
| 400 | `INVALID_PARAMETER` | 参数非法（如日期格式错误） |
| 400 | `INVALID_DECISION` | 审批结果非法 |
| 404 | `RESOURCE_NOT_FOUND` | 日期/ticker 无数据 |
| 404 | `RUN_NOT_FOUND` | run_id 不存在 |
| 409 | `RUN_NOT_PENDING` | run 当前不处于待审批状态 |
| 422 | `VALIDATION_ERROR` | 请求体校验失败 |
| 500 | `INTERNAL_ERROR` | 服务内部错误 |
| 502 | `UPSTREAM_ERROR` | 上游依赖（yfinance/搜索/LLM）失败 |

### 6.4 Pagination & CORS

- 分页接口（`/recommendations/ticker/{ticker}/history`、`/runs`）统一支持 `page`（默认 1）与 `page_size`（默认 20，最大 100），`/runs` 额外支持 `status`、`date` 筛选。
- 服务器模式启用 `CORSMiddleware`，允许的来源由环境变量 `CORS_ORIGINS` 配置（默认 `http://localhost:5173`）。

---

## 7. Frontend Architecture

### 7.1 Pages & Routes

| Page | Route | Purpose |
|------|-------|---------|
| HistoryView | `/` / `/history` | 推荐历史列表（分页、status/date 筛选），点击进入详情 |
| PendingView | `/pending` | 待审批队列（status=PENDING） |
| RunDetailView | `/runs/:runId` | 运行详情/审阅；PENDING 时显示「确认买入/拒绝」按钮 |

### 7.2 Approval Flow (前后端)

```
User → PendingView → 点击某 run → RunDetailView
        │                              │ GET /api/runs/{run_id}
        │                              ▼
        │                         展示每只股票建议/推理/价格
        │                              │ 点击「确认买入」或「拒绝」
        │                              ▼
        │                  POST /api/run/{run_id}/approve {decision}
        │                              │
        ▼                              ▼
   列表刷新                   后端恢复图执行 → Finalize → (Mock_Execution|END)
                                       │
                                       ▼
                            前端刷新展示最终状态（APPROVED/REJECTED）
```

### 7.3 Dev Proxy & Types

- Vite dev server 将 `/api` 代理到 `http://localhost:8000`，开发期免 CORS；后端 `CORSMiddleware` 作为兜底。
- 前端 TypeScript 类型与后端 Pydantic 响应模型一一对应（`ApiResponse<T>`、`RunOut`、`RecommendationOut`、`PaginationMeta`）。
- axios 响应拦截器统一解析信封，遇到 `success=false` 抛出错误并由调用方/全局提示处理。

---

## 8. State Flow

```
AgentState
┌────────────────────────────────────────────────────────────┐
│ tickers: ["AAPL", "MSFT", ...]                             │
│ raw_news_data: {} ──▶ {"AAPL": {price, news}, ...}        │
│ analyses: [] ──▶ [{ticker, reasoning, score, action, price}]│
│ analysis_report: "" ──▶ "formatted report"                 │
│ approval_status: "PENDING" ──▶ APPROVED/REJECTED/ERROR     │
│ run_id: <uuid> (= thread_id, 初始化生成)                    │
│ error_message: None ──▶ "..." (on error)                  │
└────────────────────────────────────────────────────────────┘

Node 1 (News_Scraper)     ──▶  fills raw_news_data (news + price)
Node 2 (Quant_Analyst)    ──▶  fills analyses + analysis_report
Node 3 (Data_Persistence) ──▶  写入 analysis_runs(PENDING) + recommendations
Node 4 (Human_Approval)   ──▶  interrupt；注入 approval_status
Node 5 (Finalize)         ──▶  更新 run 状态 (APPROVED/REJECTED, approved_at)
        │ conditional edge
        ├── APPROVED ─▶ Node 6 (Mock_Execution) ─▶ END
        └── REJECTED ─▶ END
Node E (Error_Handler)    ──▶  on exception: status=ERROR, fills error_message
```

### State Immutability

每个 Node 返回一个 **新的 State partial dict**，LangGraph 自动合并到当前 State。Node 内部不修改传入的 State 对象：

```python
def news_scraper_node(state: AgentState) -> dict:
    tickers = state["tickers"]
    news_data = fetch_all_news(tickers)
    return {"raw_news_data": news_data}
```

---

## 9. Error Handling Strategy

```
┌──────────────┐
│  Node Error  │
└──────┬───────┘
       │
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
│  - safe end of run          │
└─────────────────────────────┘
```

- **API 调用失败**：重试 3 次，指数退避；超过上限路由到 Error_Handler。
- **LLM 输出解析失败**：依赖 Pydantic 结构化输出 + 重试 1 次；仍失败回退默认 HOLD 或标记 ERROR。
- **数据库写入失败**：记录日志并标记 run 状态，避免静默丢失。
- **用户输入无效**：CLI 循环提示直到输入 Y/N；API 端返回 `INVALID_DECISION`。
- **超时控制**：所有网络/LLM 调用设置超时，防止单次 run 长时间挂起。
- **部分失败**：单个 ticker 抓取失败可记录状态并继续处理其余 ticker。
- **前端**：统一拦截 `error`，用 Ant Design `message`/`notification` 提示。

---

## 10. Security Design

| Concern | Mitigation |
|---------|-----------|
| API Keys | 通过 `.env` 文件管理，`.gitignore` 排除，提供 `.env.example` 模板 |
| LLM Prompt Injection | 新闻内容只作为 data context，不注入 system prompt |
| Input Validation | Human Approval 仅接受 Y/N；API 路径/请求体经 Pydantic 校验 |
| Rate Limiting | 对外部 API 设置速率限制与重试退避，避免限流/封禁 |
| SQL Injection | 使用参数化查询，Repository 模式 |
| CORS | 服务器模式限定允许来源（CORS_ORIGINS） |
| API Auth | MVP 阶段无认证（前端也无登录）；预留中间件接口供后续添加 |

---

## 11. Run Modes

### 11.1 CLI Mode

```bash
cd backend
python -m src.main
```

交互式单次运行：抓取→分析→写入 PENDING→`interrupt_before` 中断，控制台打印报告并等待 HITL 审批（Y/N），Finalize 更新状态后按结果走 APPROVED/REJECTED 分支。

### 11.2 Server Mode

```bash
cd backend
python -m src.main --serve [--port 8000]
```

启动 FastAPI 服务，供前端与外部系统使用：
- `POST /api/run/trigger` **异步**启动分析（后台任务），立即返回 `202 Accepted` + `run_id`。
- 后台分析写入 `PENDING` 数据后，执行到 `Human_Approval_Node` 中断。
- 前端轮询 `/api/runs/pending` 或 `/api/runs/{run_id}` 展示分析内容，再通过 `POST /api/run/{run_id}/approve` 提交结果。
- 系统基于 **Checkpointer** 和 `thread_id`（= run_id）恢复执行，服务重启后 PENDING 的 run 仍可恢复。

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
├── README.md                       # monorepo 总览 + 启动说明
├── spec.md
├── CLAUDE.md
├── doc/                            # 设计文档
│   ├── architecture-design.md
│   └── detailed-design.md
│
├── backend/                        # Python / FastAPI / LangGraph
│   ├── pyproject.toml
│   ├── .env.example
│   ├── .gitignore
│   ├── data/                       # SQLite 数据库文件目录
│   │   └── .gitkeep
│   ├── src/
│   │   ├── __init__.py
│   │   ├── main.py                 # CLI + Server 入口
│   │   ├── config/
│   │   │   ├── settings.py         # 环境变量 & 常量（含 CORS_ORIGINS）
│   │   │   └── llm.py              # LLM 客户端工厂
│   │   ├── models/
│   │   │   ├── state.py            # AgentState / TickerNews / TickerAnalysis
│   │   │   └── schemas.py          # Pydantic API request/response models
│   │   ├── nodes/
│   │   │   ├── news_scraper.py     # Node 1
│   │   │   ├── quant_analyst.py    # Node 2
│   │   │   ├── data_persistence.py # Node 3 (前置, 写 PENDING)
│   │   │   ├── human_approval.py   # Node 4
│   │   │   ├── finalize.py         # Node 5 (更新状态) (NEW)
│   │   │   ├── mock_execution.py   # Node 6
│   │   │   └── error_handler.py    # Node E
│   │   ├── graph/
│   │   │   ├── builder.py          # StateGraph 构建（条件边）
│   │   │   └── checkpointer.py     # SqliteSaver/AsyncSqliteSaver 工厂
│   │   ├── tools/
│   │   │   ├── stock_data.py       # yfinance 封装
│   │   │   └── news_search.py      # Tavily/DuckDuckGo 封装
│   │   ├── db/
│   │   │   ├── connection.py       # SQLite 连接管理
│   │   │   ├── init_db.py          # 建表 & 索引初始化
│   │   │   └── repository.py       # 数据访问层 (CRUD)
│   │   ├── api/
│   │   │   ├── app.py              # FastAPI app factory（含 CORS）
│   │   │   ├── routes/
│   │   │   │   ├── recommendations.py
│   │   │   │   └── runs.py          # 运行管理 + 审批路由
│   │   │   └── dependencies.py     # 依赖注入
│   │   ├── prompts/
│   │   │   └── quant_analyst.py
│   │   └── utils/
│   │       └── formatting.py
│   └── tests/
│       ├── test_news_scraper.py
│       ├── test_quant_analyst.py
│       ├── test_data_persistence.py
│       ├── test_human_approval.py
│       ├── test_finalize.py
│       ├── test_mock_execution.py
│       ├── test_error_handler.py
│       ├── test_graph_builder.py
│       ├── test_repository.py
│       └── test_api.py
│
└── frontend/                       # Vue3 + Ant Design Vue
    ├── package.json
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
        │   ├── runs.ts             # runs / approve / trigger API
        │   └── recommendations.ts  # recommendations API
        ├── types/
        │   └── index.ts            # ApiResponse / RunOut / RecommendationOut 等
        ├── stores/
        │   ├── runs.ts             # Pinia store
        │   └── recommendations.ts
        ├── views/
        │   ├── HistoryView.vue
        │   ├── PendingView.vue
        │   └── RunDetailView.vue
        └── components/
            ├── RunTable.vue
            ├── RecommendationTable.vue
            ├── ActionTag.vue
            └── ApprovalBar.vue
```
