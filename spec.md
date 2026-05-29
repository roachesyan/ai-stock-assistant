# 产品需求文档与系统规格说明：AI 量化 Agent（v1.2 MVP）

## 1. 项目概述
使用 **LangGraph** 和 **LangChain** 构建一个多 Agent（Multi-Agent）系统，用于追踪全球前 10 大 AI 公司，聚合每日新闻/财务数据，生成量化分析/交易建议，并在任何模拟执行之前引入人工介入审批（Human-in-the-Loop，HITL）机制。系统对外暴露 **REST API**，并提供一个 **Web 前端**（Vue3 + Ant Design Vue）供人工查询每日推荐历史、审阅 AI 分析并点击确认/拒绝今日交易。所有结果均持久化存储于 **SQLite**。

项目采用 **monorepo** 结构，后端（Python/FastAPI）与前端（Vue3）位于同一仓库的 `backend/` 与 `frontend/` 目录下。

> ⚠️ **免责声明：** 本系统仅用于技术研究与学习目的，所有分析结果与「交易操作」均为**模拟**，不构成任何投资建议。真实投资决策请咨询持牌专业人士并自行承担风险。

## 2. 技术栈

### 2.1 后端（`backend/`）
*   **编程语言：** Python 3.10+
*   **核心框架：** LangGraph、LangChain
*   **LLM 提供商：** Anthropic（Claude 3.5 Sonnet）或 OpenAI（GPT-4o）
*   **API 框架：** FastAPI（搭配 Uvicorn）
*   **数据库：** SQLite（通过 `aiosqlite` 实现异步支持）
*   **状态持久化：** LangGraph Checkpointer（`SqliteSaver` / `AsyncSqliteSaver`）
*   **数据校验：** Pydantic v2（用于 LLM 结构化输出与 API 模型）
*   **工具/API：** `yfinance`（用于获取股票代码/基础数据）、`Tavily` 或 `DuckDuckGo Search`（用于新闻抓取）。

### 2.2 前端（`frontend/`）
*   **框架：** Vue 3（Composition API，`<script setup>`）
*   **UI 组件库：** Ant Design Vue 4.x
*   **构建工具：** Vite
*   **路由：** Vue Router 4
*   **状态管理：** Pinia
*   **HTTP 客户端：** axios
*   **语言：** TypeScript
*   **鉴权：** MVP 阶段**不引入鉴权**（无登录/无 token），仅预留后续扩展空间。

## 3. 核心图架构（StateGraph）
该 Agent 是一个**带条件分支的状态机**（而非纯粹的线性 DAG）。为支持 Web 前端的审批工作流，**持久化节点被前置到人工审批之前**：分析结果会先以 `PENDING` 状态落库，从而让前端在审批前就能查询并展示完整的分析内容。整体流程如下：

```
News_Scraper → Quant_Analyst → Data_Persistence (status=PENDING, 写入 recommendations)
                                          │
                                  [interrupt: Human_Approval]
                                          │  (CLI 输入 Y/N 或前端调用 approve API)
                                          ▼
                                  Finalize (更新 run 状态)
                                          │
                          ┌───────────────┴───────────────┐
                       APPROVED                         REJECTED
                          │                                │
                   Mock_Execution                         END
                          │
                         END

任意节点抛出异常 → Error_Handler（标记 run 为 ERROR）→ END
```

> **设计说明（相比 v1.1 的变更）：** v1.1 在审批后才落库，导致 `PENDING` 的 run 没有可供前端展示的数据。v1.2 将持久化前移：分析完成后立即以 `PENDING` 写入 `analysis_runs` 与 `recommendations`，审批结果由 `Finalize` 节点更新 `status`（`APPROVED` / `REJECTED`）与 `approved_at`。这样「查询历史 + 待审批展示 + 点击确认」三类前端操作都基于同一份持久化数据。

### 3.1 节点定义

