# 产品需求文档与系统规格说明：AI 量化 Agent（v1.4 MVP）

## 1. 项目概述
使用 **LangGraph** 和 **LangChain** 构建一个多 Agent（Multi-Agent）系统，用于追踪全球前 10 大 AI 公司，聚合每日新闻/财务数据，由「分析师 Agent」生成量化分析/交易建议，再由「风控 Agent」做 AI 审查（替代人工事前审批），最终**自动模拟执行**对应的买入/卖出操作。人工不参与事前审批，而是事后**撤销**已执行的交易，且**仅限当天（同一 `run_date`）的交易可被撤销**。系统对外暴露 **REST API**，并提供一个 **Web 前端**（Vue3 + Ant Design Vue）供人工查询每日推荐历史、查看 AI 风控结论、查看当日已执行交易并一键撤销。所有结果均持久化存储于 **SQLite**。

项目采用 **monorepo** 结构，后端（Python/FastAPI）与前端（Vue3）位于同一仓库的 `backend/` 与 `frontend/` 目录下。

> **为什么用 LangGraph/LangChain：** v1.4 引入三个**有界循环**——结构化输出自修复、证据补充环、风控反思环。它们带有「循环 + 条件分支 + 终止条件」，正是 LangGraph 的核心能力；LangChain 负责 LLM 抽象与结构化输出。

## 2. 技术栈

### 2.1 后端（`backend/`）
*   **编程语言：** Python 3.10+
*   **核心框架：** LangGraph（带循环与条件分支的状态图）、LangChain
*   **LLM 提供商：** 默认 **智谱 GLM（glm-5.1）**，通过其 **Anthropic 兼容端点** 复用 `langchain-anthropic`；也支持官方 Anthropic（Claude 3.5 Sonnet）或 OpenAI（GPT-4o）。由 `LLM_PROVIDER` 切换（见 §9.1）。
*   **API 框架：** FastAPI（搭配 Uvicorn）
*   **数据库：** SQLite（通过 `aiosqlite` 实现异步支持）
*   **数据校验：** Pydantic v2（用于 LLM 结构化输出与 API 模型）
*   **工具/API：** `yfinance`（用于获取股票代码/基础数据）、`Tavily` 或 `DuckDuckGo Search`（用于新闻抓取）。

> **注（相比 v1.3）：** v1.3 是纯线性流水线。v1.4 在图中加入三个有界循环（见 §3），图重新成为带环的状态机。由于没有人工中断（`interrupt_before`），仍**不需要** LangGraph Checkpointer——所有循环都在单次 `invoke` 内同步跑完。

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
该 Agent 是一个**带三个有界循环的状态机**。分析师 Agent 与风控 Agent 协作迭代，最终自动执行交易。整体流程如下：

```
news_scraper → quant_analyst
                   │  (route_after_analyst)
        ┌──────────┴───────────┐
   证据不足且未超轮次          证据充分
        ▼                      ▼
 evidence_gatherer ──回到──▶ risk_reviewer
   (evidence_rounds++)           │ (route_after_risk)
                      ┌──────────┴──────────┐
                  风控驳回且未超轮次       通过 / 轮次用尽
                      ▼                      ▼
                 回到 quant_analyst    data_persistence → auto_execution → END
                 (risk_rounds++,
                  带 risk_feedback)

任意节点抛出异常 → error_handler（标记 run 为 ERROR）→ END
```

### 3.1 三个有界循环

1. **结构化输出自修复（节点内循环）**
   `Quant_Analyst_Node` 调用 `with_structured_output()`；若输出不符合 Pydantic schema（校验失败），带着校验错误反馈让 LLM 重试，最多 `MAX_SCHEMA_RETRIES`（默认 2）次。属节点内部循环，不体现为图的边。

2. **证据补充环（图循环）**
   分析师输出中携带 `needs_more_evidence`（信息不足、需要补充搜索的 ticker 列表）。`route_after_analyst` 检测到该列表非空且 `evidence_rounds < MAX_EVIDENCE_ROUNDS`（默认 2）时，转向 `Evidence_Gatherer_Node` 对这些 ticker 追加搜索，更新 `raw_news_data` 后**回到 `quant_analyst`** 重新分析；否则进入风控。

