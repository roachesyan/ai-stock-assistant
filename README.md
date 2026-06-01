# AI Quant Agent (v1.4 MVP)

一个基于 **LangGraph + LangChain** 的多 Agent 量化助手 monorepo：分析师 Agent 生成交易建议，风控 Agent 做 AI 审查（带证据补充环、风控反思环、结构化输出自修复三个有界循环），通过后**自动模拟执行** BUY/SELL；人工只能**事后撤销当天的交易**。后端 FastAPI + SQLite，前端 Vue3 + Ant Design Vue。

> ⚠️ 仅供技术研究与学习，所有交易均为**模拟**且**自动执行**，不构成投资建议。

## 结构

```
ai-stock-assistant/
├── backend/            # Python / FastAPI / LangGraph
├── frontend/           # Vue3 + Ant Design Vue + Vite + TS
├── docker-compose.yml  # 一键启动后端 + 前端
├── spec.md             # 产品需求与系统规格
└── doc/                # 架构设计 / 详细设计
```

详见 `spec.md`、`doc/architecture-design.md`、`doc/detailed-design.md`。

---

## 一、本地运行（原生，开发推荐）

需要：**Python 3.10+**、**Node.js 18+**、一个 **GLM API Key**（或 Anthropic / OpenAI）。

### 1. 配置环境变量

```bash
cd backend
cp .env.example .env
```

编辑 `backend/.env`，至少填好 LLM：

```ini
LLM_PROVIDER=glm
GLM_API_KEY=你的GLM-token            # 形如 id.secret，到智谱开放平台获取
GLM_BASE_URL=https://open.bigmodel.cn/api/anthropic
GLM_MODEL=glm-5.1
```

> 新闻搜索：`TAVILY_API_KEY` 留空会自动回退到免费的 DuckDuckGo，无需配置也能跑。

### 2. 启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 方式 A：CLI 模式 —— 跑一次完整流程（抓取→分析→风控→自动执行），打印结果后退出
python -m src.main

# 方式 B：Server 模式 —— 启动 REST API（默认 http://localhost:8000）
python -m src.main --serve
```

API 文档（Server 模式）：http://localhost:8000/docs

### 3. 启动前端

另开一个终端：

```bash
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

前端开发服务器会把 `/api` 自动代理到 `http://localhost:8000`，因此**需先启动后端 Server 模式**。打开 http://localhost:5173 即可使用。

### 4. 跑测试

```bash
# 后端
cd backend && source .venv/bin/activate && pytest

# 前端
cd frontend && npm run test
```

---

## 二、Docker Compose 运行（一键启动）

需要：**Docker** 与 **Docker Compose**。

### 1. 准备环境变量

确保 `backend/.env` 已存在并填好 `GLM_API_KEY`（compose 通过 `env_file` 读取它）：

```bash
cd backend && cp .env.example .env   # 然后编辑填入 GLM_API_KEY
cd ..
```

### 2. 构建并启动

```bash
docker-compose up -d --build
```

- 前端（nginx）：http://localhost:8080
- 后端（FastAPI）：http://localhost:8000 （API 文档 /docs）

前端容器内的 nginx 会把 `/api` 反向代理到后端容器，因此浏览器只需访问 **http://localhost:8080**。SQLite 数据持久化在名为 `backend-data` 的 Docker 卷中。

### 3. 常用命令

```bash
docker-compose logs -f            # 查看日志
docker-compose ps                 # 查看状态
docker-compose down               # 停止并移除容器（保留数据卷）
docker-compose down -v            # 停止并移除容器 + 数据卷（清空数据）
```

---

## 四、定时调度（每日自动分析）

后端**常驻进程内置了 APScheduler 调度器**，无需外部 cron——开启后服务自己会在每个**交易日**定时跑一次完整分析并自动执行交易。仅在 **Server 模式**生效。

在 `backend/.env` 中开启：

```ini
SCHEDULE_ENABLED=true                 # 开启
SCHEDULE_CRON=30 9 * * 1-5            # 每周一到周五 09:30 触发
SCHEDULE_TIMEZONE=America/New_York    # 按美东时间解释 cron（美股时区）
MARKET_CALENDAR=XNYS                  # 交易日历（XNYS=纽交所）
SKIP_NON_TRADING_DAYS=true            # 节假日/周末自动跳过
```

要点：
- 触发逻辑与 `POST /api/run/trigger` 完全一致（同一条 `run_pipeline` 路径），结果照常落库、可在前端查看与撤销。
- 用 **pandas-market-calendars** 判断交易日：不仅跳过周末，还会跳过**美股节假日**（如元旦、感恩节等）。
- `SCHEDULE_TIMEZONE` 很关键：cron 时间按它解释。美股是美东时间，和本地（北京时间）不同，请按市场设置。
- 有防重入保护：上一次还没跑完不会重复触发。
- **单实例限制**：调度在后端进程内运行，若将来横向扩成多副本会重复触发，届时需加分布式锁或独立调度服务。
- Docker 部署同理：在 `backend/.env` 设好后 `docker-compose up -d` 即可，无需额外容器。

---

## 五、使用流程

1. 打开前端，点右上角「触发今日分析」（或后端 `POST /api/run/trigger`）。
2. 后台跑完多 Agent 流程（抓新闻 + 多轮 LLM），将通过风控的 BUY/SELL 自动模拟执行。
3. 到「今日交易」查看已执行交易，对不认可的点「撤销」（**仅当天可撤销**）。
4. 「推荐历史」可按日期/状态/风控结论筛选；点进详情可看 AI 风控的逐条意见。

---

## 六、LLM 提供商

默认使用智谱 **GLM（glm-5.1）** 的 Anthropic 兼容端点（`LLM_PROVIDER=glm`）。也支持官方 Anthropic（`anthropic`）或 OpenAI / GLM 的 OpenAI 兼容端点（`openai`）。完整变量见 `backend/.env.example` 与 `doc/detailed-design.md` §7。