*   **节点 1：`News_Scraper_Node`（新闻抓取节点）**
    *   **输入：** 目标股票代码列表（例如 AAPL、MSFT、NVDA、GOOGL、META、TSLA、AMD、TSM、ASML、AVGO）。
    *   **任务：** 为每个股票代码获取最新的前 3 条新闻文章以及当前股价。
    *   **输出：** 聚合后的原始数据字典（含新闻与价格）。
    *   **错误处理：** yfinance / 搜索接口失败时进行重试（带退避），全部失败则将该 run 标记为 `ERROR` 并记录原因。
*   **节点 2：`Quant_Analyst_Node`（量化分析师节点）**
    *   **输入：** 聚合后的原始数据。
    *   **任务：** 将数据传递给 LLM，并使用特定提示词让其扮演资深量化分析师（Senior Quant Analyst）。通过 Pydantic + `with_structured_output()` 让 LLM 输出**强类型结构化结果**，针对每个股票代码包含：`Reasoning`（分析推理）、`Sentiment_Score`（情绪评分，1-10）以及 `Action`（操作：BUY/HOLD/SELL）。
    *   **输出：** 格式化的交易策略报告（含每个 ticker 的结构化结果）。
    *   **错误处理：** LLM 调用失败或输出校验失败时重试；超过重试上限则将 run 标记为 `ERROR`。
*   **节点 3：`Data_Persistence_Node`（数据持久化节点）** ——「**前置**」
    *   **输入：** 结构化分析结果、原始数据（用于取价格）。
    *   **任务：** 以 `PENDING` 状态写入 `analysis_runs`，并将每个股票代码的推荐结果作为 `recommendations` 表的单独一行写入（含 `run_date`、ticker、reasoning、sentiment_score、action、price_at_analysis）。
    *   **输出：** 确认 `run_id` 已落库（`run_id` 在初始化时即生成，等于 `thread_id`）。
*   **节点 4：`Human_Approval_Node`（人工审批节点，Human-in-the-Loop）**
    *   **机制：** 使用 LangGraph 的 `interrupt_before` 特性中断执行。此时 run 已为 `PENDING` 且数据可查。
    *   **CLI 模式：** 将分析报告打印到控制台，等待用户的 CLI 输入（Y/N）。
    *   **服务器模式：** 中断后 run 处于 `PENDING`，前端通过待审批队列展示，由审批 API（见 4.1）注入决策并恢复执行。
    *   **恢复机制：** 依赖 Checkpointer + `thread_id`（详见 4.4）。
*   **节点 5：`Finalize_Node`（审批落定节点）**
    *   **输入：** 审批决策（`approval_status`）。
    *   **任务：** 更新对应 `analysis_runs` 的 `status` 为 `APPROVED` / `REJECTED`，并在 `APPROVED` 时写入 `approved_at`。
    *   **输出：** 更新后的状态。
*   **节点 6：`Mock_Execution_Node`（模拟执行节点）**
    *   **进入条件：** 仅当审批为 `APPROVED` 时执行。
    *   **任务：** 打印 "✅ EXECUTING TRADES: [BUY/SELL 操作列表]"（被拒绝的 run 不进入本节点，控制台/日志输出 "🚫 TRADES REJECTED BY ARCHITECT."）。
*   **节点 E：`Error_Handler_Node`（错误处理节点）**
    *   **进入条件：** 上游任意节点抛出未捕获异常。
    *   **任务：** 将对应 `analysis_runs.status` 置为 `ERROR`，记录 `error_message`，安全结束本次 run。

## 4. REST API

通过 FastAPI 暴露 REST API，供前端与外部系统查询推荐数据并完成审批。

> **CORS：** 服务器模式启用 `CORSMiddleware`，允许前端开发地址（默认 `http://localhost:5173`）跨域访问。允许的来源可通过环境变量 `CORS_ORIGINS` 配置。