3. **风控反思环（图循环）**
   `Risk_Reviewer_Node`（独立风控 Agent，独立 prompt + Pydantic schema `RiskReview`）审查分析师的方案：仓位是否过激、是否与新闻矛盾、情绪分与动作是否自洽。`route_after_risk`：
   - 风控**通过**（`approved=true`）→ 进入 `data_persistence`。
   - 风控**驳回**且 `risk_rounds < MAX_RISK_ROUNDS`（默认 3）→ 带 `risk_feedback` **回到 `quant_analyst`** 让其修订，`risk_rounds++`。
   - 风控**驳回但轮次已用尽** → 仍进入 `data_persistence`（见下方「轮次用尽策略」）。

### 3.2 轮次用尽策略（风控未通过仍执行）

当风控反思环达到 `MAX_RISK_ROUNDS` 仍未通过时，**默认策略为「执行 + 标记」**：
- 仍按分析师最终结果继续 `data_persistence` → `auto_execution`，**正常自动执行**交易；
- 在 `analysis_runs` 记录 `risk_verdict=REJECTED_AT_LIMIT`、`risk_rounds`、`review_notes`（风控最后一次的意见）；
- 前端对此类 run 显示「⚠️ 风控未通过仍执行」警示标，人工可当天撤销相关交易。

可选保守策略（通过配置项 `RISK_LIMIT_POLICY` 切换）：
- `EXECUTE_AND_FLAG`（默认）：如上，执行并标记。
- `DOWNGRADE_TO_HOLD`：轮次用尽后，把风控仍反对的 BUY/SELL **降级为 HOLD**（即不执行被否的交易），仅执行未被反对的部分。

风控**通过**的正常 run，`risk_verdict=APPROVED`。

### 3.3 节点定义

*   **节点 1：`News_Scraper_Node`（新闻抓取节点）**
    *   **输入：** 目标股票代码列表（例如 AAPL、MSFT、NVDA、GOOGL、META、TSLA、AMD、TSM、ASML、AVGO）。
    *   **任务：** 为每个股票代码获取最新的前 3 条新闻文章以及当前股价。
    *   **输出：** 聚合后的原始数据字典（含新闻与价格）。
    *   **错误处理：** yfinance / 搜索接口失败时进行重试（带退避），全部失败则将该 run 标记为 `ERROR` 并记录原因。
*   **节点 2：`Quant_Analyst_Node`（量化分析师节点）**
    *   **输入：** 聚合后的原始数据；可选的风控反馈 `risk_feedback`（修订轮）。
    *   **任务：** 让 LLM 扮演资深量化分析师。通过 Pydantic + `with_structured_output()` 输出强类型结构化结果，每个 ticker 含 `Reasoning`、`Sentiment_Score`(1-10)、`Action`(BUY/HOLD/SELL)，并输出 `needs_more_evidence`（需要补充证据的 ticker 列表，可为空）。若收到 `risk_feedback`，需针对性修订上一轮方案。
    *   **结构化输出自修复：** schema 校验失败时带反馈重试，最多 `MAX_SCHEMA_RETRIES` 次（循环 1）。
    *   **输出：** 结构化分析结果 + 格式化报告 + `needs_more_evidence`。
*   **节点 3：`Evidence_Gatherer_Node`（证据补充节点）**
    *   **进入条件：** 分析师标记 `needs_more_evidence` 非空且未超 `MAX_EVIDENCE_ROUNDS`。
    *   **任务：** 仅对 `needs_more_evidence` 中的 ticker 追加搜索（更具体的查询/更多结果），合并进 `raw_news_data`，`evidence_rounds++`，回到分析师。
