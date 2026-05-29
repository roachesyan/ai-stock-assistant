# Detailed Design: AI Quant Agent v1.2 MVP

> **v1.2 关键变更：** 项目改造为 monorepo（`backend/` + `frontend/`）；持久化节点前置到人工审批之前（先写 `PENDING`），新增 `Finalize_Node` 在审批后更新 run 状态；新增 Vue3 + Ant Design Vue 前端。后端代码路径前缀由 `src/` 调整为 `backend/src/`。

---

## 1. State Definition

### 1.1 AgentState

文件：`backend/src/models/state.py`

相比 v1.0 补充了**价格数据**（`TickerNews.price`）、**结构化分析结果**（`analyses`）与**错误信息**（`error_message`），保证数据链路完整。`run_id` 在初始化时即生成（= thread_id）。

```python
from typing import TypedDict, List, Dict, Optional


class TickerNews(TypedDict):
    """单个 ticker 的原始抓取数据。"""
    ticker: str
    price: float
    price_change_pct: float
    articles: List[str]          # 最新前 3 条新闻


class TickerAnalysis(TypedDict):
    """单个 ticker 的结构化分析结果（与 Pydantic 模型对应）。"""
    ticker: str
    reasoning: str
    sentiment_score: int         # 1-10
    action: str                  # "BUY" / "HOLD" / "SELL"
    price_at_analysis: float


class AgentState(TypedDict):
    tickers: List[str]
    raw_news_data: Dict[str, TickerNews]      # 含新闻与价格
    analyses: List[TickerAnalysis]            # 结构化分析结果
    analysis_report: str                      # 给人审阅的格式化报告
    approval_status: str                      # "PENDING" | "APPROVED" | "REJECTED" | "ERROR"
    run_id: Optional[str]                     # UUID（= LangGraph thread_id，初始化生成）
    error_message: Optional[str]              # 出错时的原因
```

### 1.2 State Lifecycle

| Phase | Field | Before | After |
|-------|-------|--------|-------|
| Init | tickers / run_id / approval_status | `[...]` / `<uuid>` / `"PENDING"` | — |
| Node 1 | raw_news_data | `{}` | `{"AAPL": {...}, ...}` |
| Node 2 | analyses / analysis_report | `[]` / `""` | 结构化列表 + 格式化报告 |
| Node 3 | (写库副作用) | — | analysis_runs(PENDING) + recommendations |
| Node 4 | approval_status | `"PENDING"` | `"APPROVED"` or `"REJECTED"` |
| Node 5 | (写库副作用) | — | 更新 status / approved_at |
| Node E | approval_status / error_message | — | `"ERROR"` / 错误原因 |

---

## 2. Database Design

### 2.1 Schema DDL

文件：`backend/src/db/init_db.py`

```sql
CREATE TABLE IF NOT EXISTS analysis_runs (
    id            TEXT PRIMARY KEY,
    run_date      TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'PENDING',
    error_message TEXT,
    created_at    TEXT    NOT NULL,
    approved_at   TEXT
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

CREATE INDEX IF NOT EXISTS idx_recommendations_run_id      ON recommendations(run_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_ticker      ON recommendations(ticker);
CREATE INDEX IF NOT EXISTS idx_recommendations_run_date    ON recommendations(run_date);
CREATE INDEX IF NOT EXISTS idx_recommendations_ticker_date ON recommendations(ticker, run_date);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_date          ON analysis_runs(run_date);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_status        ON analysis_runs(status);
```

> **设计说明：** `recommendations` 冗余 `run_date` 列，按日期查询走单表索引，无需 join；`run_id` 外键 `ON DELETE CASCADE`，删除 run 时级联清理推荐结果，避免孤儿数据。

### 2.2 Connection Management

文件：`backend/src/db/connection.py`

```python
import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "stock_assistant.db"

async def get_connection() -> aiosqlite.Connection:
    """获取 SQLite 异步连接。启用 WAL 模式和外键约束。"""
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")   # 必须开启，否则 CASCADE 不生效
    return db
```

**设计决策**：
- 使用 **WAL 模式** 支持并发读写（单写多读）
- 启用 **外键约束** 保证数据完整性与级联删除
- 数据库文件存放在 `backend/data/` 目录，通过 `.gitignore` 排除

