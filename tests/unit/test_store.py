"""Store 测试:临时 SQLite 文件上的 CRUD 往返。"""
import pytest

from researchpilot.app.store import Store

RUN = "run-1"


@pytest.fixture()
def store(tmp_path):
    return Store(str(tmp_path / "test.db"))


def test_create_and_get_session(store):
    store.create_session(RUN, "主题", "running", "plan")
    s = store.get_session(RUN)
    assert s["topic"] == "主题"
    assert s["status"] == "running"
    assert s["created_at"]


def test_update_session_partial(store):
    store.create_session(RUN, "主题", "running", "plan")
    store.update_session(RUN, status="succeeded", stage="write", report_md="# 报告")
    s = store.get_session(RUN)
    assert s["status"] == "succeeded"
    assert s["stage"] == "write"
    assert s["report_md"] == "# 报告"
    # 只传一个字段:其它列保持不变
    store.update_session(RUN, error="boom")
    s = store.get_session(RUN)
    assert s["error"] == "boom"
    assert s["status"] == "succeeded"


def test_get_missing_returns_none(store):
    assert store.get_session("nope") is None


def test_events_roundtrip_in_order(store):
    store.create_session(RUN, "t", "running", "plan")
    store.save_event(RUN, {"type": "a", "run_id": RUN})
    store.save_event(RUN, {"type": "b", "run_id": RUN})
    events = store.list_events(RUN)
    assert [e["type"] for e in events] == ["a", "b"]


def test_list_sessions_newest_first(store, tmp_path):
    store.create_session("r1", "a", "succeeded", "write")
    store.create_session("r2", "b", "running", "plan")
    rows = store.list_sessions()
    assert [r["run_id"] for r in rows] == ["r2", "r1"]
