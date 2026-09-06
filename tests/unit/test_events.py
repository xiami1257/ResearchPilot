"""事件层测试:构造/校验/Union 分流/类型配套。"""
import pytest
from pydantic import ValidationError

from researchpilot.core.events import (
    AgentMessagePayload,
    Event,
    EventType,
    NoteReadyPayload,
    ReviewVerdictPayload,
    SourceFoundPayload,
    Stage,
    StageChangedPayload,
    TaskFailedPayload,
    TaskSucceededPayload,
    Verdict,
)

RUN = "run-test-1"


def _make(type_: EventType, payload):
    return Event.make(type_, payload, run_id=RUN)


# -- 每类事件的构造 + JSON 往返 -----------------------------------------

@pytest.mark.parametrize(
    "event",
    [
        _make(EventType.STAGE_CHANGED, StageChangedPayload(stage=Stage.RESEARCH)),
        _make(EventType.AGENT_MESSAGE, AgentMessagePayload(role="researcher", agent_id=1, message="开始检索")),
        _make(EventType.SOURCE_FOUND, SourceFoundPayload(agent_id=1, sub_index=0, query="a b", url="https://a.com", title="A")),
        _make(EventType.NOTE_READY, NoteReadyPayload(agent_id=1, sub_index=0)),
        _make(EventType.REVIEW_VERDICT, ReviewVerdictPayload(agent_id=1, sub_index=0, verdict=Verdict.SUPPORTED, reason="ok")),
        _make(EventType.TASK_SUCCEEDED, TaskSucceededPayload(summary="done")),
        _make(EventType.TASK_FAILED, TaskFailedPayload(error="boom")),
    ],
    ids=lambda e: e.type.value,
)
def test_event_roundtrip_to_dict(event: Event):
    """每种事件都能 to_dict 出合法结构,关键载荷字段保留。"""
    d = event.to_dict()
    assert d["type"] == event.type.value
    assert d["run_id"] == RUN
    assert "at" in d
    payload = d["payload"]
    assert isinstance(payload, dict)
    # 每种事件的载荷里必须出现它自己的标识性字段
    expected_key = {
        EventType.STAGE_CHANGED: "stage",
        EventType.AGENT_MESSAGE: "message",
        EventType.SOURCE_FOUND: "url",
        EventType.NOTE_READY: "sub_index",
        EventType.REVIEW_VERDICT: "verdict",
        EventType.TASK_SUCCEEDED: "summary",
        EventType.TASK_FAILED: "error",
    }[event.type]
    assert expected_key in payload


def test_payload_discrimination_source_not_note():
    """Union 分流:带 url 的 dict 必须判成 SourceFound,而不是被 NoteReady 吞掉。"""
    ev = Event.model_validate({
        "run_id": RUN,
        "type": EventType.SOURCE_FOUND.value,
        "payload": {"agent_id": 1, "sub_index": 0, "query": "q", "url": "https://x.io", "title": "X"},
    })
    assert isinstance(ev.payload, SourceFoundPayload)
    assert not isinstance(ev.payload, NoteReadyPayload)


def test_extra_fields_rejected():
    """extra='forbid':多一个字段必须报错(保证 schema 漂移能早期暴露)。"""
    with pytest.raises(ValidationError):
        StageChangedPayload(stage=Stage.PLAN, surprise="?")


def test_make_rejects_type_payload_mismatch():
    """make() 必须拒绝 type 与载荷不配套的组合。"""
    with pytest.raises(TypeError):
        _make(EventType.STAGE_CHANGED, TaskSucceededPayload(summary="oops"))
