"""后台任务编排:把 Planner / Research / Review / Report / Writer
串成一次完整研究任务,并负责两件横切事:
- 广播事件(内存 hub,推给 SSE 订阅者)
- 落库(全部事件 + 会话状态 + 最终报告)

设计取舍(面试可讲):
1. **core 层保持"不知道事件总线存在"**:内核只是逐阶段返回结果,
   编排层在阶段边界把进展包装成事件广播 —— 内核可测性不被总线污染。
   例外是研究阶段的逐笔记回调(research.py 的 on_note):阶段内部
   的完成时机内核不关心,但"实时性"又必须有,所以用回调暴露时机,
   事件内容仍由本层决定。
2. **任务随进程内存存续**:重启后运行中任务丢失(置为 failed)。
   V1 不追求断点续跑 —— 快照/回放能力已由事件落库提供。
3. **任何异常都收敛为事件 + 状态,不冒泡**:后台任务不该无声消失,
   也不该让请求线程崩溃。失败详情进 TASK_FAILED 与 sessions.error。
"""
import asyncio
import logging
from typing import Callable

from ..core.events import (
    AgentMessagePayload, AgentRole, Event, EventType, NoteReadyPayload,
    Stage, StageChangedPayload, TaskFailedPayload, TaskSucceededPayload,
    Verdict,
)
from ..core.planner import Planner
from ..core.report import build_report_sources, render_references
from ..core.research import run_research_phase
from ..core.reviewer import run_review_phase
from ..core.writer import Writer
from ..llm.client import LLMClient
from ..search.extract import fetch_and_extract
from ..search.providers import DuckDuckGoSearch, SearchProvider, SerperSearch
from .settings import Settings
from .store import Store

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 事件广播 Hub:一个 session 多个 SSE 订阅者,全部能收到
# ---------------------------------------------------------------------------

class EventHub:
    """run_id -> 订阅者队列集合;push(None) 表示流结束。"""

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.setdefault(run_id, set()).add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(run_id)
        if subs is not None:
            subs.discard(q)
            if not subs:
                self._subs.pop(run_id, None)

    def push(self, run_id: str, item) -> None:
        """同步调用(编排协程内轻量入队,不 await,避免事件丢失)。"""
        for q in list(self._subs.get(run_id, ())):
            q.put_nowait(item)

    def close_stream(self, run_id: str) -> None:
        for q in list(self._subs.get(run_id, ())):
            q.put_nowait(None)


# ---------------------------------------------------------------------------
# SessionRunner
# ---------------------------------------------------------------------------