*   **节点 4：`Risk_Reviewer_Node`（风控审查节点）**
    *   **输入：** 分析师的结构化方案 + 原始数据。
    *   **任务：** 让 LLM 扮演独立风控官，按 `RiskReview`（Pydantic）输出：`approved`(bool)、`issues`（逐条问题，关联 ticker）、`overall_notes`。审查维度：仓位/激进度、与新闻是否矛盾、情绪分与动作是否自洽。
    *   **输出：** `risk_review`、`risk_feedback`（驳回时给分析师的修订意见）。
*   **节点 5：`Data_Persistence_Node`（数据持久化节点）**
    *   **输入：** 最终分析结果、风控结论、原始数据（取价格）。
    *   **任务：** 写入 `analysis_runs`（`status=EXECUTED`，并记录 `risk_verdict`/`risk_rounds`/`evidence_rounds`/`review_notes`），将每个 ticker 的推荐写入 `recommendations`。`run_id` 初始化时生成。
*   **节点 6：`Auto_Execution_Node`（自动执行节点）**
    *   **输入：** 最终分析结果（在 `DOWNGRADE_TO_HOLD` 策略下还需风控否决清单）。
    *   **任务：** 对每个 `action ∈ {BUY, SELL}` 的建议写入一条 `trades` 记录（`status=EXECUTED`，`executed_at=now`，`price` 取分析时价格）。`HOLD` 不产生交易。打印已执行交易列表。
*   **节点 E：`Error_Handler_Node`（错误处理节点）**
    *   **进入条件：** 上游任意节点抛出未捕获异常（含 schema 自修复仍失败）。
    *   **任务：** 将对应 `analysis_runs.status` 置为 `ERROR`（若 run 尚未创建则先创建再标记），记录 `error_message`，安全结束本次 run。

## 4. REST API

通过 FastAPI 暴露 REST API，供前端与外部系统查询推荐/风控/交易数据并执行撤销。

> **CORS：** 服务器模式启用 `CORSMiddleware`，允许前端开发地址（默认 `http://localhost:5173`）跨域访问。允许的来源可通过环境变量 `CORS_ORIGINS` 配置。

### 4.1 接口端点

| 方法 | 路径 | 说明 |
|--------|------|-------------|
| GET | `/api/recommendations/latest` | 获取最近一天所有股票代码的推荐结果 |
| GET | `/api/recommendations/{date}` | 获取指定日期（YYYY-MM-DD）的推荐结果 |
| GET | `/api/recommendations/ticker/{ticker}/latest` | 获取指定股票代码的最新推荐结果 |
| GET | `/api/recommendations/ticker/{ticker}/history` | 获取指定股票代码的历史推荐结果（分页） |
| POST | `/api/run/trigger` | 手动触发一次新的分析运行（异步，返回 `202` + `run_id`） |
| GET | `/api/runs` | 列出所有分析运行及其汇总信息（分页，支持按状态/日期/风控结论筛选） |
| GET | `/api/runs/{run_id}` | 查询指定 run 的状态、风控结论、全部推荐结果及交易 |
| GET | `/api/trades/today` | 获取当天已执行、且**可撤销**的交易列表 |
| GET | `/api/trades` | 列出交易（分页，支持按 run_id/ticker/status/date 筛选） |
| POST | `/api/trades/{trade_id}/cancel` | 撤销单笔交易（仅限当天） |
| POST | `/api/runs/{run_id}/cancel` | 撤销该 run 下所有当天未撤销的交易（便捷批量） |

**`GET /api/runs/{run_id}`** 返回 run 概要（含 `risk_verdict`/`review_notes`）+ 其下全部 `recommendations` 与 `trades`，供前端「详情页」一次性渲染。

