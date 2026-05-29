# Detailed Design: AI Quant Agent v1.4 MVP

> **v1.4 关键变更：** 在 v1.3 自动执行 + 当日撤销的基础上，引入**双 Agent（分析师 + 风控）与三个有界循环**：
> 1. **结构化输出自修复**（节点内，≤ `MAX_SCHEMA_RETRIES`）；
> 2. **证据补充环**（`Evidence_Gatherer_Node`，≤ `MAX_EVIDENCE_ROUNDS`）；
> 3. **风控反思环**（`Risk_Reviewer_Node` 驳回 → 回分析师修订，≤ `MAX_RISK_ROUNDS`）。
> 风控轮次用尽默认「执行 + 标记」（`risk_verdict=REJECTED_AT_LIMIT`），可配置降级为 HOLD。图重新成为带环状态机；因无人工中断，仍**不需要 Checkpointer**（单次 invoke 内完成所有循环）。

---

## 1. State Definition

### 1.1 AgentState

文件：`backend/src/models/state.py`

```python
from typing import TypedDict, List, Dict, Optional


class TickerNews(TypedDict):
    """单个 ticker 的原始抓取数据。"""
    ticker: str
    price: float
    price_change_pct: float
    articles: List[str]          # 最新前 3 条新闻（证据补充环会追加）


class TickerAnalysis(TypedDict):
    """单个 ticker 的结构化分析结果（与 Pydantic 模型对应）。"""
    ticker: str
    reasoning: str
    sentiment_score: int         # 1-10
    action: str                  # "BUY" / "HOLD" / "SELL"
    price_at_analysis: float


class RiskIssue(TypedDict):
    ticker: str
    issue: str                   # 例如「情绪分 8 却给 SELL，自相矛盾」


class RiskReview(TypedDict):
    approved: bool
    issues: List[RiskIssue]
    overall_notes: str


class TradeExecution(TypedDict):
    ticker: str
    side: str                    # "BUY" / "SELL"
    price: float


class AgentState(TypedDict):
    tickers: List[str]
    raw_news_data: Dict[str, TickerNews]
    analyses: List[TickerAnalysis]
    analysis_report: str
    needs_more_evidence: List[str]            # 需补充证据的 ticker（证据补充环）
    evidence_rounds: int                      # 已执行证据补充轮数
    risk_review: Optional[RiskReview]         # 最近一次风控结论
    risk_feedback: Optional[str]              # 驳回时回传分析师的修订意见
    risk_rounds: int                          # 已执行风控反思轮数
    risk_verdict: Optional[str]               # "APPROVED" / "REJECTED_AT_LIMIT"
    executed_trades: List[TradeExecution]
    run_id: Optional[str]                     # UUID（初始化生成）
    error_message: Optional[str]
```

### 1.2 State Lifecycle

| Phase | Field | After |
|-------|-------|-------|
| Init | run_id / evidence_rounds / risk_rounds | `<uuid>` / `0` / `0` |
| news_scraper | raw_news_data | 抓取结果 |
| quant_analyst | analyses / needs_more_evidence / analysis_report | 结构化结果（每轮修订） |
| evidence_gatherer | raw_news_data / evidence_rounds | 追加证据，`+1` |
| risk_reviewer | risk_review / risk_feedback | 风控结论；驳回时 feedback |
| (risk loop) | risk_rounds | 每次驳回回退 `+1` |
| data_persistence | (写库) | analysis_runs(EXECUTED, risk_*) + recommendations |
| auto_execution | executed_trades (+写库) | BUY/SELL → trades |
| error_handler | error_message | run=ERROR |

---

## 2. Database Design

### 2.1 Schema DDL

文件：`backend/src/db/init_db.py`

```sql
CREATE TABLE IF NOT EXISTS analysis_runs (
    id              TEXT PRIMARY KEY,
    run_date        TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'EXECUTED',
    risk_verdict    TEXT,                          -- 'APPROVED' | 'REJECTED_AT_LIMIT'
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
```

> **设计说明：** `analysis_runs` 新增 `risk_verdict` / `risk_rounds` / `evidence_rounds` / `review_notes` 记录 AI 风控过程。逐条 risk issues 的 MVP 做法是把结构化结论序列化进 `review_notes`（JSON 文本）；后续可拆出 `risk_issues` 表。`run_id` 外键 `ON DELETE CASCADE` 级联清理 recs + trades。

### 2.2 Connection Management

文件：`backend/src/db/connection.py`（同 v1.3，开启 WAL + 外键）

```python
import aiosqlite
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "stock_assistant.db"

async def get_connection() -> aiosqlite.Connection:
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db
```

### 2.3 Repository Layer

文件：`backend/src/db/repository.py`