### 2.3 Repository Layer

文件：`backend/src/db/repository.py`

采用 Repository 模式封装数据访问：

```python
class AnalysisRepository:
    async def create_run(self, run_id: str, run_date: str, status: str = "PENDING") -> None: ...
    async def update_run_status(self, run_id: str, status: str,
                                approved_at: str | None = None,
                                error_message: str | None = None) -> None: ...
    async def save_recommendations(self, run_id: str, run_date: str, recommendations: list[dict]) -> None: ...
    async def get_latest_recommendations(self) -> list[dict]: ...
    async def get_recommendations_by_date(self, date: str) -> list[dict]: ...
    async def get_latest_by_ticker(self, ticker: str) -> dict | None: ...
    async def get_ticker_history(self, ticker: str, page: int, page_size: int) -> tuple[list[dict], int]: ...
    async def list_runs(self, page: int, page_size: int,
                        status: str | None = None, date: str | None = None) -> tuple[list[dict], int]: ...
    async def get_run_by_id(self, run_id: str) -> dict | None: ...
    async def get_run_with_recommendations(self, run_id: str) -> dict | None: ...
    async def list_pending_runs(self) -> list[dict]: ...
```

> 分页方法返回 `(rows, total)` 元组，便于在 API 层计算 `total_pages`。`get_run_with_recommendations` 供前端详情页一次性获取 run + 其推荐。

---

## 3. Node Implementations

> 节点顺序（v1.2）：News_Scraper → Quant_Analyst → **Data_Persistence(PENDING)** → [interrupt] Human_Approval → **Finalize** → (Mock_Execution | END)。

### 3.1 News_Scraper_Node

文件：`backend/src/nodes/news_scraper.py`

**职责**：对每个 ticker 并发获取股价和新闻。

```
Input:  state.tickers
Output: {"raw_news_data": Dict[str, TickerNews]}
```

**流程**：

```
For each ticker in state.tickers (concurrent):
  1. yfinance.Ticker(ticker).fast_info → current_price, previous_close → price_change_pct
  2. Tavily/DuckDuckGo search "{ticker} stock news" → top 3 article summaries
  3. Assemble TickerNews dict
Aggregate into raw_news_data; return {"raw_news_data": result}
```

**错误处理**：单个 ticker 失败不阻塞其他（部分失败策略）；失败 ticker 标记 `price: 0.0, articles: ["ERROR: ..."]`；全部失败 → 抛异常路由到 `Error_Handler_Node`。

**依赖**：`backend/src/tools/stock_data.py`, `backend/src/tools/news_search.py`

---

### 3.2 Quant_Analyst_Node

文件：`backend/src/nodes/quant_analyst.py`

**职责**：将聚合数据传递给 LLM，输出结构化交易建议。

```
Input:  state.raw_news_data
Output: {"analyses": List[TickerAnalysis], "analysis_report": str}
```

**流程**：

```
1. Format raw_news_data into human-readable context string
2. Build prompt from template (backend/src/prompts/quant_analyst.py)
3. Call LLM via LangChain structured output: llm.with_structured_output(QuantReport)
4. 校验通过的结构化结果 → 填充 analyses + price_at_analysis（从 raw_news_data 取价）
5. 生成可读 analysis_report
6. Return {"analyses": [...], "analysis_report": "..."}
```

**结构化输出（Pydantic 模型）**：

```python
from pydantic import BaseModel, Field
from typing import Literal, List

class TickerRecommendation(BaseModel):
    ticker: str
    reasoning: str = Field(..., description="2-3 句分析")
    sentiment_score: int = Field(..., ge=1, le=10)
    action: Literal["BUY", "HOLD", "SELL"]

class QuantReport(BaseModel):
    recommendations: List[TickerRecommendation]
```

> 使用 `with_structured_output()` 由框架负责解析与校验，避免手工解析 JSON 的格式漂移问题。

**错误处理**：校验失败 → 重试 1 次；仍失败 → 缺失 ticker 回退默认值 `{reasoning: "Parse error", sentiment_score: 5, action: "HOLD"}`，或标记 `ERROR`。

**依赖**：`backend/src/config/llm.py`, `backend/src/prompts/quant_analyst.py`, `backend/src/models/schemas.py`

---

