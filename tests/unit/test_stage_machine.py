"""状态机测试:合法全路径 / 非法迁移 / 终态封锁。"""
import pytest

from researchpilot.core.events import Stage
from researchpilot.core.stage_machine import RunStateMachine, RunStatus
from researchpilot.errors import StageMachineError


def test_initial_state():
    m = RunStateMachine()
    assert m.status == RunStatus.RUNNING
    assert m.stage == Stage.PLAN
    assert not m.is_finished


def test_advance_full_path():
    """合法路径:PLAN -> RESEARCH -> REVIEW -> WRITE,逐个推进。"""
    m = RunStateMachine()
    assert m.advance() == Stage.RESEARCH
    assert m.advance() == Stage.REVIEW
    assert m.advance() == Stage.WRITE
    assert m.stage == Stage.WRITE
    assert not m.is_finished


def test_advance_beyond_write_is_illegal():
    m = RunStateMachine()
    for _ in range(3):
        m.advance()
    with pytest.raises(StageMachineError):
        m.advance()


def test_succeed_then_any_migration_is_illegal():
    m = RunStateMachine()
    m.succeed()
    assert m.status == RunStatus.SUCCEEDED
    assert m.is_finished
    with pytest.raises(StageMachineError):
        m.advance()
    with pytest.raises(StageMachineError):
        m.fail("late error")


def test_fail_from_mid_stage_records_error():
    m = RunStateMachine()
    m.advance()  # -> research
    m.fail("LLM 挂了")
    assert m.status == RunStatus.FAILED
    assert m.error == "LLM 挂了"
    with pytest.raises(StageMachineError):
        m.advance()  # 终态后不再允许任何迁移
