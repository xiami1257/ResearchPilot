"""SessionRunner 编排测试: Fake 全链路 + 事件流 hub 行为。

覆盖:
- 完整研究成功:状态落库 succeeded、事件序列正确(阶段推进顺序、终态收尾)
- planner 连续失败:状态 failed、错误落库、TASK_FAILED 收尾
- 事件 hub:订阅者收到广播;任务结束后流以 None 关闭
"""
import asyncio

from researchpilot.app.store import Store
from researchpilot.app.tasks import SessionRunner
from researchpilot.core.events import EventType
from tests.fakes import FULL_SCRIPT, FakeLLM, FakeSearch, fake_fetch, make_pipeline_runner

DB = "test.db"


def _run(runner, run_id="r1", topic="测试主题"):
    asyncio.run(runner.run(run_id, topic))


def _prepare(db_path):
    """共享准备:造 runner + 建会话。"""
    runner, llm = make_pipeline_runner(db_path)
    runner.store.create_session("r1", "测试主题", status="running", stage="plan")
    return runner, llm


def test_full_pipeline_succeeds_and_persists(tmp_path):
    runner, llm = _prepare(str(tmp_path / DB))
    _run(runner)

    s = runner.store.get_session("r1")
    assert s["status"] == "succeeded"
    assert s["error"] is None
    assert s["report_md"].startswith("# 报告")
    # 引用脚注由系统确定性追加(带真实 URL,不靠模型)
    assert "## 引用来源" in s["report_md"]
    assert "https://s0.io" in s["report_md"]
    assert llm.call_count == len(FULL_SCRIPT)  # plan+2笔记+2核验+1写作

    events = runner.store.list_events("r1")
    types = [e["type"] for e in events]
    # 阶段推进顺序:research -> review -> write(plan 阶段是建会话时预置的)
    stages = [
        e["payload"]["stage"]
        for e in events if e["type"] == EventType.STAGE_CHANGED.value
    ]
    assert stages == ["research", "review", "write"]
    # 两个子问题各广播一次笔记就绪
    assert types.count(EventType.NOTE_READY.value) == 2
    # 第一条是 planner 开场白(看板以此提示"规划中")
    assert events[0]["type"] == EventType.AGENT_MESSAGE.value
    # 终态事件最后一条,带一句话摘要
    assert events[-1]["type"] == EventType.TASK_SUCCEEDED.value
    assert events[-1]["payload"]["summary"]


def test_planner_failure_persists_error_and_emits_failed(tmp_path):
    """planner 两次自纠都失败 -> PlanningError -> 状态 failed + TASK_FAILED 收尾。"""
    llm = FakeLLM(script=["not json", "still not json"])
    store = Store(str(tmp_path / DB))
    runner = SessionRunner(llm=llm, search=FakeSearch({}), store=store, fetch=fake_fetch({}))
    store.create_session("r1", "主题", status="running", stage="plan")
    _run(runner)

    s = store.get_session("r1")
    assert s["status"] == "failed"
    assert "PlanningError" in s["error"]
    events = store.list_events("r1")
    assert events[-1]["type"] == EventType.TASK_FAILED.value
    assert events[-1]["payload"]["error"]


def test_subscriber_receives_events_until_stream_close(tmp_path):
    """订阅者拿到全部广播;成功路径跑完,流以 None 关闭(SSE 断开的依据)。"""

    async def scenario():
        runner, _ = make_pipeline_runner(str(tmp_path / DB))
        runner.store.create_session("r1", "测试主题", status="running", stage="plan")
        q = runner.hub.subscribe("r1")
        task = asyncio.create_task(runner.run("r1", "测试主题"))

        types: list[str] = []
        while True:
            item = await asyncio.wait_for(q.get(), timeout=5)  # 防死锁
            if item is None:
                break
            types.append(item.type.value)
        await task
        assert types[-1] == EventType.TASK_SUCCEEDED.value
        assert EventType.NOTE_READY.value in types

    asyncio.run(scenario())