### 3.3 Data_Persistence_Node（前置，写 PENDING）

文件：`backend/src/nodes/data_persistence.py`

**职责**：在人工审批**之前**将分析结果以 `PENDING` 状态落库，使前端能查询并展示待审批内容。

```
Input:  state.run_id, state.analyses, state.raw_news_data
Output: {}  (无 state 修改；写库副作用)
```

**流程**：

```
1. run_id 已在初始化生成；run_date = today (YYYY-MM-DD)
2. create_run(run_id, run_date, status="PENDING")
   - created_at = now (ISO 8601)；approved_at = null
3. For each analysis in state.analyses:
   - Insert into recommendations (含冗余 run_date, price_at_analysis)
4. 使用事务保证 analysis_runs 与 recommendations 一致
```

**错误处理**：写入失败 → 记录日志并将 run 标记为 ERROR（不静默丢失）。

**依赖**：`backend/src/db/repository.py`

---

### 3.4 Human_Approval_Node

文件：`backend/src/nodes/human_approval.py`

**职责**：在 `interrupt_before` 处中断，等待人工审批。此时 run 已为 `PENDING` 且数据可查。

```
Input:  state.analysis_report
Output: {"approval_status": str}
```

**CLI 模式流程**：

```
1. Format analysis_report for console (表格 + X BUY / Y HOLD / Z SELL 汇总)
2. Prompt: "Approve these trades? (Y/N): "
3. "Y" → {"approval_status": "APPROVED"}；"N" → {"approval_status": "REJECTED"}
   其它 → 重提示（最多 3 次，默认 REJECTED）
```

**服务器模式流程**：

```
1. 中断时 run 已为 PENDING（前端可见）
2. 审批结果由 POST /api/run/{run_id}/approve 注入
3. 通过 checkpointer + thread_id 恢复执行
```

**LangGraph 集成**：

```python
graph = builder.compile(
    checkpointer=checkpointer,            # SqliteSaver / AsyncSqliteSaver
    interrupt_before=["human_approval"],
)

config = {"configurable": {"thread_id": run_id}}
graph.invoke(initial_state, config=config)          # 运行至中断（此时已写 PENDING）
# 注入审批并恢复
graph.invoke({"approval_status": "APPROVED"}, config=config)
```

**依赖**：`backend/src/utils/formatting.py`, `backend/src/graph/checkpointer.py`

---

### 3.5 Finalize_Node（审批落定）

文件：`backend/src/nodes/finalize.py`

**职责**：根据审批决策更新已落库 run 的状态。

```
Input:  state.run_id, state.approval_status
Output: {}  (写库副作用)
```

**流程**：

```
1. 读取 approval_status (APPROVED / REJECTED)
2. update_run_status(run_id, status,
       approved_at = now if APPROVED else None)
3. recommendations 已在 Node 3 写入，无需重复写
```

**条件路由**：Finalize 之后由条件边决定走向——`APPROVED` → `Mock_Execution_Node`；`REJECTED` → END。

**依赖**：`backend/src/db/repository.py`

---

### 3.6 Mock_Execution_Node

文件：`backend/src/nodes/mock_execution.py`

**职责**：仅在 APPROVED 分支执行，输出模拟执行信息。

```
(仅 APPROVED 分支)
1. Filter analyses where action in ["BUY", "SELL"]
2. Print "✅ EXECUTING TRADES: [AAPL: BUY, NVDA: SELL, ...]"
3. Print "💾 Run {run_id} finalized as APPROVED"
4. 若全为 HOLD → "No actionable trades"

(REJECTED 分支不进入本节点) → "🚫 TRADES REJECTED BY ARCHITECT."
```

---

### 3.7 Error_Handler_Node

文件：`backend/src/nodes/error_handler.py`

```
Input:  state.run_id, state.error_message
Output: {"approval_status": "ERROR"}

1. update_run_status(run_id, "ERROR", error_message=...)
   （若 run 尚未创建则先 create_run 再标记）
2. Print "⚠️ RUN FAILED: {error_message}"
3. → END
```

**依赖**：`backend/src/db/repository.py`

---

## 4. Graph Construction

文件：`backend/src/graph/builder.py`

### 4.1 Graph Wiring

