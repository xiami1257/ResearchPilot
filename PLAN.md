# ResearchPilot — 多 Agent 研究报告助手 · 整体计划书

> 状态:草稿(待用户审查)| 日期:2026-09-06 | 预估周期:1-2 周
> 目录位置:repo 目录为 `agent01/`(父仓库 `deepseek_project/`),内部 Python 包名为 `researchpilot`

---

## 1. 项目定位与目标

**一句话**:输入一个研究主题,系统自动完成「拆解 → 多路并行检索 → 交叉核验 → 成稿」,输出一篇**带引用来源溯源**的研究报告,全过程在网页上**实时可视化**。

**简历价值定位**(LLM / AI 应用开发岗):

- 与已有经历互补:taobao_100mdate 是"串行阶段管道 + 数据工程",本项目的叙事差异是"**并行多 Agent 协作 + 实时可观测 + 幻觉控制**"
- 面试官可在线直接体验,演示效果强
- 覆盖 LLM 应用岗核心考察点:Agent 编排设计、function calling、并行化、引用溯源/防幻觉、真实模型端到端工程化

**成功标准**(全部满足才算完成):

1. 在线 demo 可访问:输入主题 → 过程实时可视化 → 输出带 [1][2] 脚注引用的报告
2. 3-5 个预置演示主题真实跑通(真实 LLM + 真实网页检索)
3. 测试:核心编排有 pytest 单测 + mock 集成测试 + 真 LLM e2e 冒烟
4. 简历可直接摘用的项目描述 + 面试追问准备清单

---

## 2. 产品行为(用户故事)

- 用户在首页输入主题(可选:提问范围/语言偏好),点「开始研究」
- 页面进入实时看板:顶部阶段进度条(规划 → 并行检索 → 交叉核验 → 撰写),中部各 Agent 的活动状态与日志流,侧栏已采集来源卡片;所有事件由后端 SSE 推送
- 完成后切换到报告视图:Markdown 报告,引用以 [1][2] 上标呈现,文末脚注列出 URL/标题
- 报告自动存入历史,可随时回看
- 失败/证据不足有明确提示,而不是编造内容

---

## 3. 总体架构

```ascii
┌─────────────────────── 浏览器 (React + Vite + TS) ───────────────────────┐
│  首页(输入主题)  │  实时看板(SSE 事件流)  │  报告页(Markdown+脚注)  │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │  REST: POST /api/sessions   SSE: GET /api/sessions/{id}/events
┌───────────────────────────────▼──────────────────────────────────────────┐
│                        FastAPI 应用层 (端口 8001)                          │
│  - API 路由 / 会话 CRUD  - 任务调度(后台 asyncio task)  - SQLite 持久化    │
└───────────────────────────────┬──────────────────────────────────────────┘
┌───────────────────────────────▼──────────────────────────────────────────┐
│              Agent 编排内核 (纯 Python, 不依赖 Web 框架)                    │
│                                                                          │
│   Planner ──拆分研究子问题──► Researcher × N (asyncio 并行)                 │
│                                   │  检索(SearchProvider) + 抓正文          │
│                                   ▼                                        │
│                          结构化笔记(含引用 URL) ◄── 证据不足则显式标注        │
│                                   │                                        │
│              Reviewer ──交叉核验引用/事实──► Writer ──► Markdown 报告        │
│                                                                          │
│  事件总线: 每个 Agent 行为 -> 事件对象 -> SSE 推送 + 落库                   │
└──────────────────────────────────────────────────────────────────────────┘
        ▲                                        ▲
   LLM Client (OpenAI 兼容,        SearchProvider (Serper 默认 +
   默认 DeepSeek,可配 base_url)      DuckDuckGo 无 key 兜底) + 正文提取
```

## 4. 组件职责

