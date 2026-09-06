"""FastAPI 应用层:HTTP 路由 + SSE 实时事件流。

接口一览:
  POST   /api/sessions              创建研究任务 -> 202 + run_id(立即返回,后台跑)
  GET    /api/sessions              会话列表(历史)
  GET    /api/sessions/{run_id}     会话详情(状态 + 全部事件 + 报告) -> 快照
  GET    /api/sessions/{run_id}/events  SSE 实时流(增量事件)

前后端时序约定(重要):
  页面打开 -> 先 GET 详情拿快照(含已发生全部事件)
            -> 再开 SSE 等增量
  这样:刷新/断线重连 = 快照 + 新事件,不会丢进度。
  任务已结束时订阅 SSE 会立即关闭 —— 增量模式,不补发。

create_app 工厂:store / runner 可注入(测试传 Fake 或临时 DB);
模块级 `app = create_app()` 供 serve.py / uvicorn 直接使用。
"""
import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..core.events import Stage
from .settings import Settings, load_settings
from .store import Store
from .tasks import SessionRunner, build_default_runner

logger = logging.getLogger(__name__)


class CreateSessionRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=300, description="研究主题")
    n_sub: int = Field(default=4, ge=3, le=5, description="拆解子问题数量")


def create_app(
    *,
    settings: Settings | None = None,
    runner: SessionRunner | None = None,
    store: Store | None = None,
) -> FastAPI:
    """组装应用。不传则走生产默认(读环境变量,真 LLM + 真检索)。"""
    settings = settings or load_settings()
    runner = runner or build_default_runner(settings)
    store = store or runner.store

    app = FastAPI(title="ResearchPilot", version="0.1.0")
    app.state.settings = settings
    app.state.runner = runner

    # ------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/sessions", status_code=202)
    def create_session(
        req: CreateSessionRequest, background: BackgroundTasks
    ) -> dict:
        """建会话 + 后台执行。先落库(快照可查),再挂后台任务。"""
        run_id = uuid.uuid4().hex[:12]
        store.create_session(
            run_id, req.topic, status="running", stage=Stage.PLAN.value
        )
        background.add_task(runner.run, run_id, req.topic, req.n_sub)
        logger.info("session %s started: %s", run_id, req.topic)
        return {"run_id": run_id}

    @app.get("/api/sessions")
    def list_sessions() -> dict:
        return {"sessions": store.list_sessions()}

    @app.get("/api/sessions/{run_id}")
    def get_session(run_id: str) -> dict:
        session = store.get_session(run_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return {"session": session, "events": store.list_events(run_id)}

    @app.get("/api/sessions/{run_id}/events")
    async def session_events(run_id: str) -> StreamingResponse:
        """SSE:任务运行中返回增量事件;终态订阅立即结束。"""
        session = store.get_session(run_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        return StreamingResponse(
            _event_stream(runner, run_id, session["status"]),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # -- 生产单服务(决策 D8):FastAPI 托管前端构建产物 ----------------
    # 注意:mount("/") 必须最后注册 —— Starlette 按注册顺序匹配,
    # 先注册的 /api 路由会优先命中,其余请求才落到静态文件。
    dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if dist.is_dir():  # 未构建前端时(dev 走 vite 代理/纯测试)跳过,不影响 API
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")

    return app


async def _event_stream(
    runner: SessionRunner, run_id: str, status: str
) -> AsyncIterator[str]:
    """单订阅者的 SSE 生成器。退出(客户端断开/流结束)必退订。"""
    queue = runner.hub.subscribe(run_id)
    if status != "running":  # 已终态:无增量可发,立即结束
        queue.put_nowait(None)
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item.to_dict(), ensure_ascii=False)}\n\n"
    finally:
        runner.hub.unsubscribe(run_id, queue)


# 模块级默认实例:serve.py 以 "researchpilot.app.api:app" 导入
app = create_app()