```python
from langgraph.graph import StateGraph, END
from src.models.state import AgentState
from src.nodes.news_scraper import news_scraper_node
from src.nodes.quant_analyst import quant_analyst_node
from src.nodes.data_persistence import data_persistence_node
from src.nodes.human_approval import human_approval_node
from src.nodes.finalize import finalize_node
from src.nodes.mock_execution import mock_execution_node
from src.nodes.error_handler import error_handler_node


def route_after_finalize(state: AgentState) -> str:
    return "mock_execution" if state["approval_status"] == "APPROVED" else END


def build_graph(checkpointer):
    graph = StateGraph(AgentState)

    graph.add_node("news_scraper", news_scraper_node)
    graph.add_node("quant_analyst", quant_analyst_node)
    graph.add_node("data_persistence", data_persistence_node)
    graph.add_node("human_approval", human_approval_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("mock_execution", mock_execution_node)
    graph.add_node("error_handler", error_handler_node)

    # 主链：抓取 → 分析 → 写 PENDING → 中断审批 → 落定
    graph.set_entry_point("news_scraper")
    graph.add_edge("news_scraper", "quant_analyst")
    graph.add_edge("quant_analyst", "data_persistence")
    graph.add_edge("data_persistence", "human_approval")
    graph.add_edge("human_approval", "finalize")

    # 条件边：仅 APPROVED 进入 mock_execution
    graph.add_conditional_edges(
        "finalize",
        route_after_finalize,
        {"mock_execution": "mock_execution", END: END},
    )
    graph.add_edge("mock_execution", END)
    graph.add_edge("error_handler", END)

    # 编译：在 human_approval 前中断（此时已写 PENDING）
    return graph.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_approval"],
    )
```

### 4.2 Graph Visualization

```
START ─▶ news_scraper ─▶ quant_analyst ─▶ data_persistence(PENDING) ─▶ [INTERRUPT] ─▶ human_approval ─▶ finalize
                                                                                                            │
                                                                          ┌─────────────────────────────────┴───────┐
                                                                      APPROVED                                  REJECTED
                                                                          ▼                                         ▼
                                                                   mock_execution ─▶ END                          END

任意节点异常 ─▶ error_handler ─▶ END
```

### 4.3 Checkpointer

文件：`backend/src/graph/checkpointer.py`

```python
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

def get_checkpointer(db_path: str):
    """CLI: SqliteSaver；Server: AsyncSqliteSaver。thread_id = run_id。"""
    ...
```

---

## 5. Backend API Design

### 5.1 FastAPI App Factory（含 CORS）

文件：`backend/src/api/app.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.routes import recommendations, runs
from src.config import settings

def create_app() -> FastAPI:
    app = FastAPI(title="AI Stock Assistant", version="1.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,   # 默认 ["http://localhost:5173"]
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(recommendations.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    return app
```

### 5.2 Response Models

文件：`backend/src/models/schemas.py`

```python
from pydantic import BaseModel
from typing import Optional, List, Generic, TypeVar

T = TypeVar("T")

class ApiError(BaseModel):
    code: str
    message: str

class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: Optional[T] = None
    error: Optional[ApiError] = None
    meta: Optional[dict] = None

class RecommendationOut(BaseModel):
    id: int
    run_id: str
    run_date: str
    ticker: str
    reasoning: str
    sentiment_score: int
    action: str
    price_at_analysis: float
    created_at: str

class RunOut(BaseModel):
    id: str
    run_date: str
    status: str
    error_message: Optional[str] = None
    created_at: str
    approved_at: Optional[str] = None
    recommendation_count: int = 0

class RunDetailOut(RunOut):
    recommendations: List[RecommendationOut] = []

class ApprovalIn(BaseModel):
    decision: str   # "APPROVED" | "REJECTED"

class PaginationMeta(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
```

### 5.3 Recommendations Routes

文件：`backend/src/api/routes/recommendations.py`

```
GET /api/recommendations/latest                     → ApiResponse[List[RecommendationOut]]
GET /api/recommendations/{date}                     → 校验日期(400) / 404 / List[RecommendationOut]
GET /api/recommendations/ticker/{ticker}/latest     → 校验 ticker(422) / 404 / RecommendationOut
GET /api/recommendations/ticker/{ticker}/history    → page/page_size 分页 + PaginationMeta
```

### 5.4 Runs Routes