```python
class AnalysisRepository:
    # runs
    async def create_run(self, run_id: str, run_date: str,
                         status: str = "EXECUTED", risk_verdict: str | None = None,
                         risk_rounds: int = 0, evidence_rounds: int = 0,
                         review_notes: str | None = None) -> None: ...
    async def update_run_status(self, run_id: str, status: str, error_message: str | None = None) -> None: ...
    async def get_run_by_id(self, run_id: str) -> dict | None: ...
    async def get_run_with_details(self, run_id: str) -> dict | None: ...   # run + recs + trades
    async def list_runs(self, page: int, page_size: int, status: str | None = None,
                        date: str | None = None, risk_verdict: str | None = None) -> tuple[list[dict], int]: ...

    # recommendations
    async def save_recommendations(self, run_id: str, run_date: str, recommendations: list[dict]) -> None: ...
    async def get_latest_recommendations(self) -> list[dict]: ...
    async def get_recommendations_by_date(self, date: str) -> list[dict]: ...
    async def get_latest_by_ticker(self, ticker: str) -> dict | None: ...
    async def get_ticker_history(self, ticker: str, page: int, page_size: int) -> tuple[list[dict], int]: ...

    # trades
    async def save_trades(self, run_id: str, run_date: str, trades: list[dict]) -> None: ...
    async def get_trade_by_id(self, trade_id: int) -> dict | None: ...
    async def list_trades(self, page: int, page_size: int, run_id: str | None = None,
                          ticker: str | None = None, status: str | None = None,
                          date: str | None = None) -> tuple[list[dict], int]: ...
    async def list_today_trades(self, today: str) -> list[dict]: ...
    async def cancel_trade(self, trade_id: int, cancelled_at: str) -> None: ...
    async def cancel_run_trades(self, run_id: str, today: str, cancelled_at: str) -> int: ...
```

---

## 3. Node Implementations

> 节点（v1.4）：news_scraper → quant_analyst →(证据/风控两环)→ data_persistence → auto_execution → END。路由函数见 §3.8。异常 → error_handler。

### 3.1 News_Scraper_Node — `backend/src/nodes/news_scraper.py`

同 v1.3：yfinance 取价 + Tavily/DuckDuckGo 取 top 3 新闻 → 组装 `raw_news_data`。单 ticker 失败不阻塞；全部失败 → Error_Handler。

```
Input:  state.tickers
Output: {"raw_news_data": Dict[str, TickerNews]}
```

### 3.2 Quant_Analyst_Node — `backend/src/nodes/quant_analyst.py`

**职责**：LLM 结构化输出交易建议 + 标记证据缺口；支持消费风控反馈做修订；含**结构化输出自修复**循环。

```
Input:  state.raw_news_data, state.risk_feedback(可选), state.analyses(上一轮，可选)
Output: {"analyses": [...], "analysis_report": "...", "needs_more_evidence": [...]}
```

**Pydantic 模型**（`backend/src/models/schemas.py`）：

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
    needs_more_evidence: List[str] = Field(
        default_factory=list,
        description="信息不足、需要补充搜索的 ticker 列表；若充分则为空",
    )
```

**流程（含 schema 自修复循环）**：

```
1. 组装上下文：raw_news_data；若 risk_feedback 存在，附加「上一轮方案 + 风控意见，请针对性修订」
2. structured_llm = llm.with_structured_output(QuantReport)
3. for attempt in range(MAX_SCHEMA_RETRIES + 1):
     try:
         report = structured_llm.invoke(prompt)        # 校验由框架完成
         break
     except (ValidationError / OutputParserException) as e:
         if attempt == MAX_SCHEMA_RETRIES: raise        # → Error_Handler
         prompt += f"\n上次输出校验失败：{e}. 请严格按 schema 重新输出。"
4. analyses = [填充 price_at_analysis(取自 raw_news_data) for r in report.recommendations]
5. 生成 analysis_report
6. return {"analyses": analyses,
           "analysis_report": report_text,
           "needs_more_evidence": report.needs_more_evidence}
```

> 修订轮中，分析师必须参考 `risk_feedback` 调整 BUY/SELL/HOLD 或评分，并在 reasoning 中体现回应。

### 3.3 Evidence_Gatherer_Node — `backend/src/nodes/evidence_gatherer.py` (NEW)

**职责**：仅对 `needs_more_evidence` 中的 ticker 追加搜索，丰富 `raw_news_data`，回到分析师。

```
Input:  state.needs_more_evidence, state.raw_news_data, state.evidence_rounds
Output: {"raw_news_data": <updated>, "evidence_rounds": state.evidence_rounds + 1,
         "needs_more_evidence": []}    # 清空，待分析师重新评估

1. for ticker in state.needs_more_evidence:
     extra = search_news(f"{ticker} latest earnings guidance analyst outlook", max_results=5)
     raw_news_data[ticker].articles 合并去重 extra
2. evidence_rounds += 1
3. return 更新后的 raw_news_data（清空 needs_more_evidence，回到 quant_analyst 重判）
```

> 终止由 `route_after_analyst` 把关：即便分析师再次标记缺口，`evidence_rounds >= MAX_EVIDENCE_ROUNDS` 时也直接进入风控，防止死循环。

### 3.4 Risk_Reviewer_Node — `backend/src/nodes/risk_reviewer.py` (NEW)

**职责**：独立风控 Agent，审查分析师方案。

```
Input:  state.analyses, state.raw_news_data
Output: {"risk_review": RiskReview, "risk_feedback": <str|None>}
```

**Pydantic 模型**：

```python
class RiskIssueModel(BaseModel):
    ticker: str
    issue: str

class RiskReviewModel(BaseModel):
    approved: bool
    issues: List[RiskIssueModel] = Field(default_factory=list)
    overall_notes: str
