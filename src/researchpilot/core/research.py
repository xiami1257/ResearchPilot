"""研究阶段并行 runner:把多个子问题分给多个 Researcher 并发执行。

设计说明:
- Researcher(单子问题)与并行编排(多子问题)分成两个模块,
  各自可独立测试:单测测 Researcher,集成测这里
- asyncio.Semaphore 限制并发上限:多个子问题各自还要并行抓网页,
  没有上限会瞬间打爆 LLM/检索/目标网站 —— 限流是 Agent 系统
  必须自己负责的事,别指望上游帮你挡
- 任何一个子问题失败 → 整体失败(异常冒泡)。
  V1 的取舍:宁可整个任务失败明示,也不要交付缺胳膊少腿的报告;
  Reviewer 阶段(弱证据标注)负责"内容不全"的优雅处理
"""
import asyncio
from collections.abc import Callable

from .models import Note, SubQuestion
from .researcher import Researcher, FetchFn


async def run_research_phase(
    subquestions: list[SubQuestion],
    *,
    llm,
    search,
    fetch: FetchFn,
    max_concurrent: int = 5,
    on_note: Callable[[Note], None] | None = None,
) -> list[Note]:
    """并行研究全部子问题,返回与 subquestions 顺序一致的笔记列表。

    on_note: 可选回调,每完成一个子问题笔记就立即触发(而不是全部
    完成才一次性触发)。这是"实时看板"的关键 —— 调度层用它广播
    NOTE_READY 事件;完成顺序不确定,但返回列表仍按 sub_index 排序。
    """
    # 并发数不必超过子问题数(用不着建没活干的 worker)
    cap = min(max_concurrent, len(subquestions)) or 1
    semaphore = asyncio.Semaphore(cap)

    async def worker(sub: SubQuestion) -> Note:
        async with semaphore:
            researcher = Researcher(llm=llm, search=search, fetch=fetch)
            return await researcher.research_one(sub)

    pending = {asyncio.create_task(worker(s)): s for s in subquestions}
    notes_by_sub: dict[int, Note] = {}
    try:
        for done in asyncio.as_completed(pending):
            note = await done
            notes_by_sub[note.sub_index] = note
            if on_note is not None:
                on_note(note)  # 逐笔记广播;回调同步轻量,不做 I/O
    except BaseException:
        for t in pending:  # 某个子问题炸了:取消还没跑完的,避免孤儿任务
            t.cancel()
        raise
    return [notes_by_sub[s.index] for s in subquestions]
