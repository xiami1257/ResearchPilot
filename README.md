# ResearchPilot · 多 Agent 研究报告助手

输入一个研究主题,自动完成**拆解 → 多路并行检索 → 交叉核验 → 成稿**,输出带引用溯源的研究报告;Agent 每一步的思考与检索过程在网页上**实时可视化**。

> 面向 LLM 应用开发的练习项目:自研轻量 Agent 编排内核(未使用 langgraph/crewAI),真实 LLM + 真实网页检索端到端运行。2 周完成。

## 它能做什么

- **一次点击研究**:输入主题(如"2026 年大模型推理优化的主要技术路线"),系统自动规划研究子问题
- **并行 Agent 协作**:多个 Researcher 同时检索网页、阅读并提炼"带引用笔记"
- **交叉核验防幻觉**:Reviewer 逐条核验引用与事实,证据不足处**显式标注**而非编造
- **过程可观测**:SSE 实时推送每个 Agent 的行为——检索了什么、看到了什么、如何判断
- **带脚注的报告**:正文引用以 [1][2] 标注,文末列出来源 URL
- **历史回看与删除**:报告与会话事件持久化(SQLite),随时可查;可删除不需要的历史(运行中的任务受保护)

## 架构

```
Planner ──拆解子问题──► Researcher × N(并行检索+抓正文+笔记)
                              │
Reviewer ──交叉核验──► Writer ──► Markdown 报告(带 [n] 引用)
                              │
              事件总线 → SSE → 网页实时看板
```

后端:FastAPI + 自研编排内核 + SQLite | 前端:React + TypeScript + Vite | LLM:OpenAI 兼容(默认 DeepSeek) | 检索:Tavily / Serper / DuckDuckGo(按 key 自动路由)

详细设计见 [PLAN.md](PLAN.md)。

## 快速开始

```bash
# 1. 后端(需 Python 3.11+)
pip install -r requirements.txt
pip install -e .                  # 以 editable 模式安装本包,入口脚本才能 import researchpilot

# 2. 配置环境变量(项目不引 dotenv,直接 export;Windows PowerShell 用 $env:LLM_API_KEY="…")
export LLM_API_KEY=sk-...         # 必填:OpenAI 兼容 API key(默认走 DeepSeek,可用 LLM_BASE_URL/LLM_MODEL 覆盖)
export SERPER_API_KEY=...         # 可选:serper.dev 搜索 key;也可用 export TAVILY_API_KEY=...(有 Tavily key 时自动优先)
                                  # 都不配则自动降级 DuckDuckGo(国内网络下检索效果差)

# 3. 启动(单服务:FastAPI 同时托管前端与 API)
cd web && npm install && npm run build     # 先构建前端(仅首次/改前端后需要)
cd .. && python scripts/serve.py           # http://127.0.0.1:8001(默认端口,与花生壳内网穿透映射一致)

# 前端 dev 模式(改 UI 热更新,可选):cd web && npm run dev → 5173 端口,代理 /api 到 8001
```

配置项全表见 [CLAUDE.md](CLAUDE.md)「环境变量」;DB 默认落在当前目录 researchpilot.db(可用 `DB_PATH` 改)。

## 测试

```bash
python -m pytest -q          # 单元 + 集成测试(mock LLM/检索,无网络,无需 key)
python -m pytest -m e2e      # 真 LLM 冒烟(需 LLM_API_KEY)
python scripts/run_demo_topics.py   # 批量跑演示主题并输出质量摘要
```

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | 自研:事件总线 + 阶段状态机(Planner / Researcher × N / Reviewer / Writer) |
| LLM 接入 | httpx 直连 OpenAI 兼容 API(默认 DeepSeek,可换任意兼容服务) |
| 网页检索 | Tavily / Serper(配 key 自动启用)+ DuckDuckGo 零 key 兜底;trafilatura 正文提取 |
| 后端 | Python 3.11 · FastAPI · SSE · SQLite |
| 前端 | React 18 · TypeScript · Vite(自写 CSS) |
| 测试 | pytest:单元 / 集成(mock)/ 真机 e2e 三层 |

## 项目结构

```
agent01/
├── PLAN.md                  # 整体计划书(架构/决策/里程碑)
├── src/researchpilot/
│   ├── core/                # 纯编排内核:events/状态机/四角色 agent
│   ├── llm/                 # OpenAI 兼容客户端封装
│   ├── search/              # 检索 provider + 网页正文提取
│   └── app/                 # FastAPI 路由/任务调度/存储/配置
├── tests/                   # unit / integration(mock)/ e2e(真机)
├── scripts/                 # 启动、演示主题批跑
└── web/                     # React + TS 前端
```

## 演示

- 在线地址:_(上线后填写)_
- 预置演示主题:_(上线后填写)_

## License

MIT(待定)