| 组件 | 职责 | 依赖 |
|---|---|---|
| `core/events.py` | 事件类型枚举 + Pydantic schema(SSE 协议的唯一事实来源) | pydantic |
| `core/stage_machine.py` | 任务生命周期状态机(start → running → done/failed),阶段推进规则 | — |
| `core/planner.py` | 主题拆解为 2-5 个研究子问题(结构化输出,失败重试 1 次) | LLM Client |
| `core/researcher.py` | 每个子问题一个 Researcher 协程,检索 → 抓正文 → 提炼"带引用笔记" | LLM + Search |
| `core/reviewer.py` | 逐条核验笔记引用:URL 可访问、claim 与来源片段一致、标注置信度 | LLM |
| `core/writer.py` | 汇总笔记 → 按主题结构成稿,引用编号 [n],证据不足小节显式标注 | LLM |
| `llm/client.py` | OpenAI 兼容 chat completions 封装(httpx),超时/重试/JSON schema 解析 | httpx |
| `search/providers.py` | SearchProvider 抽象;Serper 实现 + DuckDuckGo 兜底实现 | httpx |
| `search/extract.py` | 抓取网页正文并截断(trafilatura),失败降级为 snippet | trafilatura |
| `app/api.py` | FastAPI 路由:会话 CRUD、启动任务、SSE 流 | fastapi |
| `app/tasks.py` | 后台任务编排:挂载各 Agent、收集事件、写库、超时熔断 | — |
| `app/store.py` | SQLite 存取(会话 / 事件 / 报告),stdlib sqlite3 | — |
| `web/` | React + TS + Vite 前端(生产由 FastAPI 托管静态构建产物) | react |

## 5. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | Python 3.11+ / FastAPI / uvicorn | 异步编排天然契合;SSE 支持好 |
| 编排 | **自研轻量内核**(不引 langgraph/crewAI) | 简历叙事"手写 Agent 编排",能讲透状态机/事件/失败处理;与 taobao 自研风格一致 |
| LLM | OpenAI 兼容封装(httpx 直连),默认 DeepSeek | 已有 DeepSeek key 经验;配置化可换通义/GLM |
| 检索 | Serper API(免费额度,效果好)+ DuckDuckGo 兜底(无 key 可跑) | demo 需要稳定且真实 |
| 正文提取 | trafilatura | 轻量、鲁棒 |
| 存储 | SQLite(stdlib sqlite3) | 零运维,单文件可移植 |
| 前端 | React 18 + Vite + TypeScript + 自写 CSS | 已有 React/TS 经验(mini_mall);不引重型 UI 库,视觉自定义 |
| 测试 | pytest + mock LLM/检索 + 真 LLM 冒烟 | 分层:快(单测)→ 中(mock 集成)→ 真(e2e) |

## 6. 关键设计决策

> 已按默认值定稿,标注 ⚠️ 的项需要用户确认(见 §12)。其余按此执行,改动需更新本文档。

| # | 决策 | 默认值 | 备选(不推荐) |
|---|---|---|---|
| D1 ⚠️ | 界面语言 | 简体中文 UI;报告语言跟随主题提问语言 | 全英文(不利于国内面试官体验) |
| D2 ⚠️ | LLM 供应商 | DeepSeek `deepseek-chat`(环境变量可覆盖 base_url/model/key) | 通义 qwen-plus 仅需换配置 |
| D3 ⚠️ | 检索供应商 | Serper(需注册免费 key);无 key 自动降级 DDG | 仅 DDG(检索质量差,demo 效果打折) |
| D4 | 编排 | 自研:事件总线 + 阶段状态机,单进程 asyncio | langgraph(黑盒感强,难讲实现) |
| D5 | 并行度 | Researcher 数量 = 子问题数(上限 5),asyncio.gather + 信号量 | 串行(慢,展示差) |
| D6 | 防幻觉 | 引用必带 URL;Reviewer 核验;证据不足显式标注;单任务总超时 5 min | 无核验(面试被追问就露怯) |
| D7 | 会话/历史 | SQLite 存全部事件与报告,首页可回看;重启后运行中任务标记 failed | 不持久化(功能单薄) |
| D8 | 部署形态 | 单服务:FastAPI 托管前端构建产物 → 部署简单(一个进程) | 前后端分离双服务(部署成本高) |
| D9 | 依赖管理 | `requirements.txt` + venv(与 taobao 一致) | uv(可以但引入新工具) |
| D10 | 日志 | 事件落库 + stdout 结构化日志;无外部可观测系统 | 引 Sentry 等(超范围) |