撤销端点无请求体；幂等性约定见 4.5。

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
    "code": "TRADE_NOT_CANCELLABLE",
    "message": "该交易非当日交易或已撤销，无法撤销"
  },
  "meta": null
}
```

### 4.3 统一错误码

| HTTP 状态码 | error.code | 说明 |
|--------|------|-------------|
| 400 | `INVALID_PARAMETER` | 请求参数非法（如日期格式错误） |
| 404 | `RESOURCE_NOT_FOUND` | 资源不存在（日期/ticker 无数据） |
| 404 | `RUN_NOT_FOUND` | 指定 run_id 不存在 |
| 404 | `TRADE_NOT_FOUND` | 指定 trade_id 不存在 |
| 409 | `TRADE_NOT_CANCELLABLE` | 交易非当日、或已撤销，不可撤销 |
| 422 | `VALIDATION_ERROR` | 请求参数校验失败 |
| 500 | `INTERNAL_ERROR` | 服务内部错误 |
| 502 | `UPSTREAM_ERROR` | 上游依赖（yfinance/搜索/LLM）失败 |

### 4.4 分页规范

分页类接口（`/recommendations/ticker/{ticker}/history`、`/runs`、`/trades`）统一支持：

| 查询参数 | 类型 | 默认值 | 说明 |
|--------|------|-------------|------|
| `page` | int | 1 | 页码，从 1 开始 |
| `page_size` | int | 20 | 每页条数，最大 100 |

`/runs` 额外支持可选筛选：`status`（EXECUTED/ERROR）、`date`（YYYY-MM-DD）、`risk_verdict`（APPROVED/REJECTED_AT_LIMIT）。`/trades` 额外支持 `run_id`、`ticker`、`status`（EXECUTED/CANCELLED）、`date`。分页结果通过响应 `meta` 中的 `total`、`page`、`page_size`、`total_pages` 返回。

### 4.5 撤销规则（当日限制）

- 一笔交易可被撤销，当且仅当：
  1. 该交易存在（否则 `404 TRADE_NOT_FOUND`）；
  2. 其 `run_date` **等于服务器当天日期**（否则 `409 TRADE_NOT_CANCELLABLE`，「跨天不可撤销」）；
  3. 其当前 `status` 为 `EXECUTED`（已是 `CANCELLED` 则 `409 TRADE_NOT_CANCELLABLE`，幂等地视为不可重复撤销）。
- 撤销动作：将 `trades.status` 置为 `CANCELLED`，写入 `cancelled_at`。原始 `recommendations` 与 `analysis_runs` 记录保留不变（撤销只影响交易，不改写分析/风控历史，保证审计可追溯）。
- `POST /api/runs/{run_id}/cancel` 仅撤销该 run 下满足上述条件的交易；已撤销/跨天的将被跳过，返回实际撤销数量。
- **「当天」的判定**：以服务器本地日期为准；如需固定市场时区，可在实现时通过配置项指定（MVP 默认服务器本地日期）。

### 4.6 服务运行模式

系统支持两种运行模式：
- **CLI 模式**（`python -m src.main`）：运行图一次，自动跑完所有循环（抓取→分析↔证据↔风控→落库→自动执行），控制台打印风控结论与已执行交易，保存到 SQLite，然后退出（无人工交互）。
- **服务器模式**（`python -m src.main --serve`）：启动 FastAPI 服务器，供前端与外部系统使用。
  - 分析运行可通过 `POST /api/run/trigger` 触发或定时调度（cron）。
  - 触发为**异步**操作（抓新闻 + 多轮 LLM 调用耗时较长）：接口立即返回 `202 Accepted` 与 `run_id`，分析在后台任务中**完整跑完**（含三个循环与自动执行），无需人工介入。
  - 前端通过 `/api/runs`、`/api/runs/{run_id}`、`/api/trades/today` 查询结果，并对当天交易执行撤销。

## 5. Web 前端（Vue3 + Ant Design Vue）

前端是一个单页应用（SPA），通过后端 REST API 读写数据。MVP 阶段不含鉴权。

### 5.1 页面与功能

| 页面 | 路由 | 功能 |
|------|------|------|
| **推荐历史** | `/` 或 `/history` | 以表格列出所有分析运行（按日期倒序），展示运行日期、状态、**风控结论**（APPROVED / 风控未通过仍执行）、推荐数量、交易数量、创建时间；支持按状态/日期/风控结论筛选、分页；点击某行进入详情。 |
| **今日交易** | `/today` | 列出当天已执行的交易（来自 `/api/trades/today`），每笔显示 ticker、方向（BUY/SELL）、价格、执行时间；提供「撤销」按钮（仅当天可撤销）。 |
| **运行详情** | `/runs/:runId` | 展示该 run 下每个 ticker 的建议、情绪评分、推理、分析时价格；**AI 风控结论卡片**（通过/未通过、逐条 issues、overall_notes、风控轮次/证据轮次）；以及由 BUY/SELL 生成的交易及其状态。若该 run 为当天，交易行显示「撤销」按钮。 |

顶部布局提供「触发今日分析」按钮（调用 `POST /api/run/trigger`），触发后引导用户到「今日交易」查看自动执行结果。

### 5.2 关键交互流程

**AI 分析 → AI 风控 → 自动执行 → 人工撤销（当日）：**
1. 触发分析（或由定时任务触发）→ 后端跑完证据补充环与风控反思环 → 风控通过（或轮次用尽按策略处理）后自动执行 BUY/SELL。
2. 用户打开「今日交易」，看到当天已自动执行的交易；在「运行详情」可查看 AI 风控为何通过/未通过。
3. 对不认可的交易点击「撤销」→ 前端调用 `POST /api/trades/{trade_id}/cancel`（带 `a-popconfirm` 二次确认）。
4. 后端校验当日限制并将交易置为 `CANCELLED`，前端刷新列表。
5. 跨天后，历史交易的「撤销」按钮禁用/隐藏（后端也会拒绝）。

**查询每日推荐历史：**
1. 用户打开「推荐历史」，按日期/状态/风控结论筛选。
2. 点击任意历史 run 查看详情，了解当日 AI 建议、风控结论、自动执行的交易及其后续是否被撤销。

### 5.3 前后端联调
- 开发期通过 Vite dev server 代理：`/api` → `http://localhost:8000`（避免 CORS 配置）；同时后端开启 `CORSMiddleware` 作为兜底。
- API 基址通过环境变量 `VITE_API_BASE_URL` 配置（`.env.development` / `.env.production`）。
- 前端 TypeScript 类型与后端 Pydantic 响应模型一一对应（`ApiResponse<T>`、`RunOut`、`RecommendationOut`、`TradeOut`、`RiskReviewOut` 等）。