文件：`backend/src/api/routes/runs.py`

```
GET  /api/runs
  - page/page_size 分页；可选 status / date 筛选
  - ApiResponse[List[RunOut]] + PaginationMeta

GET  /api/runs/{run_id}
  - 404 RUN_NOT_FOUND
  - ApiResponse[RunDetailOut]  (run 概要 + 其全部 recommendations，供前端详情/审阅页)

GET  /api/runs/pending
  - status = "PENDING" 队列
  - ApiResponse[List[RunOut]]

POST /api/run/trigger
  - 异步后台任务，202 Accepted
  - ApiResponse[{"run_id": str, "status": "STARTED"}]

POST /api/run/{run_id}/approve
  - Body: ApprovalIn {"decision": "APPROVED" | "REJECTED"}
  - 404 RUN_NOT_FOUND / 409 RUN_NOT_PENDING / 400 INVALID_DECISION
  - 通过 checkpointer(thread_id=run_id) 恢复中断的图
  - ApiResponse[RunDetailOut]  (返回更新后的 run)
```

### 5.5 Approve 端点处理逻辑

```
1. 读取 run = get_run_by_id(run_id)；不存在 → 404 RUN_NOT_FOUND
2. run.status != "PENDING" → 409 RUN_NOT_PENDING
3. decision 不在 {APPROVED, REJECTED} → 400 INVALID_DECISION
4. 用 checkpointer 恢复图：graph.invoke({"approval_status": decision},
       config={"configurable": {"thread_id": run_id}})
   → Finalize 更新 status / approved_at；APPROVED 时执行 Mock_Execution
5. 返回 get_run_with_recommendations(run_id)
```

### 5.6 Dependencies

文件：`backend/src/api/dependencies.py`

```python
from src.db.connection import get_connection
from src.db.repository import AnalysisRepository

async def get_repository() -> AnalysisRepository:
    conn = await get_connection()
    return AnalysisRepository(conn)
```

---

## 6. Tools Layer

### 6.1 Stock Data Tool — `backend/src/tools/stock_data.py`

```python
def get_stock_price(ticker: str) -> dict:
    """获取单个 ticker 的当前价格和涨跌幅。
    返回 {"price": float, "price_change_pct": float}。
    失败时重试（指数退避），全部失败抛出异常由上层处理。"""
```

### 6.2 News Search Tool — `backend/src/tools/news_search.py`

```python
def search_news(query: str, max_results: int = 3) -> list[str]:
    """优先 Tavily (需 API key)，回退 DuckDuckGo (免费)。含速率限制与重试。"""
```

---

## 7. Backend Configuration

### 7.1 Environment Variables

文件：`backend/src/config/settings.py` / 模板 `backend/.env.example`

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | Yes* | — | OpenAI API Key |
| `ANTHROPIC_API_KEY` | Yes* | — | Anthropic API Key |
| `LLM_PROVIDER` | No | `openai` | `openai` or `anthropic` |
| `TAVILY_API_KEY` | No | — | Tavily API Key (可选) |
| `TARGET_TICKERS` | No | 10 只默认 | 逗号分隔的 ticker 列表 |
| `DB_PATH` | No | `data/stock_assistant.db` | SQLite 数据库路径 |
| `API_HOST` | No | `0.0.0.0` | API 服务监听地址 |
| `API_PORT` | No | `8000` | API 服务端口 |
| `CORS_ORIGINS` | No | `http://localhost:5173` | 允许的前端来源（逗号分隔） |

*至少需要一个 LLM Provider 的 API Key。`.env` 不得提交版本库。

### 7.2 LLM Client Factory — `backend/src/config/llm.py`

```python
def get_llm() -> BaseChatModel:
    provider = settings.LLM_PROVIDER
    if provider == "anthropic":
        return ChatAnthropic(model="claude-3-5-sonnet-20241022")
    return ChatOpenAI(model="gpt-4o")
```

---

## 8. Prompt Design

文件：`backend/src/prompts/quant_analyst.py`

### System Prompt