```

**流程**：

```
1. 组装上下文：每个 ticker 的 action / sentiment_score / reasoning + 对应新闻摘要
2. risk_llm = llm.with_structured_output(RiskReviewModel)   # 同样适用 schema 自修复
3. review = risk_llm.invoke(risk_prompt)
4. risk_feedback = None if review.approved else 汇总 issues+overall_notes 成可执行的修订意见
5. return {"risk_review": review.model_dump(), "risk_feedback": risk_feedback}
```

**审查维度（写入 prompt）**：仓位是否过激（如几乎全 BUY）、动作是否与新闻矛盾（利空却 BUY）、`sentiment_score` 与 `action` 是否自洽（高分却 SELL）。

### 3.5 Data_Persistence_Node — `backend/src/nodes/data_persistence.py`

**职责**：写 run（含风控结论）+ recommendations。进入本节点前，路由已决定 `risk_verdict`。

```
Input:  state.run_id, state.analyses, state.risk_review, state.risk_verdict,
        state.risk_rounds, state.evidence_rounds
Output: {}  (写库副作用)

1. run_date = today()
2. review_notes = json.dumps(state.risk_review) if risk_review else None
3. create_run(run_id, run_date, status="EXECUTED",
              risk_verdict=state.risk_verdict,           # APPROVED | REJECTED_AT_LIMIT
              risk_rounds=state.risk_rounds,
              evidence_rounds=state.evidence_rounds,
              review_notes=review_notes)
4. save_recommendations(run_id, run_date, state.analyses)   # 事务
```

> `risk_verdict` 由 `route_after_risk` 写入 state（通过 → APPROVED；轮次用尽 → REJECTED_AT_LIMIT）。

### 3.6 Auto_Execution_Node — `backend/src/nodes/auto_execution.py`

**职责**：对 BUY/SELL 写 trades；在 `DOWNGRADE_TO_HOLD` 策略下跳过被风控否决的交易。

```
Input:  state.run_id, state.analyses, state.risk_review, state.risk_verdict
Output: {"executed_trades": [...]}

1. candidates = [a for a in analyses if a.action in ("BUY", "SELL")]
2. if RISK_LIMIT_POLICY == "DOWNGRADE_TO_HOLD" and risk_verdict == "REJECTED_AT_LIMIT":
       否决集 = {issue.ticker for issue in risk_review.issues}
       candidates = [a for a in candidates if a.ticker not in 否决集]
       # 被剔除者视为 HOLD，不下单（recommendations 已记录其原始 action 供审计）
3. trades = [{ticker, side: a.action, price: a.price_at_analysis} for a in candidates]
4. save_trades(run_id, run_date, trades)   # status=EXECUTED, executed_at=now（事务）
5. Print 已执行交易；空 → "No actionable trades"
6. return {"executed_trades": trades}
```

### 3.7 Error_Handler_Node — `backend/src/nodes/error_handler.py`

```
1. update_run_status(run_id, "ERROR", error_message=...)（run 不存在则先 create_run）
2. Print "⚠️ RUN FAILED: {error_message}" → END
```

### 3.8 路由函数 — `backend/src/nodes/routing.py` (NEW)

```python
from langgraph.graph import END
from src.config import settings
from src.models.state import AgentState

def route_after_analyst(state: AgentState) -> str:
    if state["needs_more_evidence"] and state["evidence_rounds"] < settings.MAX_EVIDENCE_ROUNDS:
        return "evidence_gatherer"
    return "risk_reviewer"

def route_after_risk(state: AgentState) -> dict | str:
    review = state["risk_review"]
    if review and review["approved"]:
        return "approved"          # → 写 risk_verdict=APPROVED → data_persistence
    if state["risk_rounds"] < settings.MAX_RISK_ROUNDS:
        return "revise"            # → risk_rounds++ → 回 quant_analyst
    return "limit_reached"         # → risk_verdict=REJECTED_AT_LIMIT → data_persistence
```

> 因 LangGraph 条件边的目标需为节点名/END，`route_after_risk` 的三个分支在 `builder.py` 中映射为：`approved`/`limit_reached` → 经一个轻量「定稿」步骤写入 `risk_verdict` 后到 `data_persistence`；`revise` → 回 `quant_analyst`。定稿与计数更新可在小工具节点或在 risk_reviewer 出口处理（见 §4.1 注释）。

---

## 4. Graph Construction

文件：`backend/src/graph/builder.py`

### 4.1 Graph Wiring（带三个有界循环，无 checkpointer）

```python
from langgraph.graph import StateGraph, END
from src.config import settings
from src.models.state import AgentState
from src.nodes.news_scraper import news_scraper_node
from src.nodes.quant_analyst import quant_analyst_node
from src.nodes.evidence_gatherer import evidence_gatherer_node
from src.nodes.risk_reviewer import risk_reviewer_node
from src.nodes.data_persistence import data_persistence_node
from src.nodes.auto_execution import auto_execution_node
from src.nodes.error_handler import error_handler_node
from src.nodes.routing import route_after_analyst