### 4.1 接口端点

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| GET | `/api/recommendations/latest` | 获取最近一天所有股票代码的推荐结果 |
| GET | `/api/recommendations/{date}` | 获取指定日期（YYYY-MM-DD）的推荐结果 |
| GET | `/api/recommendations/ticker/{ticker}/latest` | 获取指定股票代码的最新推荐结果 |
| GET | `/api/recommendations/ticker/{ticker}/history` | 获取指定股票代码的历史推荐结果（分页） |
| POST | `/api/run/trigger` | 手动触发一次新的分析运行（异步，返回 `202` + `run_id`） |
| GET | `/api/runs` | 列出所有分析运行及其汇总信息（分页，支持按状态/日期筛选） |
| GET | `/api/runs/{run_id}` | 查询指定 run 的状态、详情及其全部推荐结果 |
| GET | `/api/runs/pending` | 获取所有待审批（`PENDING`）的 run 队列 |
| POST | `/api/run/{run_id}/approve` | 提交审批结果（确认买入/拒绝），恢复中断的图执行 |

**`GET /api/runs/{run_id}`** 返回 run 概要 + 其下全部 `recommendations`，供前端「审阅/详情页」一次性渲染。

**`POST /api/run/{run_id}/approve` 请求体：**

```json
{
  "decision": "APPROVED"   // 或 "REJECTED"，等价于 CLI 的 Y/N
}
```

### 4.2 响应格式

所有接口返回统一信封（envelope）。分页类接口在 `meta` 中携带分页信息。

```json
{
  "success": true,
  "data": [],
  "error": null,
  "meta": {
    "total": 10,
    "date": "2025-01-15",
    "run_id": "uuid-string",
    "page": 1,
    "page_size": 20,
    "total_pages": 5
  }
}
```

