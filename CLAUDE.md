# CLAUDE.md — agent01 / ResearchPilot

## 协作模式(最高优先级)

本项目以**用户学习**为主:代码(含测试)全部由用户亲手编写。Claude Code 只做两件事:

1. 提示下一步做什么(按里程碑拆任务卡,含验收标准)
2. 审阅用户的代码(指出问题、解释原理、给修改建议,不直接代改)

例外:项目文档(README/PLAN 等)可由 Claude 起草。任何需要"替用户写/改代码"的冲动先克制——给诊断和示例,让用户动手。

## 项目一句话

输入研究主题 → Planner 拆解 → 多个 Researcher 并行检索网页 → Reviewer 交叉核验 → Writer 成稿的多 Agent 研究报告助手,过程经 SSE 实时可视化,报告带 [n] 脚注引用溯源。面向简历展示,1-2 周交付,在线可体验。

## 必读

- [PLAN.md](PLAN.md) — 整体计划书:架构、决策(D1-D10)、里程碑 M0-M6、范围控制。**改设计先改这里**
- [README.md](README.md) — 对外介绍(面试官入口)

## 常用命令(工作目录 = agent01)

```bash
pip install -r requirements.txt    # 安装依赖
pip install -e .                   # editable 安装本包(src-layout 必需,否则入口脚本 import 不到 researchpilot)
python scripts/serve.py            # 启动后端(dev: uvicorn --reload)
python -m pytest -q                      # 单元+集成测试(mock LLM/检索,无网络)
python -m pytest -m e2e -q               # 真 LLM 冒烟(需配 LLM key,慢)
python scripts/run_demo_topics.py        # 批量跑演示主题并输出质量摘要
cd web && npm install && npm run dev     # 前端 dev(代理 /api → 127.0.0.1:8001)
cd web && npm run build                  # 构建产物 web/dist 由 FastAPI 托管(生产单服务)
```

## 环境变量(均在 `src/researchpilot/app/settings.py` 单点读取)

| 变量 | 含义 | 默认 |
|---|---|---|
| `LLM_BASE_URL` | OpenAI 兼容 API base | `https://api.deepseek.com` |
| `LLM_API_KEY` | API key(**测试 e2e/真机必配**) | 空 |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `SEARCH_PROVIDER` | 预留(实际按 key 自动路由:Tavily > Serper > DDG) | `serper` |
| `SERPER_API_KEY` | serper.dev 免费 key | 空 |
| `TAVILY_API_KEY` | Tavily 免费 key(有值则自动优先于 Serper) | 空 |

## 架构速览(改代码前先看对应文件)

- [src/researchpilot/core/events.py](src/researchpilot/core/events.py) — 事件类型枚举 + Pydantic schema,**SSE 协议唯一事实来源**,前后端与落库都依赖它
- [src/researchpilot/core/stage_machine.py](src/researchpilot/core/stage_machine.py) — 任务阶段状态机(纯逻辑,无 I/O)
- [src/researchpilot/core/](src/researchpilot/core/) 下 planner/researcher/reviewer/writer 四角色,**不 import Web 框架**
- [src/researchpilot/llm/client.py](src/researchpilot/llm/client.py) — OpenAI 兼容封装(httpx),含超时/重试/JSON schema 解析
- [src/researchpilot/search/](src/researchpilot/search/) — SearchProvider 抽象 + 实现
- [src/researchpilot/app/tasks.py](src/researchpilot/app/tasks.py) — 后台任务调度入口(编排挂载点)
- [web/](web/) — React + Vite + TS 前端;生产构建产物 `web/dist/` 由 FastAPI 托管

## 测试约定

- 分层:unit(快,无网络)→ integration(可编程 mock)→ e2e(`@slow` + `-m e2e`,真 LLM)
- mock 固定件在 [tests/fakes.py](tests/fakes.py):`FakeLLM`(按剧本返回)、`FakeSearch`(本地 fixture 页),**不得联网**
- 改动 `core/` 后必须保证 `pytest -q` 全绿再声称完成
- 改动真机链路(LLM/search 调用、事件 schema)后必须跑一次 `-m e2e` 或真实演示主题

## 铁律

- 引用溯源是产品核心卖点:任何"研究报告输出"路径都必须带真实 URL 引用;证据不足显式标注,禁止让模型编造来源
- 不要新增与 [PLAN.md](PLAN.md) §6 决策冲突的实现;要改先更新 PLAN.md
- 红线与沟通规则继承父目录 [CLAUDE.md](../CLAUDE.md)(中文回复、不自动 commit 等)
- V1 范围以 PLAN.md §7 为准,超范围功能先讨论