```
You are a Senior Quant Analyst at a top-tier hedge fund.
Analyze the provided stock news and price data, then produce a trading
recommendation for each ticker.

For each ticker provide:
1. Reasoning: concise 2-3 sentence analysis of news sentiment and price action.
2. Sentiment_Score: integer 1 (extremely bearish) to 10 (extremely bullish).
3. Action: one of "BUY", "HOLD", "SELL".

Guidelines:
- Score 1-3: Bearish → SELL；4-6: Neutral → HOLD；7-10: Bullish → BUY
- Consider both news sentiment and price momentum.
- Be decisive — avoid defaulting to HOLD without justification.
```

> 结构化输出由 `with_structured_output(QuantReport)` 约束。

### Human Prompt Template

```
Analyze the following market data:

{formatted_data}

Provide a recommendation (Reasoning, Sentiment_Score, Action) for each ticker.
```

---

## 9. Entry Point

文件：`backend/src/main.py`

### 9.1 CLI Mode

```python
# cd backend && python -m src.main
1. Load .env；init config；init DB
2. Build checkpointer + graph
3. Initial state（run_id 预生成）:
   {tickers, raw_news_data={}, analyses=[], analysis_report="",
    approval_status="PENDING", run_id=<uuid>, error_message=None}
4. graph.invoke(initial_state, config={"configurable": {"thread_id": run_id}})
   → 运行至 interrupt（此时已写 PENDING 数据）
5. Print report；prompt Y/N
6. graph.invoke({"approval_status": ...}, config) → Finalize → (Mock_Execution|END)
7. Exit
```

### 9.2 Server Mode

```python
# cd backend && python -m src.main --serve [--port 8000]
1. Load .env；init config；init DB
2. create_app()（含 CORS）；start Uvicorn
3. POST /api/run/trigger → 后台任务启动分析（202 + run_id），写 PENDING 后中断
4. 前端展示 pending → POST /api/run/{run_id}/approve → checkpointer 恢复
```

---

## 10. Frontend Detailed Design

### 10.1 项目初始化

```bash
cd frontend
npm create vite@latest . -- --template vue-ts
npm install ant-design-vue@4 vue-router@4 pinia axios dayjs
```

`main.ts` 注册 Ant Design Vue、Pinia、Router：

```ts
import { createApp } from "vue";
import Antd from "ant-design-vue";
import "ant-design-vue/dist/reset.css";
import { createPinia } from "pinia";
import router from "./router";
import App from "./App.vue";

createApp(App).use(Antd).use(createPinia()).use(router).mount("#app");
```

### 10.2 Vite 代理

文件：`frontend/vite.config.ts`

```ts
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
```

### 10.3 TypeScript 类型

文件：`frontend/src/types/index.ts`（对应后端 Pydantic 模型）

```ts
export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
  meta: Record<string, any> | null;
}

export type RunStatus = "PENDING" | "APPROVED" | "REJECTED" | "ERROR";
export type Action = "BUY" | "HOLD" | "SELL";

export interface Recommendation {
  id: number;
  run_id: string;
  run_date: string;
  ticker: string;
  reasoning: string;
  sentiment_score: number;
  action: Action;
  price_at_analysis: number;
  created_at: string;
}

export interface Run {
  id: string;
  run_date: string;
  status: RunStatus;
  error_message?: string | null;
  created_at: string;
  approved_at?: string | null;
  recommendation_count: number;
}

export interface RunDetail extends Run {
  recommendations: Recommendation[];
}
```

### 10.4 API 客户端

文件：`frontend/src/api/client.ts`

```ts
import axios from "axios";

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api",
  timeout: 30000,
});

// 响应拦截器：解析统一信封，success=false 时抛错
client.interceptors.response.use((resp) => {
  const body = resp.data;
  if (body && body.success === false) {
    return Promise.reject(new Error(body.error?.message ?? "请求失败"));
  }
  return resp;
});

export default client;
```

文件：`frontend/src/api/runs.ts`

```ts
import client from "./client";
import type { ApiResponse, Run, RunDetail } from "../types";

export const listRuns = (params: { page?: number; page_size?: number; status?: string; date?: string }) =>
  client.get<ApiResponse<Run[]>>("/runs", { params }).then((r) => r.data);

export const listPendingRuns = () =>
  client.get<ApiResponse<Run[]>>("/runs/pending").then((r) => r.data);

export const getRun = (runId: string) =>
  client.get<ApiResponse<RunDetail>>(`/runs/${runId}`).then((r) => r.data);

export const approveRun = (runId: string, decision: "APPROVED" | "REJECTED") =>
  client.post<ApiResponse<RunDetail>>(`/run/${runId}/approve`, { decision }).then((r) => r.data);

export const triggerRun = () =>
  client.post<ApiResponse<{ run_id: string; status: string }>>("/run/trigger").then((r) => r.data);
```