失败响应：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "RUN_NOT_FOUND",
    "message": "未找到指定的 run_id"
  },
  "meta": null
}
```

### 4.3 统一错误码

| HTTP 状态码 | error.code | 说明 |
|--------|------|-------------|
| 400 | `INVALID_PARAMETER` | 请求参数非法（如日期格式错误） |
| 400 | `INVALID_DECISION` | 审批结果非法（非 APPROVED/REJECTED） |
| 404 | `RESOURCE_NOT_FOUND` | 资源不存在（日期/ticker 无数据） |
| 404 | `RUN_NOT_FOUND` | 指定 run_id 不存在 |
| 409 | `RUN_NOT_PENDING` | 该 run 当前不处于待审批状态 |
| 422 | `VALIDATION_ERROR` | 请求体校验失败 |
| 500 | `INTERNAL_ERROR` | 服务内部错误 |
| 502 | `UPSTREAM_ERROR` | 上游依赖（yfinance/搜索/LLM）失败 |

### 4.4 分页规范

分页类接口（`/recommendations/ticker/{ticker}/history`、`/runs`）统一支持：

| 查询参数 | 类型 | 默认值 | 说明 |
|--------|------|-------------|------|
| `page` | int | 1 | 页码，从 1 开始 |
| `page_size` | int | 20 | 每页条数，最大 100 |

`/runs` 额外支持可选筛选：`status`（PENDING/APPROVED/REJECTED/ERROR）、`date`（YYYY-MM-DD）。分页结果通过响应 `meta` 中的 `total`、`page`、`page_size`、`total_pages` 返回。

### 4.5 服务运行模式

系统支持两种运行模式：
- **CLI 模式**（`python -m src.main`）：运行图一次，进行交互式 HITL 审批（控制台输入 Y/N），保存到 SQLite，然后退出。
- **服务器模式**（`python -m src.main --serve`）：启动 FastAPI 服务器，供前端与外部系统使用。
  - 分析运行可通过 `POST /api/run/trigger` 触发或定时调度（cron）。
  - 触发为**异步**操作（抓新闻 + LLM 耗时较长）：接口立即返回 `202 Accepted` 与 `run_id`，分析在后台任务中执行。
  - 后台分析在写入 `PENDING` 数据后，执行到 `Human_Approval_Node` 时中断。
  - 前端轮询 `/api/runs/pending` 或 `/api/runs/{run_id}` 获取待审批项并展示分析内容，再通过 `POST /api/run/{run_id}/approve` 提交结果，由系统基于 Checkpointer 恢复图执行。

### 4.6 状态恢复（Checkpointer）

服务器模式下的「中断 → 审批 → 恢复」依赖 LangGraph 的持久化能力：
- 使用 `SqliteSaver` / `AsyncSqliteSaver` 作为 checkpointer，将图状态持久化到 SQLite。
- 每次 run 使用唯一 `thread_id`（与 `run_id` 一致），用于在审批后定位并恢复对应的中断执行。
- 即使服务重启，`PENDING` 的 run 仍可被恢复，不会丢失中间状态。

## 5. Web 前端（Vue3 + Ant Design Vue）

前端是一个单页应用（SPA），通过后端 REST API 读写数据。MVP 阶段不含鉴权。

### 5.1 页面与功能

| 页面 | 路由 | 功能 |
|------|------|------|
| **推荐历史** | `/` 或 `/history` | 以表格列出所有分析运行（按日期倒序），展示运行日期、状态、推荐数量、创建/审批时间；支持按状态与日期筛选、分页；点击某行进入详情。**「人工如何审核」**通过 `status`（APPROVED/REJECTED）与 `approved_at` 体现。 |
| **待审批队列** | `/pending` | 列出所有 `PENDING` 的 run，提示人工去审核；点击进入审阅页。 |
| **运行详情 / 审阅** | `/runs/:runId` | 展示该 run 下每个 ticker 的建议（BUY/HOLD/SELL）、情绪评分、推理、分析时价格。若 run 为 `PENDING`，页面底部显示「✅ 确认买入」「🚫 拒绝」按钮（调用 approve API）；非 PENDING 则只读展示审批结果。 |

顶部布局提供「触发今日分析」按钮（调用 `POST /api/run/trigger`），触发后引导用户到待审批队列。

### 5.2 关键交互流程

**人工审核今日是否购买：**
1. 用户打开「待审批队列」，看到今日 `PENDING` 的 run。
2. 点击进入「运行详情/审阅」页，查看每只股票的 AI 建议与推理。
3. 点击「确认买入」或「拒绝」→ 前端调用 `POST /api/run/{run_id}/approve`。
4. 后端恢复图执行、更新状态，前端刷新展示最终结果（已审批/已拒绝）。

**查询每日推荐历史：**
1. 用户打开「推荐历史」，按日期/状态筛选。
2. 点击任意历史 run 查看详情，了解当日 AI 给出的建议以及人工最终的审批结论。

### 5.3 前后端联调
- 开发期通过 Vite dev server 代理：`/api` → `http://localhost:8000`（避免 CORS 配置）；同时后端开启 `CORSMiddleware` 作为兜底。
- API 基址通过环境变量 `VITE_API_BASE_URL` 配置（`.env.development` / `.env.production`）。
- 前端 TypeScript 类型与后端 Pydantic 响应模型一一对应（`ApiResponse<T>`、`RunOut`、`RecommendationOut` 等）。

## 6. 数据库设计（SQLite）

> **通用约定：** 连接时开启外键约束 `PRAGMA foreign_keys = ON;`。

### 6.1 数据表

**`analysis_runs`** —— 记录分析流水线的每一次执行：

| 列名 | 类型 | 说明 |
|--------|------|-------------|
| id | TEXT（主键） | UUID（同时用作 LangGraph 的 thread_id） |
| run_date | TEXT | 运行日期（YYYY-MM-DD） |
| status | TEXT | "PENDING"、"APPROVED"、"REJECTED"、"ERROR" |
| error_message | TEXT | 错误原因（仅 status=ERROR 时填充，可为空） |
| created_at | TEXT | ISO 8601 时间戳 |
| approved_at | TEXT | ISO 8601 时间戳（审批通过时填充，可为空） |