## 7. 范围控制

**V1 做**:主题输入(带 1-2 个可选参数:检索条数、语言);四阶段流程;实时看板;报告+引用;历史列表(含删除);错误提示与证据不足标注;预置演示主题按钮。

**V1 明确不做**(YAGNI):登录/多用户;任务编排手动编辑;PDF/Word 导出;会话续跑/中断恢复;用户自定义 Agent 数;缓存层;Agent 工具自定义。报告下载仅复制 Markdown。

## 8. 目录结构(目标)

```
agent01/
├── README.md / CLAUDE.md / PLAN.md(本文档)
├── requirements.txt
├── pytest.ini / conftest.py
├── src/researchpilot/
│   ├── __init__.py / __main__.py
│   ├── core/          # 纯编排内核(无 Web 依赖): events, stage_machine, planner, researcher, reviewer, writer
│   ├── llm/           # client.py(OpenAI 兼容封装)
│   ├── search/        # providers.py, extract.py
│   └── app/           # api.py, tasks.py, store.py, settings.py
├── tests/
│   ├── unit/          # 状态机/引用编号/note 结构校验等(快)
│   ├── integration/   # mock LLM + mock 检索 跑全流程
│   └── e2e/           # 真 LLM 冒烟(标 @slow,手动触发)
├── scripts/
│   ├── run_demo_topics.py   # 预置演示主题批量跑 + 输出质量摘要
│   └── serve.py             # uvicorn 启动入口
└── web/               # React+Vite 前端(client 构建产物由后端托管)
```

## 9. 里程碑(M0-M6,共 14 天,含 2 天缓冲)

| 里程碑 | 时间 | 交付物 | 退出标准 | 状态 |
|---|---|---|---|---|
| **M0 脚手架** | Day 1 | 三份文档(本文档/README/CLAUDE)、目录树、requirements、pytest 骨架 | `pytest` 通过;`uvicorn` 起服务返回 hello | ✅ |
| **M1 编排内核** | Day 2-3 | events.py / stage_machine.py / planner.py + mock LLM | 状态机全路径单测通过;Planner 结构化输出单测通过 | ✅ |
| **M2 检索与并行研究** | Day 4-6 | SearchProvider(Serper+DDG)、正文提取、researcher.py | mock 检索集成测试:5 个子问题并行出 5 份带 URL 笔记 | ✅ |
| **M3 核验与写作** | Day 7-8 | reviewer.py / writer.py / 报告组装与 [n] 编号 | 引用编号幂等;证据不足路径有测试覆盖 | ✅ |
| **M4 API 与持久化** | Day 9-10 | FastAPI 路由 + 任务调度 + SQLite + SSE + **确定性引用脚注**(render_references) | curl 冒烟:POST → 事件/报告落库可查;pytest 79 passed | ✅ |
| **M5 前端与真机打磨** | Day 11-13 | React 三视图(输入/看板/报告+历史);SSE 实时渲染;静态托管;Dockerfile | tsc+vite 构建通过;真实 HTTP 冒烟通过。**剩余**:配 key 后真机跑主题 + 质量迭代 | 🟡(代码完成,待 key 真机) |
| **M6 上线与收尾** | Day 14 | 部署上线、README 完善(截图/链接)、简历素材、演示走查 | 在线链接可用;演示脚本 10 分钟能走完 | ⏳(待部署平台) |