### 10.5 路由

文件：`frontend/src/router/index.ts`

```ts
import { createRouter, createWebHistory } from "vue-router";

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/history" },
    { path: "/history", component: () => import("../views/HistoryView.vue") },
    { path: "/pending", component: () => import("../views/PendingView.vue") },
    { path: "/runs/:runId", component: () => import("../views/RunDetailView.vue"), props: true },
  ],
});
```

### 10.6 页面设计

| 页面 | 组件 / Ant Design | 说明 |
|------|------|------|
| **HistoryView** | `a-table` + `a-select`(status) + `a-date-picker` + `a-pagination` | 列：日期、状态(Tag)、推荐数、创建时间、审批时间、操作(查看)；筛选 + 分页调用 `listRuns` |
| **PendingView** | `a-table` / `a-list` | 仅 PENDING；每项「去审核」跳转详情；调用 `listPendingRuns` |
| **RunDetailView** | `a-descriptions` + `RecommendationTable` + `ApprovalBar` | 顶部 run 概要；中部每只股票建议表（`RecommendationTable`）；底部 `ApprovalBar`（仅 PENDING 显示「✅ 确认买入」「🚫 拒绝」），调用 `approveRun` |

### 10.7 复用组件

| 组件 | 职责 |
|------|------|
| `RunTable.vue` | 渲染 run 列表（被 History/Pending 复用），含状态 Tag、跳转 |
| `RecommendationTable.vue` | 渲染某 run 的 recommendations：ticker、ActionTag、评分(`a-progress`/数字)、价格、推理 |
| `ActionTag.vue` | 按 BUY(绿)/HOLD(蓝)/SELL(红) 渲染 `a-tag` |
| `ApprovalBar.vue` | 审批操作条：两个 `a-button` + `a-popconfirm` 二次确认 + loading 态 |

### 10.8 Pinia Store

文件：`frontend/src/stores/runs.ts`

```ts
import { defineStore } from "pinia";
import * as runsApi from "../api/runs";
import type { Run, RunDetail } from "../types";

export const useRunsStore = defineStore("runs", {
  state: () => ({
    runs: [] as Run[],
    pending: [] as Run[],
    current: null as RunDetail | null,
    total: 0,
    loading: false,
  }),
  actions: {
    async fetchRuns(params) { /* listRuns → 填充 runs/total */ },
    async fetchPending() { /* listPendingRuns → pending */ },
    async fetchRun(runId: string) { /* getRun → current */ },
    async approve(runId: string, decision: "APPROVED" | "REJECTED") {
      const res = await runsApi.approveRun(runId, decision);
      this.current = res.data;            // 刷新详情
      return res;
    },
  },
});
```

---

## 11. Testing Strategy

### 11.1 Backend Test Matrix

| Test Type | Scope | File | Mock Strategy |
|-----------|-------|------|---------------|
| Unit | `stock_data.get_stock_price` | `test_stock_data.py` | Mock yfinance |
| Unit | `news_search.search_news` | `test_news_search.py` | Mock Tavily/DDG |
| Unit | `news_scraper_node` | `test_news_scraper.py` | Mock tools |
| Unit | `quant_analyst_node` | `test_quant_analyst.py` | Mock LLM (structured output) |
| Unit | `data_persistence_node` (PENDING) | `test_data_persistence.py` | In-memory SQLite |
| Unit | `finalize_node` | `test_finalize.py` | In-memory SQLite |
| Unit | `mock_execution_node` | `test_mock_execution.py` | No mock |
| Unit | `error_handler_node` | `test_error_handler.py` | In-memory SQLite |
| Unit | `AnalysisRepository` | `test_repository.py` | In-memory SQLite |
| Unit | API endpoints (含 approve/pending/detail) | `test_api.py` | TestClient + in-memory DB |
| Integration | Full graph (PENDING→approve/reject/error) | `test_graph_builder.py` | Mock LLM + tools + in-memory checkpointer |

