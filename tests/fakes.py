"""测试假件(FakeLLM / FakeSearch 等都放这里),严禁联网。

FakeLLM 设计:剧本(script)模式。
- script 元素依次作为每次 complete() 的返回值
- 元素可以是 Exception 实例:直接抛出,模拟网络失败/上游错误
- calls 记录每次调用参数,测试可以断言"prompt 里确实带上了重试信息"

FakeSearch / fake_fetch 同理:记录调用、按查询返回预制结果。
"""
from __future__ import annotations


class FakeLLM:
    def __init__(
        self,
        script: list[str | Exception] | None = None,
        *,
        delay: float = 0.0,
    ) -> None:
        self.script = list(script) if script else []
        self.delay = delay  # 每次调用前 sleep,模拟真实耗时(测时序/SSE)
        self.calls: list[dict] = []

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
        self.calls.append(
            {"prompt": prompt, "system": system, "json_mode": json_mode}
        )
        if not self.script:
            raise AssertionError("FakeLLM 剧本用尽:出现了未预期的调用")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def call_count(self) -> int:
        return len(self.calls)


class FakeSearch:
    """按查询词返回预制结果的假检索服务;未配置的查询返回空(可测证据不足路径)。"""

    def __init__(self, results_by_query: dict[str, list[dict]] | None = None) -> None:
        # 值用 dict 存(轻量),取用时转 SearchSource
        self._map = results_by_query or {}
        self.queries: list[str] = []

    async def search(self, query: str, top_k: int = 5) -> list:
        self.queries.append(query)
        raw = self._map.get(query, [])
        return [_as_source(d) for d in raw[:top_k]]


def _as_source(d: dict):
    from researchpilot.core.models import SearchSource

    return SearchSource(
        url=d["url"], title=d.get("title", ""), snippet=d.get("snippet", "")
    )


def fake_fetch(url_to_content: dict[str, str]):
    """构造一个假 fetch:URL -> 正文。没配的 URL 返回 None(=抓取失败)。"""
    async def _fetch(url: str) -> str | None:
        return url_to_content.get(url)

    return _fetch


# ---------------------------------------------------------------------------
# 全链路剧本:1 plan + 2 notes + 2 reviews + 1 write(顺序固定,并行部分同构无依赖)
# ---------------------------------------------------------------------------

PLAN_JSON = ('{"subquestions": ['
             '{"question": "Q0", "queries": ["q0"]},'
             '{"question": "Q1", "queries": ["q1"]}]}')
NOTE_JSON = '{"claim": "结论", "details": "见 [0]。", "source_indexes": [0]}'
REVIEW_JSON = ('{"reviews": [{"index": 0, "verdict": "supported", "reason": "来源内容支撑主张"}]}')

def write_json_md() -> str:
    """writer 输出。report_md 里有真实换行,必须 json.dumps 生成,不能手拼。"""
    import json

    # 模型只输出正文(规则 5:不写文末引用表,由 render_references 追加)
    md = "# 报告\n\nQ0 结论 [1]。\n\nQ1 结论 [2]。\n"
    return json.dumps({"report_md": md})


FULL_SCRIPT = [PLAN_JSON, NOTE_JSON, NOTE_JSON, REVIEW_JSON, REVIEW_JSON, write_json_md()]


def make_pipeline_runner(db_path: str):
    """一次完整成功研究的 runner:2 子问题 -> 各 1 来源 -> 各 1 条 SUPPORTED。
    返回 (SessionRunner, FakeLLM),调用方负责 create_session 后 asyncio.run(run)。"""
    from researchpilot.app.store import Store
    from researchpilot.app.tasks import SessionRunner

    llm = FakeLLM(script=list(FULL_SCRIPT))
    search = FakeSearch({
        "q0": [{"url": "https://s0.io", "title": "S0"}],
        "q1": [{"url": "https://s1.io", "title": "S1"}],
    })
    store = Store(db_path)
    runner = SessionRunner(
        llm=llm, search=search, store=store,
        fetch=fake_fetch({"https://s0.io": "内容0", "https://s1.io": "内容1"}),
    )
    return runner, llm