**弹性预案**:若 M2/M3 滑期 → 砍 M5 打磨深度(UI 保底可用即可),**不砍** M4 的 SSE 与 D6 防幻觉。

## 10. 测试策略

- **单元(快)**:状态机转移、事件 schema、引用编号、笔记结构校验、JSON 输出解析(坏 JSON/缺字段)
- **集成(mock)**:`FakeLLM`(可编程返回剧本)+ `FakeSearch`(本地 fixture 页面)→ 全流程无网络跑通
- **e2e(真)**:标 `@slow`,默认跳过,手动跑:1 个真实主题全流程 + 断言报告含 ≥3 个引用 URL、无空节
- **前端**:不做组件级重测试(V1);关键为 SSE 渲染冒烟(手动走查清单)

## 11. 部署与在线访问

- 形态:D8 单服务 —— FastAPI 托管 `web/dist`,一个进程
- 首选:**Render Free**(web service,免费额度,demo 够用);备选:Hugging Face Spaces(Docker);最后手段:仅本地 + 录屏(不满足"在线可访问",尽量避免)
- 需要:DeepSeek API key、Serper key、部署平台账号 → 均通过环境变量注入,不进代码库(见 §12 准备清单)
- 演示话题池放入页面预设按钮,保证面试官 1 次点击即看到效果,不暴露耗时过长的话题

## 12. 开放问题与准备清单(需要用户确认/准备)

| 项 | 说明 |
|---|---|
| ~~D1 界面中文~~ | 已实施:全站中文 UI |
| ⚠️ D2 LLM key | 真机打磨/上线的唯一阻塞项:配 `LLM_API_KEY` 后跑 `python -m pytest -m e2e` 与 `scripts/run_demo_topics.py` |
| ⚠️ D3 Serper key | 可选但推荐:无 key 降级 DuckDuckGo,国内网络下命中率差,演示效果打折 |
| 项目名 | 已定 ResearchPilot,repo 目录沿用 agent01 |
| ⚠️ 部署平台 | Dockerfile 已就绪;选 Render Free / HF Spaces / Zeabur 任一生效即可部署 |
| 架构图/截图 | 上线后补进 README(演示区占位已留) |

## 13. 简历素材草稿

> 上线后结合实测数据(报告数量、典型耗时)再润色。

- 独立开发 **ResearchPilot**(2 周):输入主题即可产出带引用溯源研究报告的多 Agent 系统,在线可体验
- 自研轻量 Agent 编排内核(阶段状态机 + 事件总线 + 失败重试),Planner → 多 Researcher 并行 → Reviewer → Writer 四角色协作,Researcher 可横向扩展
- 设计证据链防幻觉机制:引用强制携带 URL、Reviewer 交叉核验、证据不足显式标注而非编造,缓解 LLM 幻觉
- 基于 Server-Sent Events 的 Agent 过程实时可视化,检索/推理/核验全链路可观测
- 工程化:真实 LLM(DeepSeek)+ 真实检索端到端;pytest 单测/集成(可编程 mock LLM)/真机冒烟分层测试;SQLite 会话持久化

**面试追问点(提前准备)**:为什么不用 langgraph?如何保证引用不伪造?并行线程多了怎么控成本/限流?任务失败如何恢复?Reviewer 判据是什么、如何验证其有效性?

## 14. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-06 | 初稿:方向 A「多 Agent 研究助手」定稿,决策固化 |
| 2026-09-06 | M1-M4 落地(79 passed);M5 前端三视图+静态托管+Dockerfile;新增引用脚注确定性生成(render_references)与 e2e 冒烟/演示脚本;M6 仅剩部署与真机打磨 |
| 2026-09-07 | 检索新增 Tavily provider(配 TAVILY_API_KEY 自动优先于 Serper),含单测;D3 保持「Serper 默认、key 路由、DDG 兜底」语义不变 |