def route_after_risk(state: AgentState) -> str:
    review = state["risk_review"]
    if review and review["approved"]:
        return "data_persistence"          # 通过
    if state["risk_rounds"] < settings.MAX_RISK_ROUNDS:
        return "quant_analyst"             # 驳回 → 修订
    return "data_persistence"              # 轮次用尽 → 仍执行


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("news_scraper", news_scraper_node)
    g.add_node("quant_analyst", quant_analyst_node)
    g.add_node("evidence_gatherer", evidence_gatherer_node)
    g.add_node("risk_reviewer", risk_reviewer_node)
    g.add_node("data_persistence", data_persistence_node)
    g.add_node("auto_execution", auto_execution_node)
    g.add_node("error_handler", error_handler_node)

    g.set_entry_point("news_scraper")
    g.add_edge("news_scraper", "quant_analyst")

    # 证据补充环：analyst → (evidence_gatherer → analyst) | risk_reviewer
    g.add_conditional_edges(
        "quant_analyst",
        route_after_analyst,
        {"evidence_gatherer": "evidence_gatherer", "risk_reviewer": "risk_reviewer"},
    )
    g.add_edge("evidence_gatherer", "quant_analyst")     # 回边

    # 风控反思环：risk_reviewer → quant_analyst(修订) | data_persistence
    g.add_conditional_edges(
        "risk_reviewer",
        route_after_risk,
        {"quant_analyst": "quant_analyst", "data_persistence": "data_persistence"},
    )

    g.add_edge("data_persistence", "auto_execution")
    g.add_edge("auto_execution", END)
    g.add_edge("error_handler", END)

    return g.compile()    # 无 interrupt_before、无 checkpointer
```

> **计数与 verdict 落点（实现约定）：**
> - `evidence_rounds++` 在 `evidence_gatherer_node` 内完成。
> - `risk_rounds++` 在「驳回回退」时完成：可在 `risk_reviewer_node` 出口根据是否将驳回来递增，或在分析师入口检测到 `risk_feedback` 时递增。推荐在 `route_after_risk` 选择 `quant_analyst` 前，由 `risk_reviewer_node` 设置 `risk_feedback` 并 `risk_rounds++`。
> - `risk_verdict` 在进入 `data_persistence` 前确定：风控 `approved` → `APPROVED`；否则（必为轮次用尽路径）→ `REJECTED_AT_LIMIT`。可由 `data_persistence_node` 依据 `risk_review.approved` 与 `risk_rounds` 推断写入，避免额外节点。

### 4.2 Graph Visualization

```
START ─▶ news_scraper ─▶ quant_analyst ──route_after_analyst──┐
                              ▲                                │
                              │            ┌───────────────────┴────────┐
        (回边) evidence_gatherer◀──────  需补证据&未超轮              证据充分
                              ▲                                          │
                              │                                          ▼
        (回边, risk_feedback) │◀────route_after_risk──────────  risk_reviewer
                              │           │                              
              驳回&未超轮 ────┘           ├── 通过 ───────▶ data_persistence ─▶ auto_execution ─▶ END
                                          └── 轮次用尽 ────▶ data_persistence (REJECTED_AT_LIMIT) ─▶ ...

quant_analyst 内部：schema 校验失败 → 带反馈重试（≤ MAX_SCHEMA_RETRIES）
任意节点异常 ─▶ error_handler ─▶ END
```

---

## 5. Backend API Design

### 5.1 FastAPI App Factory（含 CORS）

文件：`backend/src/api/app.py`（同 v1.3，version 升至 1.4.0；挂载 recommendations / runs / trades 路由）

### 5.2 Response Models

文件：`backend/src/models/schemas.py`（新增 `RiskIssueOut` / `RiskReviewOut`，`RunOut` 增加风控字段）

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

class TradeOut(BaseModel):
    id: int
    run_id: str
    run_date: str
    ticker: str
    side: str
    price: float
    status: str
    executed_at: str
    cancelled_at: Optional[str] = None
    cancellable: bool = False

class RiskIssueOut(BaseModel):
    ticker: str
    issue: str

class RiskReviewOut(BaseModel):
    approved: bool
    issues: List[RiskIssueOut] = []
    overall_notes: str = ""

class RunOut(BaseModel):
    id: str
    run_date: str
    status: str
    risk_verdict: Optional[str] = None     # APPROVED | REJECTED_AT_LIMIT
    risk_rounds: int = 0
    evidence_rounds: int = 0
    error_message: Optional[str] = None
    created_at: str
    recommendation_count: int = 0
    trade_count: int = 0

class RunDetailOut(RunOut):
    risk_review: Optional[RiskReviewOut] = None    # 由 review_notes 反序列化
    recommendations: List[RecommendationOut] = []
    trades: List[TradeOut] = []

class CancelResultOut(BaseModel):
    cancelled_count: int

class PaginationMeta(BaseModel):
    total: int
    page: int
    page_size: int
    total_pages: int
```

### 5.3 Recommendations Routes — `backend/src/api/routes/recommendations.py`

同 v1.3（latest / {date} / ticker latest / ticker history 分页）。

### 5.4 Runs Routes — `backend/src/api/routes/runs.py`

```
GET  /api/runs
  - page/page_size 分页；可选 status / date / risk_verdict 筛选
  - ApiResponse[List[RunOut]] + PaginationMeta

GET  /api/runs/{run_id}
  - 404 RUN_NOT_FOUND
  - ApiResponse[RunDetailOut]  (run + risk_review(由 review_notes 反序列化) + recommendations + trades)

POST /api/run/trigger
  - 异步后台任务，202（后台跑完三循环 + 自动执行）
  - ApiResponse[{"run_id": str, "status": "STARTED"}]

POST /api/runs/{run_id}/cancel
  - 批量撤销该 run「当天 + EXECUTED」的交易
  - 404 RUN_NOT_FOUND
  - ApiResponse[CancelResultOut]
```