## 6. 数据库设计（SQLite）

> **通用约定：** 连接时开启外键约束 `PRAGMA foreign_keys = ON;`。

### 6.1 数据表

**`analysis_runs`** —— 记录分析流水线的每一次执行（含 AI 风控结论）：

| 列名 | 类型 | 说明 |
|--------|------|-------------|
| id | TEXT（主键） | UUID |
| run_date | TEXT | 运行日期（YYYY-MM-DD） |
| status | TEXT | "EXECUTED"（已自动执行）、"ERROR" |
| risk_verdict | TEXT | "APPROVED"（风控通过）、"REJECTED_AT_LIMIT"（轮次用尽仍执行）、可为空（ERROR 时） |
| risk_rounds | INTEGER | 风控反思环实际轮数 |
| evidence_rounds | INTEGER | 证据补充环实际轮数 |
| review_notes | TEXT | 风控最终意见（overall_notes 摘要），可为空 |
| error_message | TEXT | 错误原因（仅 status=ERROR 时填充，可为空） |
| created_at | TEXT | ISO 8601 时间戳 |

> **状态流转：** run 自动跑完后为 `EXECUTED`（`risk_verdict` 为 APPROVED 或 REJECTED_AT_LIMIT），异常时为 `ERROR`。撤销交易不改变 run 的状态/风控结论（撤销只作用于 `trades`）。

**`recommendations`** —— 存储每个股票代码的分析结果（含 HOLD）：

