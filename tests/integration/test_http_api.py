"""HTTP/SSE 层测试: TestClient + Fake 组件 + 临时 SQLite。

覆盖:
- POST 建任务:202 + run_id;后台任务在 TestClient 生命周期内跑完 -> 详情 succeeded
- GET 列表 / 详情快照(会话 + 全量事件)/ 404
- 参数校验 422
- SSE:终态任务订阅立即结束(增量模式不补发历史)

已知缺口(记录在案,不伪装覆盖):
- 运行中任务的 SSE 增量推送。TestClient 的请求是串行阻塞的,
  无法同时"开着流"又"发起新任务";事件总线的扇出已由
  test_tasks.py 的订阅者测试覆盖,前端将在此基础上做真实浏览器联调。
"""
import pytest
from fastapi.testclient import TestClient

from researchpilot.app.api import create_app
from researchpilot.core.events import EventType
from tests.fakes import make_pipeline_runner


@pytest.fixture()
def api(tmp_path):
    """Fake 全链路 runner + 临时库组装的应用。"""
    db = str(tmp_path / "api.db")
    runner, _ = make_pipeline_runner(db)
    return create_app(settings=None, runner=runner, store=runner.store)


def _create(client, topic="深度学习综述", n_sub=3):
    return client.post("/api/sessions", json={"topic": topic, "n_sub": n_sub})


def test_create_then_background_completes(api):
    """POST 后后台任务跑完:详情为 succeeded + 报告落库 + 事件落库。"""
    app = api
    with TestClient(app) as client:
        r = _create(client)
        assert r.status_code == 202
        run_id = r.json()["run_id"]
        assert len(run_id) == 12

        detail = client.get(f"/api/sessions/{run_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["session"]["status"] == "succeeded"
        assert body["session"]["report_md"].startswith("# 报告")

        types = [e["type"] for e in body["events"]]
        assert types[-1] == EventType.TASK_SUCCEEDED.value


def test_list_sessions_and_404(api):
    app = api
    with TestClient(app) as client:
        _create(client)
        listed = client.get("/api/sessions").json()["sessions"]
        assert any(s["status"] == "succeeded" for s in listed)

        assert client.get("/api/sessions/nope").status_code == 404
        assert client.get("/api/sessions/nope/events").status_code == 404


def test_request_validation(api):
    app = api
    with TestClient(app) as client:
        assert client.post("/api/sessions", json={"topic": "x"}).status_code == 422
        assert client.post("/api/sessions", json={"topic": "ok", "n_sub": 9}).status_code == 422


def test_sse_on_finished_session_closes_immediately(api):
    """终态订阅:无增量可发,SSE 立即结束(增量模式,不补发历史)。"""
    app = api
    with TestClient(app) as client:
        run_id = _create(client).json()["run_id"]
        # 后台任务已跑完 -> GET events 应立刻返回空体(仅 HTTP 200 + event-stream 头)
        r = client.get(f"/api/sessions/{run_id}/events")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.text == ""


def test_failure_path_reports_failed_status(api, monkeypatch):
    """planner 崩溃的任务:状态 failed + 错误可读(前端据此展示失败态)。"""
    app = api

    class Boom:
        async def complete(self, prompt, *, system=None, json_mode=False):
            raise RuntimeError("上游断了")

    with TestClient(app) as client:
        monkeypatch.setattr(app.state.runner, "_llm", Boom())
        run_id = _create(client).json()["run_id"]
        detail = client.get(f"/api/sessions/{run_id}").json()
        assert detail["session"]["status"] == "failed"
        assert "RuntimeError" in detail["session"]["error"]
        types = [e["type"] for e in detail["events"]]
        assert types[-1] == EventType.TASK_FAILED.value