> **状态流转：** run 创建时为 `PENDING`（数据已写入），审批后变为 `APPROVED` / `REJECTED`，异常时为 `ERROR`。

**`recommendations`** —— 存储每个股票代码的分析结果：

| 列名 | 类型 | 说明 |
|--------|------|-------------|
| id | INTEGER（主键） | 自增 |
| run_id | TEXT（外键） | 引用 analysis_runs.id，`ON DELETE CASCADE` |
| run_date | TEXT | 冗余的运行日期（YYYY-MM-DD），用于按日期高效查询 |
| ticker | TEXT | 股票代码 |
| reasoning | TEXT | LLM 生成的分析文本 |
| sentiment_score | INTEGER | 1-10 评分 |
| action | TEXT | "BUY"、"HOLD" 或 "SELL" |
| price_at_analysis | REAL | 分析时的股价 |
| created_at | TEXT | ISO 8601 时间戳 |

> **设计说明：** `recommendations` 表冗余了 `run_date` 列。这样按日期查询推荐结果（4.1 的 `/recommendations/{date}`）可直接走单表索引，无需 join `analysis_runs`，查询更简单高效。

### 6.2 外键定义

```sql
FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
```

删除某次 run 时，其下所有 `recommendations` 行级联删除，避免孤儿数据。

### 6.3 索引

- `idx_recommendations_run_id`：建立在 `recommendations(run_id)` 上
- `idx_recommendations_ticker`：建立在 `recommendations(ticker)` 上
- `idx_recommendations_run_date`：建立在 `recommendations(run_date)` 上（基于冗余列，单表索引）
- `idx_recommendations_ticker_date`：建立在 `recommendations(ticker, run_date)` 上（按 ticker + 日期查询历史）
- `idx_analysis_runs_date`：建立在 `analysis_runs(run_date)` 上
- `idx_analysis_runs_status`：建立在 `analysis_runs(status)` 上（用于快速检索 PENDING 队列）

## 7. 状态定义（TypedDict）
精确定义 `AgentState`，用于在各节点之间传递数据。相比 v1.0，补充了**价格数据**与**错误信息**字段，保证数据链路完整：

```python
from typing import TypedDict, List, Dict, Optional


class TickerNews(TypedDict):
    """单个股票代码的原始抓取数据。"""
    news: List[str]          # 最新的前 3 条新闻
    price: float             # 当前股价


class TickerAnalysis(TypedDict):
    """单个股票代码的结构化分析结果（与 Pydantic 模型对应）。"""
    ticker: str
    reasoning: str
    sentiment_score: int     # 1-10
    action: str              # "BUY" / "HOLD" / "SELL"
    price_at_analysis: float


class AgentState(TypedDict):
    tickers: List[str]
    raw_news_data: Dict[str, TickerNews]      # 含新闻与价格
    analyses: List[TickerAnalysis]            # 结构化分析结果
    analysis_report: str                      # 给人审阅的格式化报告
    approval_status: str                      # "PENDING" / "APPROVED" / "REJECTED" / "ERROR"
    run_id: Optional[str]                     # 当前分析运行的 UUID（= thread_id，初始化时生成）
    error_message: Optional[str]              # 出错时的原因
```

> **LLM 结构化输出建议：** 使用 Pydantic v2 模型（对应上面的 `TickerAnalysis`）配合 LangChain 的 `with_structured_output()`，由框架负责解析与校验，避免手工解析 JSON 带来的格式漂移问题。

## 8. 健壮性与错误处理