| 列名 | 类型 | 说明 |
|--------|------|-------------|
| id | INTEGER（主键） | 自增 |
| run_id | TEXT（外键） | 引用 analysis_runs.id，`ON DELETE CASCADE` |
| run_date | TEXT | 冗余的运行日期（YYYY-MM-DD），用于按日期高效查询 |
| ticker | TEXT | 股票代码 |
| reasoning | TEXT | LLM 生成的分析文本（最终修订版） |
| sentiment_score | INTEGER | 1-10 评分 |
| action | TEXT | "BUY"、"HOLD" 或 "SELL" |
| price_at_analysis | REAL | 分析时的股价 |
| created_at | TEXT | ISO 8601 时间戳 |

**`trades`** —— 由 BUY/SELL 建议自动执行产生的模拟交易（可撤销）：

| 列名 | 类型 | 说明 |
|--------|------|-------------|
| id | INTEGER（主键） | 自增 |
| run_id | TEXT（外键） | 引用 analysis_runs.id，`ON DELETE CASCADE` |
| run_date | TEXT | 冗余运行日期，用于「当日撤销」判定与按日期查询 |
| ticker | TEXT | 股票代码 |
| side | TEXT | "BUY" 或 "SELL" |
| price | REAL | 执行价格（取分析时价格 price_at_analysis） |
| status | TEXT | "EXECUTED" 或 "CANCELLED" |
| executed_at | TEXT | ISO 8601 执行时间 |
| cancelled_at | TEXT | ISO 8601 撤销时间（未撤销时为空） |

> **设计说明：** `recommendations` 覆盖全部 ticker（含 HOLD），存最终修订版用于历史分析；`trades` 只记录实际「下单」的 BUY/SELL 操作，是撤销的对象。三表均冗余 `run_date`，皆走单表索引、免 join。AI 风控的逐条 issues 可序列化进 `review_notes`，或在后续版本拆出独立 `risk_issues` 表（MVP 先放 `review_notes`）。

### 6.2 外键定义

```sql
FOREIGN KEY (run_id) REFERENCES analysis_runs(id) ON DELETE CASCADE
```

删除某次 run 时，其下所有 `recommendations` 与 `trades` 行级联删除，避免孤儿数据。

### 6.3 索引

- `idx_recommendations_run_id`：建立在 `recommendations(run_id)` 上
- `idx_recommendations_ticker`：建立在 `recommendations(ticker)` 上
- `idx_recommendations_run_date`：建立在 `recommendations(run_date)` 上（基于冗余列，单表索引）
- `idx_recommendations_ticker_date`：建立在 `recommendations(ticker, run_date)` 上（按 ticker + 日期查询历史）
- `idx_trades_run_id`：建立在 `trades(run_id)` 上
- `idx_trades_run_date`：建立在 `trades(run_date)` 上（当日撤销/按日期查询）
- `idx_trades_ticker`：建立在 `trades(ticker)` 上
- `idx_trades_status`：建立在 `trades(status)` 上
- `idx_analysis_runs_date`：建立在 `analysis_runs(run_date)` 上
- `idx_analysis_runs_status`：建立在 `analysis_runs(status)` 上
- `idx_analysis_runs_risk_verdict`：建立在 `analysis_runs(risk_verdict)` 上（按风控结论筛选）

## 7. 状态定义（TypedDict）
精确定义 `AgentState`。相比 v1.3，新增证据补充环与风控反思环所需字段：

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


class RiskIssue(TypedDict):
    """风控发现的单条问题。"""
    ticker: str
    issue: str               # 问题描述（如「情绪分 8 却给 SELL，自相矛盾」）


class RiskReview(TypedDict):
    """风控 Agent 的审查结论。"""
    approved: bool
    issues: List[RiskIssue]
    overall_notes: str


class TradeExecution(TypedDict):
    """自动执行产生的单笔交易。"""
    ticker: str
    side: str                # "BUY" / "SELL"
    price: float


