"""任务生命周期状态机(纯逻辑,无 I/O —— 不纯就没法全量单测)。

设计说明:

1. **只管"能不能这样走",不执行任何业务。** 阶段推进时"该启动哪些
   Researcher"是任务调度层(M4 的 tasks.py)的职责,状态机只回答:
   当前在哪、下一步允许去哪、这步合不合法。

2. **两层状态合并在一个类里:**
   - `status`: 整体生命周期 RUNNING -> SUCCEEDED / FAILED(终态)
   - `stage`:  流程内阶段,按 PLAN -> RESEARCH -> REVIEW -> WRITE
     单向推进(不允许跳步、不允许回退)
   研究任务的流程是严格线性的(至少 V1 如此),所以单向顺序推进的
   API 比通用的"任意迁移表"更安全 —— 把不可能的状态直接变成写不出来。

3. 注意类不 import 事件/错误以外的任何东西,也没有 asyncio ——
   这保证它可以被毫秒级单测,也能被任意并发调度器调用。
"""
from .events import Stage
from ..errors import StageMachineError

STAGE_ORDER: tuple[Stage, ...] = (
    Stage.PLAN,
    Stage.RESEARCH,
    Stage.REVIEW,
    Stage.WRITE,
)


class RunStatus(str):
    """任务生命周期状态(用 str 子类而非 Enum:与事件/存储互转最省事)。"""
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunStateMachine:
    """一次研究任务的状态机。创建即处于 RUNNING + PLAN。"""

    def __init__(self) -> None:
        self._status: str = RunStatus.RUNNING
        self._stage: Stage = STAGE_ORDER[0]
        self._error: str | None = None

    # -- 只读属性 ------------------------------------------------------
    @property
    def status(self) -> str:
        return self._status

    @property
    def stage(self) -> Stage:
        return self._stage

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def is_finished(self) -> bool:
        return self._status != RunStatus.RUNNING

    # -- 迁移方法(非法迁移一律抛 StageMachineError) --------------------
    def advance(self) -> Stage:
        """推进到下一个阶段,返回新阶段。

        处于 WRITE 时不能 advance —— 流程写完必须显式 succeed()/fail()。
        """
        self._ensure_running()
        if self._stage is STAGE_ORDER[-1]:
            raise StageMachineError(
                f"已在最后阶段 {self._stage.value},流程结束:请调用 succeed()/fail()"
            )
        self._stage = STAGE_ORDER[STAGE_ORDER.index(self._stage) + 1]
        return self._stage

    def succeed(self) -> None:
        self._ensure_running()
        self._status = RunStatus.SUCCEEDED

    def fail(self, reason: str) -> None:
        """失败可发生在任意阶段;一旦失败即终态,error 记录原因供展示。"""
        self._ensure_running()
        self._status = RunStatus.FAILED
        self._error = reason

    # -- 内部 -----------------------------------------------------------
    def _ensure_running(self) -> None:
        if self.is_finished:
            raise StageMachineError(
                f"任务已处于终态({self._status}),不允许再迁移"
            )
