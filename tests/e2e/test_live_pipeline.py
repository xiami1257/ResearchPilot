"""真实 LLM + 真实检索的端到端冒烟(M5 真机打磨的自动验收入口)。

跑法(工作目录 = agent01):
    LLM_API_KEY=sk-xxx python -m pytest -m e2e -q

- 无 LLM_API_KEY 时自动跳过 —— 日常全量/CI 不会被它拖慢或打断
- 检索无 Serper key 时自动降级 DuckDuckGo(见 build_default_runner)
- 验证的是"整条真机链路 + 防幻觉闸门",不是内容质量(质量迭代
  用 scripts/run_demo_topics.py 看摘要)
"""
import asyncio
from dataclasses import replace

import pytest

from researchpilot.app.settings import load_settings
from researchpilot.app.store import Store
from researchpilot.app.tasks import SessionRunner, build_default_runner

pytestmark = pytest.mark.e2e

# 冒烟主题:选 MCP 而非泛主题 —— DDG 兜底下英文资料命中率高,
# 保证"检索 -> 抓取 -> 提炼 -> 核验"全程有真实素材可走
TOPIC = "什么是 MCP 协议,为什么它对 AI Agent 生态重要"


def test_live_pipeline_produces_report(tmp_path):
    settings = load_settings()
    if not settings.llm_ready:
        pytest.skip("需要 LLM_API_KEY 才能跑真机 e2e")

    runner = build_default_runner(
        replace(settings, db_path=str(tmp_path / "e2e.db"))
    )
    run_id = "e2e-live"
    runner.store.create_session(run_id, TOPIC, status="running", stage="plan")

    asyncio.run(runner.run(run_id, TOPIC, n_sub=3))

    s = runner.store.get_session(run_id)
    assert s["status"] == "succeeded", f"真实链路失败: {s['error']}"
    assert s["report_md"] and len(s["report_md"]) > 200
    # 引用脚注必须由系统拼上(URL 可溯源 —— 产品核心卖点)
    assert "## 引用来源" in s["report_md"]

    # 防幻觉闸门回执:报告里不能出现消毒标记 [?](模型引用编号外的内容)
    assert "[?]" not in s["report_md"]