class AgentState(TypedDict):
    tickers: List[str]
    raw_news_data: Dict[str, TickerNews]      # 含新闻与价格（证据补充环会更新）
    analyses: List[TickerAnalysis]            # 结构化分析结果（最新修订版）
    analysis_report: str                      # 格式化报告（日志/控制台）
    needs_more_evidence: List[str]            # 需要补充证据的 ticker（证据补充环）
    evidence_rounds: int                      # 已执行的证据补充轮数
    risk_review: Optional[RiskReview]         # 最近一次风控结论
    risk_feedback: Optional[str]              # 给分析师的修订意见（驳回时）
    risk_rounds: int                          # 已执行的风控反思轮数
    risk_verdict: Optional[str]               # "APPROVED" / "REJECTED_AT_LIMIT"
    executed_trades: List[TradeExecution]     # 本次自动执行的 BUY/SELL
    run_id: Optional[str]                     # 当前分析运行的 UUID（初始化时生成）
    error_message: Optional[str]              # 出错时的原因
```

> **LLM 结构化输出建议：** 分析师与风控各用一套 Pydantic v2 模型 + `with_structured_output()`，由框架负责解析与校验，避免手工解析 JSON 的格式漂移。

## 8. 健壮性与错误处理

- **统一错误捕获：** 每个节点 try/except，异常写入 `error_message` 并路由到 `Error_Handler_Node`，把 run 标记为 `ERROR`。
- **有界循环防失控：** 三个循环都有硬上限（`MAX_SCHEMA_RETRIES` / `MAX_EVIDENCE_ROUNDS` / `MAX_RISK_ROUNDS`），路由函数基于 `*_rounds` 计数判定，杜绝无限循环。
- **外部依赖重试：** 对 yfinance、新闻搜索、LLM 调用增加重试 + 指数退避；对外部 API 设置速率限制，避免限流/封禁。
- **超时控制：** 为所有网络/LLM 调用设置合理超时，防止单次 run 长时间挂起。
- **部分失败策略：** 个别 ticker 抓取失败时记录状态并继续处理其余 ticker。
- **自动执行的安全性：** 自动执行受 AI 风控前置把关；`Auto_Execution_Node` 与撤销操作均使用事务；撤销严格校验「当日 + EXECUTED」。
- **前端错误展示：** 统一拦截 `ApiResponse.error`，用 Ant Design `message` / `notification` 提示；对 `REJECTED_AT_LIMIT` 的 run 给出醒目警示。

## 9. 配置与依赖

### 9.1 后端环境变量（`backend/.env`）

通过 `.env` 文件（配合 `python-dotenv`）管理密钥与配置，**不得提交到版本库**（加入 `.gitignore`），并提供 `.env.example` 模板：

```ini
# LLM 提供商：glm（默认，智谱 GLM）| anthropic（官方）| openai
LLM_PROVIDER=glm

# —— 智谱 GLM（默认，走 Anthropic 兼容端点）——
GLM_API_KEY=replace-with-your-glm-token             # 形如 id.secret，切勿提交版本库
GLM_BASE_URL=https://open.bigmodel.cn/api/anthropic
GLM_MODEL=glm-5.1
LLM_TIMEOUT_MS=3000000                              # LLM 调用超时（毫秒），GLM 较慢可调大

# —— 官方 Anthropic（LLM_PROVIDER=anthropic 时）——
# ANTHROPIC_API_KEY=sk-ant-xxx
# ANTHROPIC_MODEL=claude-3-5-sonnet-20241022

# —— OpenAI / 或 GLM 的 OpenAI 兼容端点（LLM_PROVIDER=openai 时）——
# OPENAI_API_KEY=sk-xxx
# OPENAI_MODEL=gpt-4o
# OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # 用 GLM 的 OpenAI 兼容端点时填写

# 新闻搜索
TAVILY_API_KEY=tvly-xxx           # 使用 Tavily 时需要

# 数据库 / 服务
DATABASE_PATH=./data/quant.db
API_HOST=0.0.0.0
API_PORT=8000

# 跨域（前端开发地址）
CORS_ORIGINS=http://localhost:5173

