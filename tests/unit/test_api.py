"""健康检查冒烟测试(M0)。

教学点:TestClient 来自 fastapi.testclient,它基于 httpx,
**不需要真实启动服务器**就能模拟发请求 —— 它直接调用 FastAPI
的应用对象,速度飞快,单测就该这么写。等 M4 有了业务接口,
每个路由都配一个这样的测试。
"""
from fastapi.testclient import TestClient

from researchpilot.app.api import app

client = TestClient(app)


def test_health():
    # 根路径 / 已被静态托管占用(生产单服务,前端入口),探测接口在 /api/health
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
