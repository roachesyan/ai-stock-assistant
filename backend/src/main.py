"""入口：CLI 模式（跑一次完整流程）与 Server 模式（FastAPI）。"""
from __future__ import annotations

import argparse
import asyncio
import logging

from src.config import settings


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def _run_cli() -> None:
    from src.db.init_db import init_db
    from src.graph.builder import run_pipeline

    await init_db()
    print(f"▶ 触发分析，目标股票: {', '.join(settings.TICKERS)}")
    result = await run_pipeline(settings.TICKERS)

    run_id = result.get("run_id")
    verdict = result.get("risk_verdict")
    err = result.get("error_message")
    if err:
        print(f"❌ run {run_id} 失败: {err}")
        return

    print(f"\n📊 run {run_id} 完成 | 风控结论: {verdict} | "
          f"风控轮次: {result.get('risk_rounds', 0)} | 证据轮次: {result.get('evidence_rounds', 0)}")
    trades = result.get("executed_trades", [])
    if trades:
        for t in trades:
            print(f"   • {t['ticker']}: {t['side']} @ {t['price']}")
    else:
        print("   • 无可执行交易（全部 HOLD）")


def _run_server(port: int) -> None:
    import uvicorn

    from src.api.app import create_app

    app = create_app()
    uvicorn.run(app, host=settings.API_HOST, port=port)


def main() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description="AI Quant Agent")
    parser.add_argument("--serve", action="store_true", help="启动 FastAPI 服务器")
    parser.add_argument("--port", type=int, default=settings.API_PORT, help="服务端口")
    args = parser.parse_args()

    if args.serve:
        _run_server(args.port)
    else:
        asyncio.run(_run_cli())


if __name__ == "__main__":
    main()