### 5.5 Trades Routes — `backend/src/api/routes/trades.py`

```
GET  /api/trades                       → 分页 + run_id/ticker/status/date 筛选
GET  /api/trades/today                 → 当天交易（cancellable 标注）
POST /api/trades/{trade_id}/cancel     → 当日撤销（404 / 409）
```

### 5.6 撤销端点处理逻辑（同 v1.3）

```
单笔: get_trade_by_id → 不存在 404 → run_date != today 409 → status != EXECUTED 409
      → cancel_trade(status=CANCELLED, cancelled_at=now) → 返回 TradeOut
批量: get_run_by_id → 不存在 404 → cancel_run_trades(run_id, today, now) 仅撤当天 EXECUTED → 返回 cancelled_count
```

`today()` / `now_iso()` 见 `backend/src/utils/dates.py`。

### 5.7 Dependencies — `backend/src/api/dependencies.py`（同 v1.3）

---

## 6. Tools Layer

### 6.1 Stock Data — `backend/src/tools/stock_data.py`

```python
def get_stock_price(ticker: str) -> dict:
    """返回 {"price": float, "price_change_pct": float}；失败重试（指数退避）。"""
```

### 6.2 News Search — `backend/src/tools/news_search.py`

```python
def search_news(query: str, max_results: int = 3) -> list[str]:
    """优先 Tavily，回退 DuckDuckGo；含速率限制与重试。证据补充环复用本函数（更具体的 query、更大 max_results）。"""
```

### 6.3 Dates — `backend/src/utils/dates.py`

```python
from datetime import datetime
def today() -> str: return datetime.now().strftime("%Y-%m-%d")
def now_iso() -> str: return datetime.now().isoformat()
```

---

## 7. Backend Configuration

文件：`backend/src/config/settings.py` / 模板 `backend/.env.example`

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | No | `glm` | `glm` \| `anthropic` \| `openai` |
| `GLM_API_KEY` | provider=glm 时必填 | — | 智谱开放平台 API Key（形如 `id.secret`） |
| `GLM_BASE_URL` | No | `https://open.bigmodel.cn/api/anthropic` | GLM 的 Anthropic 兼容端点 |
| `GLM_MODEL` | No | `glm-5.1` | GLM 模型名 |
| `ANTHROPIC_API_KEY` | provider=anthropic 时必填 | — | 官方 Anthropic API Key |
| `ANTHROPIC_MODEL` | No | `claude-3-5-sonnet-20241022` | 官方 Anthropic 模型名 |
| `OPENAI_API_KEY` | provider=openai 时必填 | — | OpenAI API Key |
| `OPENAI_MODEL` | No | `gpt-4o` | OpenAI 模型名 |
| `LLM_TIMEOUT_MS` | No | `300000` | LLM 调用超时（毫秒）。GLM 较慢可调大，如 `3000000` |
| `TAVILY_API_KEY` | No | — | Tavily API Key (可选) |
| `TARGET_TICKERS` | No | 10 只默认 | 逗号分隔的 ticker 列表 |
| `DB_PATH` | No | `data/stock_assistant.db` | SQLite 数据库路径 |
| `API_HOST` | No | `0.0.0.0` | API 服务监听地址 |
| `API_PORT` | No | `8000` | API 服务端口 |
| `CORS_ORIGINS` | No | `http://localhost:5173` | 允许的前端来源（逗号分隔） |
| `MAX_SCHEMA_RETRIES` | No | `2` | 结构化输出自修复次数 |
| `MAX_EVIDENCE_ROUNDS` | No | `2` | 证据补充环上限 |
| `MAX_RISK_ROUNDS` | No | `3` | 风控反思环上限 |
| `RISK_LIMIT_POLICY` | No | `EXECUTE_AND_FLAG` | `EXECUTE_AND_FLAG` \| `DOWNGRADE_TO_HOLD` |

*按所选 `LLM_PROVIDER` 提供对应的 API Key。`.env` 不得提交版本库（已在 `.gitignore`），仅提交占位符的 `.env.example`。

> **默认使用智谱 GLM（推荐）：** 本项目默认 `LLM_PROVIDER=glm`，通过 GLM 的 **Anthropic 兼容端点** 复用 `langchain-anthropic` 的 `ChatAnthropic`。这与 Claude Code 指向 GLM 的思路一致：用 base_url + api_key + model 三件套指过去。注意本项目变量名是自有的（`GLM_API_KEY`/`GLM_BASE_URL`/`GLM_MODEL`），**不是** Claude Code 的 `ANTHROPIC_AUTH_TOKEN` 等变量。

`backend/.env`（使用 GLM 时的示例）：

```ini
LLM_PROVIDER=glm
GLM_API_KEY=replace-with-your-glm-token          # 形如 73b4...：id.secret
GLM_BASE_URL=https://open.bigmodel.cn/api/anthropic
GLM_MODEL=glm-5.1
LLM_TIMEOUT_MS=3000000
```

LLM 工厂 `backend/src/config/llm.py`：