### 11.2 Backend Framework

pytest / pytest-asyncio / FastAPI TestClient / in-memory SQLite / pytest-cov (target 80%+)。

### 11.3 Key Test Cases（增量）

- **Data Persistence (前置)**：run 创建为 `PENDING`；recommendations 在审批前已写入；`run_date` 冗余列正确。
- **Finalize**：APPROVED → status=APPROVED 且 approved_at 非空；REJECTED → status=REJECTED 且 approved_at 为空；recommendations 不被二次写入。
- **审批流程 / 条件边**：PENDING → approve(APPROVED) → finalize → mock_execution；PENDING → approve(REJECTED) → finalize → END。
- **API**：`GET /api/runs/{id}` 返回 RunDetailOut（含 recommendations）；`POST approve` 覆盖 200/404/409/400；`/runs` 的 status/date 筛选。

### 11.4 Frontend Tests

- 框架：`vitest` + `@vue/test-utils`，API 层 mock。
- 用例：`RunTable` 渲染与跳转、`ActionTag` 颜色映射、`ApprovalBar` 在 PENDING 才显示并能触发 `approve`、store action 正确更新状态。

---

## 12. Dependencies

### 12.1 Backend — `backend/pyproject.toml`

```toml
[project]
name = "ai-stock-assistant"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "langgraph>=0.2",
    "langgraph-checkpoint-sqlite>=1.0",
    "langchain>=0.3",
    "langchain-openai>=0.2",
    "langchain-anthropic>=0.2",
    "yfinance>=0.2",
    "tavily-python>=0.5",
    "duckduckgo-search>=6.0",
    "python-dotenv>=1.0",
    "fastapi>=0.110",
    "uvicorn>=0.29",
    "aiosqlite>=0.20",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-cov>=5.0", "pytest-asyncio>=0.23", "httpx>=0.27"]
```

### 12.2 Frontend — `frontend/package.json`

```json
{
  "name": "ai-stock-assistant-frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vue-tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest"
  },
  "dependencies": {
    "vue": "^3.4.0",
    "ant-design-vue": "^4.2.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.0",
    "axios": "^1.7.0",
    "dayjs": "^1.11.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0",
    "typescript": "^5.4.0",
    "vue-tsc": "^2.0.0",
    "vite": "^5.2.0",
    "vitest": "^1.6.0",
    "@vue/test-utils": "^2.4.0"
  }
}
```

---

## 13. Implementation Order

| Phase | Tasks | Location |
|-------|-------|----------|
| **P1: Monorepo Scaffold** | 顶层 README、`backend/` 与 `frontend/` 骨架、各自 .gitignore | 仓库根 |
| **P2: Backend Models & Config** | State、Pydantic schemas（含 RunDetailOut/ApiError）、Settings（含 CORS）、LLM Factory | `backend/src/models`, `config` |
| **P3: Backend Database** | init_db（run_date/CASCADE）、connection、Repository（含 detail/pending/筛选） | `backend/src/db` |
| **P4: Backend Tools** | yfinance、News Search（重试/限流） | `backend/src/tools` |
| **P5: Backend Nodes** | 7 节点（含前置 Data_Persistence + Finalize + Error_Handler） | `backend/src/nodes` |
| **P6: Backend Prompts** | Quant Analyst prompt | `backend/src/prompts` |
| **P7: Backend Graph** | StateGraph（前置持久化 + 条件边）+ checkpointer | `backend/src/graph` |
| **P8: Backend API** | app(CORS)、routes（含 approve/pending/detail）、依赖注入 | `backend/src/api` |
| **P9: Backend Entry** | main.py CLI + Server | `backend/src/main.py` |
| **P10: Backend Tests** | 全部后端测试 | `backend/tests` |
| **P11: Frontend Scaffold** | Vite + Vue3 + TS、Ant Design Vue、Router、Pinia、代理 | `frontend/` |
| **P12: Frontend API & Types** | types、axios client、runs/recommendations API | `frontend/src/api`, `types` |
| **P13: Frontend Views** | History / Pending / RunDetail + 复用组件 | `frontend/src/views`, `components` |
| **P14: Frontend Tests & Polish** | vitest 组件/store 测试、错误提示、样式 | `frontend/` |
```
