# ResearchPilot 单服务镜像(决策 D8:FastAPI 托管前端构建产物)
#
# 用法:docker build -t researchpilot . && docker run -p 8000:8000 \
#          -e LLM_API_KEY=sk-xxx -e SERPER_API_KEY=xxx researchpilot

# ---- 阶段 1:构建前端 ----
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- 阶段 2:Python 运行环境 ----
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

# src-layout 必须可编辑安装,否则运行时 import 不到 researchpilot
COPY pyproject.toml .
COPY src ./src
RUN pip install -e .

COPY --from=web /web/dist ./web/dist

EXPOSE 8000
CMD ["uvicorn", "researchpilot.app.api:app", "--host", "0.0.0.0", "--port", "8000"]
