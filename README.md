# AI Quant Agent (v1.4 MVP)

一个基于 **LangGraph + LangChain** 的多 Agent 量化助手 monorepo：分析师 Agent 生成交易建议，风控 Agent 做 AI 审查，通过后**自动模拟执行** BUY/SELL；人工只能**事后撤销当天的交易**。后端 FastAPI + SQLite，前端 Vue3 + Ant Design Vue。

> ⚠️ 仅供技术研究与学习，所有交易均为**模拟**且**自动执行**，不构成投资建议。

## 结构

```
ai-stock-assistant/
├── backend/    # Python / FastAPI / LangGraph
└── frontend/   # Vue3 + Ant Design Vue + Vite + TS
```

详见 `spec.md`、`doc/architecture-design.md`、`doc/detailed-design.md`。

## 快速开始

### 后端

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # 填入 GLM_API_KEY 等
python -m src.main            # CLI：跑一次完整流程
python -m src.main --serve    # 启动 API 服务（:8000）
```

### 前端

```bash
cd frontend
npm install
npm run dev                   # http://localhost:5173，代理 /api → :8000
```

## LLM 提供商

默认使用智谱 **GLM（glm-5.1）** 的 Anthropic 兼容端点，配置见 `backend/.env`（`LLM_PROVIDER=glm`）。
