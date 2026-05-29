# AI Quant Agent 后端镜像
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制依赖声明，利用构建缓存
COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip && pip install .

# 数据目录（compose 会挂载卷持久化）
RUN mkdir -p /app/data

EXPOSE 8000

# 通过 --serve 启动 FastAPI；监听 0.0.0.0:8000
CMD ["python", "-m", "src.main", "--serve", "--port", "8000"]