```python
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel
from src.config import settings


def get_llm() -> BaseChatModel:
    """根据 LLM_PROVIDER 返回 LangChain ChatModel。
    默认 glm：走智谱 Anthropic 兼容端点，复用 ChatAnthropic。"""
    timeout_s = settings.LLM_TIMEOUT_MS / 1000

    if settings.LLM_PROVIDER == "glm":
        return ChatAnthropic(
            model=settings.GLM_MODEL,            # glm-5.1
            api_key=settings.GLM_API_KEY,        # 智谱 token
            base_url=settings.GLM_BASE_URL,      # https://open.bigmodel.cn/api/anthropic
            timeout=timeout_s,
            max_retries=2,
        )

    if settings.LLM_PROVIDER == "anthropic":
        return ChatAnthropic(model=settings.ANTHROPIC_MODEL, timeout=timeout_s, max_retries=2)

    return ChatOpenAI(model=settings.OPENAI_MODEL, timeout=timeout_s, max_retries=2)
```

> **结构化输出注意事项（重要）：** 本项目分析师/风控均用 `with_structured_output()`，底层走 tool calling。GLM 的 Anthropic 兼容端点为 Claude Code 设计、支持工具调用，预期可用；接入后请重点验证两个 Agent 的结构化输出是否稳定（结构化自修复循环会兜底偶发偏差）。若发现 GLM 在 Anthropic 端点下工具调用不稳，备选方案：改用 GLM 的 **OpenAI 兼容端点**——`LLM_PROVIDER=openai`，`OPENAI_API_KEY=<GLM token>`，并将 `ChatOpenAI(base_url="https://open.bigmodel.cn/api/paas/v4")`、`OPENAI_MODEL=glm-5.1`。

> **安全：** GLM token 等同密码，切勿写入代码或提交版本库；若曾在不安全渠道（聊天/截图）暴露，请到智谱开放平台重置。分析师与风控可共用同一 LLM 实例（不同 prompt + 不同 structured schema），也可各自配置模型；MVP 共用。

---

## 8. Prompt Design

### 8.1 分析师 — `backend/src/prompts/quant_analyst.py`

System Prompt（在 v1.3 基础上增加证据缺口与修订指令）：

```
You are a Senior Quant Analyst at a top-tier hedge fund.
Analyze the provided stock news and price data, then produce a trading
recommendation for each ticker.

For each ticker provide:
1. Reasoning: concise 2-3 sentence analysis.
2. Sentiment_Score: integer 1 (extremely bearish) to 10 (extremely bullish).
3. Action: one of "BUY", "HOLD", "SELL".

Also return `needs_more_evidence`: a list of tickers whose available news is
insufficient to decide confidently (empty if all sufficient).

If a RISK REVIEW feedback is provided, you MUST address each concern and revise
your prior recommendations accordingly, explaining the change in Reasoning.

Guidelines: 1-3 → SELL; 4-6 → HOLD; 7-10 → BUY. Be decisive; keep score/action consistent.
```

Human Prompt（修订轮附加）：

```
Market data:
{formatted_data}

{optional: Previous recommendations: {prev}\nRisk review feedback to address: {risk_feedback}}
```

### 8.2 风控 — `backend/src/prompts/risk_reviewer.py` (NEW)

System Prompt：

```
You are an independent Risk Officer reviewing a quant analyst's trade plan.
Approve only if the plan is sound. Reject (approved=false) if you find issues such as:
- Over-aggressive positioning (e.g. almost everything BUY).
- An action contradicting the news (e.g. BUY on clearly bearish news).
- Sentiment_Score inconsistent with Action (e.g. score 8 but SELL, or score 2 but BUY).

Return: approved (bool), issues (list of {ticker, issue}), overall_notes.
When rejecting, make issues specific and actionable so the analyst can revise.
```

> ⚠️ 系统会自动执行；风控是最后的 AI 关卡。prompt 强调审慎，文档/前端展示免责声明。两个 Agent 均用 `with_structured_output`。

---

## 9. Entry Point

文件：`backend/src/main.py`

### 9.1 CLI Mode

```python
# cd backend && python -m src.main
1. Load .env；init config；init DB；build graph（无 checkpointer）
2. Initial state（run_id 预生成，计数置 0）:
   {tickers, raw_news_data={}, analyses=[], analysis_report="",
    needs_more_evidence=[], evidence_rounds=0,
    risk_review=None, risk_feedback=None, risk_rounds=0, risk_verdict=None,
    executed_trades=[], run_id=<uuid>, error_message=None}
3. graph.invoke(initial_state)
   → 抓取 →(分析↔证据)→(分析↔风控)→ 落库 → 自动执行（无交互）
4. 打印风控结论(risk_verdict) 与已执行交易；exit
```

### 9.2 Server Mode

```python
# cd backend && python -m src.main --serve [--port 8000]
1. Load .env；init config；init DB
2. create_app()（含 CORS）；start Uvicorn
3. POST /api/run/trigger → 后台任务完整跑完（三循环 + 自动执行），202 + run_id
4. 前端通过 /api/runs/{id}（风控卡片）、/api/trades/today（撤销）查看与操作
```

---

## 10. Frontend Detailed Design

### 10.1 初始化 / 代理 / 入口

同 v1.3（Vite + Vue3 + TS + Ant Design Vue + Pinia + Router；`/api` 代理到 :8000）。

### 10.2 TypeScript 类型 — `frontend/src/types/index.ts`（在 v1.3 基础上增加风控类型与 run 风控字段）