- **统一错误捕获：** 每个节点内部使用 try/except，捕获到异常后写入 `error_message` 并将路由导向 `Error_Handler_Node`，最终把 run 标记为 `ERROR`，不会让整图崩溃。
- **外部依赖重试：** 对 yfinance、新闻搜索、LLM 调用增加重试 + 指数退避；对外部 API 设置速率限制（rate limit），避免触发对方限流或封禁。
- **超时控制：** 为所有网络/LLM 调用设置合理超时，防止单次 run 长时间挂起。
- **部分失败策略：** 若个别 ticker 抓取失败，可记录该 ticker 状态并继续处理其余 ticker（而非整批失败），具体策略在实现时确定。
- **前端错误展示：** 前端统一拦截 `ApiResponse.error`，用 Ant Design `message` / `notification` 提示，区分参数错误、资源不存在、状态冲突等。

## 9. 配置与依赖

### 9.1 后端环境变量（`backend/.env`）

通过 `.env` 文件（配合 `python-dotenv`）管理密钥与配置，**不得提交到版本库**（加入 `.gitignore`），并提供 `.env.example` 模板：

```ini
# LLM 提供商（二选一）
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
LLM_PROVIDER=anthropic            # anthropic | openai

# 新闻搜索
TAVILY_API_KEY=tvly-xxx           # 使用 Tavily 时需要

# 数据库 / 服务
DATABASE_PATH=./data/quant.db
API_HOST=0.0.0.0
API_PORT=8000

# 跨域（前端开发地址）
CORS_ORIGINS=http://localhost:5173

# 目标股票代码（逗号分隔，可覆盖默认 Top 10）
TICKERS=AAPL,MSFT,NVDA,GOOGL,META,TSLA,AMD,TSM,ASML,AVGO
```

### 9.2 前端环境变量（`frontend/.env.*`）

```ini
# frontend/.env.development
VITE_API_BASE_URL=/api            # 走 Vite 代理

# frontend/.env.production
VITE_API_BASE_URL=https://your-api-host/api
```

### 9.3 依赖清单

- **后端：** 使用 `pyproject.toml` 锁定依赖。核心：`langgraph`、`langgraph-checkpoint-sqlite`、`langchain`、`langchain-anthropic` / `langchain-openai`、`fastapi`、`uvicorn`、`aiosqlite`、`pydantic`、`yfinance`、`tavily-python` / `duckduckgo-search`、`python-dotenv`。
- **前端：** 使用 `package.json`。核心：`vue`、`ant-design-vue`、`vue-router`、`pinia`、`axios`、`dayjs`；开发依赖：`vite`、`@vitejs/plugin-vue`、`typescript`、`vue-tsc`。

## 10. 测试策略

- **后端单元测试：** 对各节点逻辑、数据库读写、API 响应封装进行单元测试；通过 mock 隔离 yfinance、搜索与 LLM 等外部依赖。
- **结构化输出测试：** 校验 LLM 输出能被 Pydantic 模型正确解析，覆盖非法/缺字段等边界场景。
- **API 测试：** 使用 FastAPI 的 `TestClient` 覆盖各端点的成功/失败路径、分页与错误码。
- **图流程测试：** 用 in-memory checkpointer 验证「持久化(PENDING) → 中断 → 审批 → 恢复」在 APPROVED / REJECTED / ERROR 三条分支下的行为。
- **前端测试：** 组件与 store 单元测试用 `vitest` + `@vue/test-utils`；API 层用 mock。
- **测试框架：** 后端 `pytest`（异步用 `pytest-asyncio`）；前端 `vitest`。

## 11. Monorepo 结构（顶层）

```
ai-stock-assistant/
├── README.md                 # monorepo 总览 + 启动说明
├── doc/                      # 设计文档
│   ├── architecture-design.md
│   └── detailed-design.md
├── spec.md
├── CLAUDE.md
├── backend/                  # Python / FastAPI / LangGraph
│   ├── pyproject.toml
│   ├── .env.example
│   ├── data/
│   ├── src/
│   └── tests/
└── frontend/                 # Vue3 + Ant Design Vue
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── index.html
    └── src/
```

> 详细的目录结构见 `doc/architecture-design.md`，各模块详细设计见 `doc/detailed-design.md`。