# 多 Agent 循环上限
MAX_SCHEMA_RETRIES=2              # 结构化输出自修复次数
MAX_EVIDENCE_ROUNDS=2            # 证据补充环上限
MAX_RISK_ROUNDS=3               # 风控反思环上限
RISK_LIMIT_POLICY=EXECUTE_AND_FLAG   # EXECUTE_AND_FLAG | DOWNGRADE_TO_HOLD

# 目标股票代码（逗号分隔，可覆盖默认 Top 10）
TICKERS=AAPL,MSFT,NVDA,GOOGL,META,TSLA,AMD,TSM,ASML,AVGO
```

> **关于 LLM 提供商：** 默认 `glm` 通过智谱的 **Anthropic 兼容端点**（`/api/anthropic`）复用 `langchain-anthropic` 的 `ChatAnthropic`，仅需 `GLM_API_KEY`/`GLM_BASE_URL`/`GLM_MODEL`。本项目的变量名是自有的，**与 Claude Code CLI 的 `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_DEFAULT_SONNET_MODEL` / `CLAUDE_CODE_*` 不同**——后者只供 Claude Code 命令行使用。由于本项目重度依赖 `with_structured_output()`（tool calling），接入 GLM 后请验证结构化输出稳定性；若不稳，可切换到 GLM 的 OpenAI 兼容端点（见上方注释）。GLM token 等同密码，若曾暴露请到智谱平台重置。

### 9.2 前端环境变量（`frontend/.env.*`）

```ini
# frontend/.env.development
VITE_API_BASE_URL=/api            # 走 Vite 代理

# frontend/.env.production
VITE_API_BASE_URL=https://your-api-host/api
```

### 9.3 依赖清单

- **后端：** 使用 `pyproject.toml` 锁定依赖。核心：`langgraph`、`langchain`、`langchain-anthropic` / `langchain-openai`、`fastapi`、`uvicorn`、`aiosqlite`、`pydantic`、`yfinance`、`tavily-python` / `duckduckgo-search`、`python-dotenv`。（无需 `langgraph-checkpoint-sqlite`：循环在单次 invoke 内完成，无中断恢复需求。）
- **前端：** 使用 `package.json`。核心：`vue`、`ant-design-vue`、`vue-router`、`pinia`、`axios`、`dayjs`；开发依赖：`vite`、`@vitejs/plugin-vue`、`typescript`、`vue-tsc`。

## 10. 测试策略

- **后端单元测试：** 对各节点逻辑、路由函数、数据库读写、API 响应封装进行单元测试；通过 mock 隔离 yfinance、搜索与 LLM。
- **结构化输出 / 自修复测试：** 校验合法输出被正确解析；首次非法 + 重试后合法 → 成功；超过 `MAX_SCHEMA_RETRIES` → 标记 ERROR。
- **证据补充环测试：** 分析师标记 needs_more_evidence → 进入 evidence_gatherer → 回到分析师；达到 `MAX_EVIDENCE_ROUNDS` 后即便仍标记也进入风控（防失控）。
- **风控反思环测试：** 驳回 → 回分析师修订（risk_rounds++）→ 再审；通过 → 进入持久化；达到 `MAX_RISK_ROUNDS` 仍驳回 → 按 `RISK_LIMIT_POLICY` 处理（EXECUTE_AND_FLAG: risk_verdict=REJECTED_AT_LIMIT 且照常执行；DOWNGRADE_TO_HOLD: 被否 BUY/SELL 降级为 HOLD 不下单）。
- **自动执行测试：** BUY/SELL 生成 trades、HOLD 不生成；run 标记为 EXECUTED 且 risk_verdict 正确。
- **撤销测试：** 当日可撤销；跨天 / 重复撤销被拒（409）；run 级批量撤销只作用于满足条件者。
- **API 测试：** `TestClient` 覆盖各端点成功/失败路径、分页（含 risk_verdict 筛选）、撤销规则与错误码。
- **图流程测试：** 用 mock LLM 驱动三个循环的各分支，验证终止条件与最终状态。
- **前端测试：** 组件与 store 单元测试用 `vitest` + `@vue/test-utils`；覆盖风控结论卡片渲染与撤销按钮当日可用性。
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
