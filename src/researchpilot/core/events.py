"""事件类型与载荷 schema —— 整个系统内外传输的"唯一事实来源"。

阅读前请先理解三条设计原则(面试也会被问):

1. **事件是"已发生的客观事实",不是"当前状态"。**
   看板/前端拿到一串事件后自行推算状态,而不是依赖某个"状态快照"。
   好处:回放事件就能重建任意时刻的画面,天然支持历史与调试。

2. **为什么所有载荷模型都 extra="forbid"(禁止多余字段)?**
   Event.payload 是一个 Union(多种载荷任选其一),Pydantic 需要从
   dict 判别它属于哪种。若允许"多余字段被静默忽略",一个带 url 的
   dict 可能被字段较少的模型误吞(比如 NoteReady 吞掉 SourceFound),
   Union 分流就不可靠。禁止多余字段后,每个 dict 恰好只匹配一种载荷。

3. **事件是强类型、可校验的**,不是自由 dict。缺字段/多字段/错类型
   在构造时立即报错,而不是在几百行之外的神秘崩溃。

新增一种事件 = 三处修改:EventType 枚举 + 对应载荷模型 + 加入 EventPayload 联合。
"""
from datetime import datetime, timezone
from enum import Enum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


def _now() -> datetime:
    """统一取 UTC 当前时间(事件带时区,落库/展示再转本地)。"""
    return datetime.now(timezone.utc)


class _Strict(BaseModel):
    """所有事件载荷的基类:禁止多余字段(见文件头原则 2)。"""
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 基础枚举
# ---------------------------------------------------------------------------

class Stage(str, Enum):
    """研究流程的四个阶段(顺序即执行顺序)。"""
    PLAN = "plan"
    RESEARCH = "research"
    REVIEW = "review"
    WRITE = "write"


class AgentRole(str, Enum):
    """参与任务的 Agent 角色。"""
    PLANNER = "planner"
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"
    WRITER = "writer"


class Verdict(str, Enum):
    """Reviewer 对一条引用的核验结论。

    - SUPPORTED   来源内容确实支撑笔记中的主张
    - UNSUPPORTED 来源与主张不符(该引用应被剔除)
    - UNVERIFIABLE 来源不可访问/内容不足,无法核验(报告应显式标注)
    """
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE = "unverifiable"


class EventType(str, Enum):
    """全部事件类型。命名:点分语义,如 stage.changed。"""
    STAGE_CHANGED = "stage.changed"
    AGENT_MESSAGE = "agent.message"
    SOURCE_FOUND = "source.found"
    NOTE_READY = "note.ready"
    REVIEW_VERDICT = "review.verdict"
    TASK_SUCCEEDED = "task.succeeded"
    TASK_FAILED = "task.failed"


# ---------------------------------------------------------------------------
# 各事件类型的载荷
# ---------------------------------------------------------------------------

class StageChangedPayload(_Strict):
    """进入(或离开)某个研究阶段。"""
    stage: Stage


class AgentMessagePayload(_Strict):
    """某个 Agent 的一句活动说明/日志(看板逐条展示,制造"实时感")。

    agent_id: 并行 Researcher 的编号;非并行角色统一为 0。
    """
    role: AgentRole
    agent_id: int = 0
    message: str


class SourceFoundPayload(_Strict):
    """某 Researcher 检索命中并决定收录一个来源。

    payload 只带元信息(轻量);网页全文/提炼笔记属于重数据,
    留在任务上下文里,不进事件流 —— 否则每个事件体积爆炸。
    """
    agent_id: int
    sub_index: int
    query: str
    url: str
    title: str
    snippet: str = ""


class NoteReadyPayload(_Strict):
    """某 Researcher 完成一个子问题的笔记提炼。

    笔记全文同样不进事件,只广播"第 sub_index 个子问题笔记就绪",
    看板据此把该 Researcher 标为完成;collected 是收录来源数(展示用)。
    """
    agent_id: int
    sub_index: int
    collected: int = 0


class ReviewVerdictPayload(_Strict):
    """Reviewer 对某个子问题给出核验结论。"""
    agent_id: int
    sub_index: int
    verdict: Verdict
    reason: str


class TaskSucceededPayload(_Strict):
    """任务整体成功。summary 用于列表页一句话概览。"""
    summary: str = ""


class TaskFailedPayload(_Strict):
    """任务整体失败(携带可展示的错误信息)。"""
    error: str


# Union 顺序无要求:extra="forbid" 保证任意顺序判别都正确(见文件头原则 2)
EventPayload = (
    StageChangedPayload
    | AgentMessagePayload
    | SourceFoundPayload
    | NoteReadyPayload
    | ReviewVerdictPayload
    | TaskSucceededPayload
    | TaskFailedPayload
)


class Event(_Strict):
    """事件信封:一次事件 = run_id + 类型 + 时间 + 载荷。

    不提供构造函数,统一用 make() 保证 type 与 payload 永远配套:
    make(EventType.SOURCE_FOUND, payload=SourceFoundPayload(...)) 由
    _PAYLOAD_TYPE 表校验配套关系,type 配错立刻报错。
    """
    run_id: str
    type: EventType
    at: datetime = Field(default_factory=_now)
    payload: EventPayload

    # type -> 载荷类型 对照表(新增事件类型时必须同步加一行)
    # ClassVar: 告知 Pydantic 这是类级常量,不要当作模型字段处理
    _PAYLOAD_TYPE: ClassVar[dict[EventType, type[BaseModel]]] = {
        EventType.STAGE_CHANGED: StageChangedPayload,
        EventType.AGENT_MESSAGE: AgentMessagePayload,
        EventType.SOURCE_FOUND: SourceFoundPayload,
        EventType.NOTE_READY: NoteReadyPayload,
        EventType.REVIEW_VERDICT: ReviewVerdictPayload,
        EventType.TASK_SUCCEEDED: TaskSucceededPayload,
        EventType.TASK_FAILED: TaskFailedPayload,
    }

    @classmethod
    def make(cls, type_: EventType, payload: BaseModel, *, run_id: str) -> "Event":
        expected = cls._PAYLOAD_TYPE[type_]
        if not isinstance(payload, expected):
            raise TypeError(
                f"event {type_.value!r} 要求 {expected.__name__} 载荷,"
                f"实际收到 {type(payload).__name__}"
            )
        return cls(run_id=run_id, type=type_, payload=payload)

    def to_dict(self) -> dict:
        """转可 JSON 序列化的 dict(SSE 推送、SQLite 落库共用这一个出口)。"""
        return self.model_dump(mode="json")