```ts
export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: { code: string; message: string } | null;
  meta: Record<string, any> | null;
}

export type RunStatus = "EXECUTED" | "ERROR";
export type RiskVerdict = "APPROVED" | "REJECTED_AT_LIMIT";
export type Action = "BUY" | "HOLD" | "SELL";
export type Side = "BUY" | "SELL";
export type TradeStatus = "EXECUTED" | "CANCELLED";

export interface Recommendation {
  id: number; run_id: string; run_date: string; ticker: string;
  reasoning: string; sentiment_score: number; action: Action;
  price_at_analysis: number; created_at: string;
}

export interface Trade {
  id: number; run_id: string; run_date: string; ticker: string;
  side: Side; price: number; status: TradeStatus;
  executed_at: string; cancelled_at?: string | null; cancellable: boolean;
}

export interface RiskIssue { ticker: string; issue: string; }
export interface RiskReview { approved: boolean; issues: RiskIssue[]; overall_notes: string; }

export interface Run {
  id: string; run_date: string; status: RunStatus;
  risk_verdict?: RiskVerdict | null; risk_rounds: number; evidence_rounds: number;
  error_message?: string | null; created_at: string;
  recommendation_count: number; trade_count: number;
}

export interface RunDetail extends Run {
  risk_review?: RiskReview | null;
  recommendations: Recommendation[];
  trades: Trade[];
}
```

### 10.3 API 客户端

文件：`frontend/src/api/client.ts`（同 v1.3：axios + 信封拦截器）。
文件：`frontend/src/api/runs.ts`（`listRuns` 增加 `risk_verdict` 筛选参数；`getRun` 返回 `RunDetail`；`triggerRun`；`cancelRunTrades`）。
文件：`frontend/src/api/trades.ts`（`listTodayTrades` / `listTrades` / `cancelTrade`，同 v1.3）。

```ts
// runs.ts 关键签名
export const listRuns = (params: {
  page?: number; page_size?: number; status?: string; date?: string; risk_verdict?: string;
}) => client.get<ApiResponse<Run[]>>("/runs", { params }).then(r => r.data);

export const getRun = (runId: string) =>
  client.get<ApiResponse<RunDetail>>(`/runs/${runId}`).then(r => r.data);
```

### 10.4 路由 — `frontend/src/router/index.ts`

```ts
routes: [
  { path: "/", redirect: "/history" },
  { path: "/history", component: () => import("../views/HistoryView.vue") },
  { path: "/today", component: () => import("../views/TodayTradesView.vue") },
  { path: "/runs/:runId", component: () => import("../views/RunDetailView.vue"), props: true },
]
```

### 10.5 页面设计

| 页面 | 组件 / Ant Design | 说明 |
|------|------|------|
| **HistoryView** | `a-table` + status/risk_verdict `a-select` + `a-date-picker` + `a-pagination` | 列：日期、状态、**风控结论**(Tag：通过/⚠️未通过仍执行)、推荐数、交易数、创建时间、查看 |
| **TodayTradesView** | `TradeTable` + 刷新 | 当天交易，`cancellable` 显示 `CancelButton` |
| **RunDetailView** | `a-descriptions` + `RiskReviewCard` + `RecommendationTable` + `TradeTable` | run 概要 + AI 风控卡片 + 建议 + 交易；当天交易可撤销 |

### 10.6 复用组件

| 组件 | 职责 |
|------|------|
| `RunTable.vue` | run 列表，状态/风控 Tag、跳转 |
| `RecommendationTable.vue` | recommendations：ticker、ActionTag、评分、价格、推理 |
| `TradeTable.vue` | trades：ticker、side、price、status、时间、CancelButton（按 `cancellable`） |
| `RiskReviewCard.vue` (NEW) | 渲染 `risk_review`：approved 徽标、逐条 issues 列表、overall_notes；`REJECTED_AT_LIMIT` 时 `a-alert` 警示 |
| `ActionTag.vue` | BUY(绿)/HOLD(蓝)/SELL(红) |
| `CancelButton.vue` | `a-popconfirm` + danger `a-button` + loading；`cancellable=false` 禁用 |

### 10.7 Pinia Store — `frontend/src/stores/trades.ts`（同 v1.3：fetchToday / cancel）。`stores/runs.ts` 的 `fetchRun` 填充含 `risk_review` 的 `RunDetail`。

---

## 11. Testing Strategy

### 11.1 Backend Test Matrix

| Test Type | Scope | File | Mock Strategy |
|-----------|-------|------|---------------|
| Unit | `stock_data` / `news_search` | `test_stock_data.py` / `test_news_search.py` | Mock yfinance / Tavily/DDG |
| Unit | `news_scraper_node` | `test_news_scraper.py` | Mock tools |
| Unit | `quant_analyst_node`（含 schema 自修复） | `test_quant_analyst.py` | Mock LLM（首错后正确 / 持续错） |
| Unit | `evidence_gatherer_node` | `test_evidence_gatherer.py` | Mock search |
| Unit | `risk_reviewer_node` | `test_risk_reviewer.py` | Mock LLM（approve / reject） |
| Unit | 路由 / 循环终止 | `test_routing.py` | 构造 state 断言分支 |
| Unit | `data_persistence_node` / `auto_execution_node` | 对应文件 | In-memory SQLite |
| Unit | `error_handler_node` | `test_error_handler.py` | In-memory SQLite |
| Unit | `AnalysisRepository`（runs/recs/trades + risk_*） | `test_repository.py` | In-memory SQLite |
| Unit | 撤销规则（当日/重复/批量） | `test_trades_cancel.py` | In-memory SQLite |
| Unit | API endpoints | `test_api.py` | TestClient + in-memory DB |
| Integration | 全图三循环各分支 | `test_graph_builder.py` | Mock LLM + tools + in-memory DB |