class SessionRunner:
    def __init__(
        self,
        *,
        llm: LLMClient,
        search: SearchProvider,
        store: Store,
        fetch: Callable | None = None,
    ) -> None:
        self._llm = llm
        self._search = search
        self.store = store
        self._fetch = fetch or fetch_and_extract
        self.hub = EventHub()

    async def run(self, run_id: str, topic: str, n_sub: int = 4) -> None:
        """完整执行一次研究。任何异常都收敛,不冒泡。"""
        try:
            await self._execute(run_id, topic, n_sub)
        except asyncio.CancelledError:
            raise  # 服务关闭等:原样上抛,不伪装成业务失败
        except Exception as e:
            logger.exception("session %s 失败", run_id)
            self._finish_failed(run_id, f"{type(e).__name__}: {e}")

    # -- 主流程 -----------------------------------------------------------

    async def _execute(self, run_id: str, topic: str, n_sub: int) -> None:
        def emit(type_: EventType, payload) -> None:
            event = Event.make(type_, payload, run_id=run_id)
            self.hub.push(run_id, event)
            self.store.save_event(run_id, event.to_dict())

        def msg(role: AgentRole, message: str, agent_id: int = 0) -> None:
            """同步发送一条 Agent 动态(内部无 I/O,只是入队+落库)。

            刻意保持同步:on_note 等回调解约就是"轻量、无 I/O"(见
            research.py),编排层若在这里引入异步会让契约错配。真异步点
            只有四个阶段的 LLM/网络调用,事件广播永远只是"顺手记一笔"。
            """
            emit(EventType.AGENT_MESSAGE,
                 AgentMessagePayload(role=role, agent_id=agent_id, message=message))

        # -- 规划
        msg(AgentRole.PLANNER, "正在拆解研究问题…")
        planner = Planner(self._llm)
        subquestions = await planner.plan(topic, n_sub=n_sub)
        msg(AgentRole.PLANNER, f"已拆解为 {len(subquestions)} 个子问题")
        emit(EventType.STAGE_CHANGED, StageChangedPayload(stage=Stage.RESEARCH))

        # -- 并行研究(逐笔记完成即广播,前端看板实时滚动)
        def note_done_cb(note) -> None:
            emit(EventType.NOTE_READY, NoteReadyPayload(
                agent_id=note.sub_index, sub_index=note.sub_index,
                collected=len(note.sources),
            ))
            label = _label_for(subquestions, note.sub_index)
            msg(AgentRole.RESEARCHER,
                      f"子问题「{label}」完成笔记,收录 {len(note.sources)} 个来源",
                      agent_id=note.sub_index)

        notes = await run_research_phase(
            subquestions, llm=self._llm, search=self._search,
            fetch=self._fetch, on_note=note_done_cb,
        )
        msg(AgentRole.RESEARCHER, "全部子问题研究完毕,进入交叉核验")

        # -- 核验
        emit(EventType.STAGE_CHANGED, StageChangedPayload(stage=Stage.REVIEW))
        reviews = await run_review_phase(notes, llm=self._llm)
        n_supported = sum(
            1 for r in reviews for e in r.evidence
            if e.verdict is Verdict.SUPPORTED
        )
        msg(AgentRole.REVIEWER,
                  f"核验完成:{n_supported} 条引用通过,其余剔除或标记未核验")

        # -- 组装 + 写作
        emit(EventType.STAGE_CHANGED, StageChangedPayload(stage=Stage.WRITE))
        sections, pool = build_report_sources(subquestions, notes, reviews)
        msg(AgentRole.WRITER,
                  f"开始撰写:{len(sections)} 个小节,引用池 {len(pool)} 条")
        report_md = await Writer(self._llm).write(topic, sections, pool)
        # 引用脚注表(带 URL)由代码确定性生成,不依赖模型 —— 见 report.py
        report_md = render_references(report_md, pool)

        self.store.update_session(run_id, status="succeeded", report_md=report_md)
        emit(EventType.TASK_SUCCEEDED,
             TaskSucceededPayload(summary=f"《{topic}》完成,{len(pool)} 条引用"))
        self.hub.close_stream(run_id)

    # -- 失败收尾 ----------------------------------------------------------

    def _finish_failed(self, run_id: str, error: str) -> None:
        self.store.update_session(run_id, status="failed", error=error)
        event = Event.make(EventType.TASK_FAILED, TaskFailedPayload(error=error), run_id=run_id)
        self.hub.push(run_id, event)
        self.store.save_event(run_id, event.to_dict())
        self.hub.close_stream(run_id)


def _short(text: str, n: int = 24) -> str:
    return text if len(text) <= n else text[:n] + "…"


def _label_for(subquestions, sub_index: int) -> str:
    if 0 <= sub_index < len(subquestions):
        return _short(subquestions[sub_index].question)
    return f"#{sub_index}"


# ---------------------------------------------------------------------------
# 默认管线工厂(生产组装点;测试直接手工注入 Fake)
# ---------------------------------------------------------------------------

def build_default_runner(settings: Settings) -> SessionRunner:
    from ..llm.client import OpenAICompatibleClient

    llm = OpenAICompatibleClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
    )
    if settings.serper_api_key:
        search: SearchProvider = SerperSearch(api_key=settings.serper_api_key)
    else:  # 无 Serper key 兜底 DDG(效果弱但任何环境可跑)
        search = DuckDuckGoSearch()
    store = Store(settings.db_path)
    return SessionRunner(llm=llm, search=search, store=store)