### 11.2 Framework

pytest / pytest-asyncio / FastAPI TestClient / in-memory SQLite / pytest-cov (target 80%+)。

### 11.3 Key Test Cases（循环相关）

- **Schema 自修复**：首次输出非法 → 重试后合法 → 成功填充 analyses；连续非法超 `MAX_SCHEMA_RETRIES` → 抛错 → run=ERROR。
- **证据补充环**：analyst 标记 needs_more_evidence → route_after_analyst → evidence_gatherer（evidence_rounds++）→ 回 analyst；`evidence_rounds == MAX_EVIDENCE_ROUNDS` 后即便仍标记也进 risk_reviewer（防失控）。
- **风控反思环**：
  - reject → route_after_risk → quant_analyst（risk_rounds++，带 risk_feedback）→ 分析师修订 → 再审。
  - approve → data_persistence，run.risk_verdict=APPROVED。
  - 连续 reject 至 `risk_rounds == MAX_RISK_ROUNDS` → data_persistence，run.risk_verdict=REJECTED_AT_LIMIT。
- **轮次用尽策略**：
  - `EXECUTE_AND_FLAG`：被否方案照常生成 trades；run 标 REJECTED_AT_LIMIT。
  - `DOWNGRADE_TO_HOLD`：风控 issues 命中的 ticker 的 BUY/SELL 不生成 trade；未命中者正常执行。
- **自动执行 / 撤销 / API / Repository / CASCADE**：同 v1.3 关键用例 + RunDetailOut 含 risk_review、`/runs` 的 risk_verdict 筛选。

### 11.4 Frontend Tests

`vitest` + `@vue/test-utils`：`RiskReviewCard` 渲染 approved/issues/notes 与 REJECTED_AT_LIMIT 警示；`TradeTable`/`CancelButton` 按 `cancellable` 控制；history 的 risk_verdict 筛选；store action。

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

> 仍无需 `langgraph-checkpoint-sqlite`：三个循环在单次 `invoke` 内同步完成，无中断恢复需求。

### 12.2 Frontend — `frontend/package.json`（同 v1.3）

```json
{
  "name": "ai-stock-assistant-frontend",
  "private": true,
  "type": "module",
  "scripts": { "dev": "vite", "build": "vue-tsc -b && vite build", "preview": "vite preview", "test": "vitest" },
  "dependencies": {
    "vue": "^3.4.0", "ant-design-vue": "^4.2.0", "vue-router": "^4.3.0",
    "pinia": "^2.1.0", "axios": "^1.7.0", "dayjs": "^1.11.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.0.0", "typescript": "^5.4.0", "vue-tsc": "^2.0.0",
    "vite": "^5.2.0", "vitest": "^1.6.0", "@vue/test-utils": "^2.4.0"
  }
}
```

---

## 13. Implementation Order

| Phase | Tasks | Location |
|-------|-------|----------|
| **P1: Monorepo Scaffold** | 顶层 README、`backend/`/`frontend/` 骨架、各自 .gitignore | 仓库根 |
| **P2: Backend Models & Config** | State（含 risk/evidence 字段）、schemas（QuantReport / RiskReviewModel / RunDetailOut / TradeOut）、Settings（含三循环上限 + 风控策略）、LLM Factory | `backend/src/models`, `config` |
| **P3: Backend Database** | init_db（含 risk_* 列 + trades + 索引、CASCADE）、connection、Repository | `backend/src/db` |
| **P4: Backend Tools & Dates** | yfinance、News Search（重试/限流，供证据环复用）、`utils/dates.py` | `backend/src/tools`, `utils` |
| **P5: Backend Nodes & Routing** | 6 节点（含 evidence_gatherer + risk_reviewer + auto_execution + error_handler）+ routing.py | `backend/src/nodes` |
| **P6: Backend Prompts** | 分析师 + 风控 prompt | `backend/src/prompts` |
| **P7: Backend Graph** | StateGraph（节点 + 条件边/回边，三循环）+ 终止条件 | `backend/src/graph` |
| **P8: Backend API** | app(CORS)、routes（recommendations/runs(含 risk_verdict 筛选)/trades + 撤销）、依赖注入 | `backend/src/api` |
| **P9: Backend Entry** | main.py CLI + Server | `backend/src/main.py` |
| **P10: Backend Tests** | 全部后端测试（重点：三循环终止、轮次用尽策略、撤销规则） | `backend/tests` |
| **P11: Frontend Scaffold** | Vite + Vue3 + TS、Ant Design Vue、Router、Pinia、代理 | `frontend/` |
| **P12: Frontend API & Types** | types（含 RiskReview）、axios client、runs/recommendations/trades API | `frontend/src/api`, `types` |
| **P13: Frontend Views** | History（risk_verdict 筛选）/ TodayTrades / RunDetail + 组件（RiskReviewCard / TradeTable / CancelButton） | `frontend/src/views`, `components` |
| **P14: Frontend Tests & Polish** | vitest 组件/store 测试（风控卡片、撤销可用性）、错误提示、样式 | `frontend/` |
```
