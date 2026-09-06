"""Planner:把研究主题拆成一组可独立检索的子问题。

职责边界:
- 只负责"规划"这一步,返回 [SubQuestion] 就结束
- 不构造/不广播任何事件 —— 事件由调度层(M4 tasks.py)统一发,
  这样 Planner 可脱离 Web/事件总线独立单测

对 LLM 输出的容错策略(写死 JSON 解析的防御套路,后续 Researcher/
Reviewer 复用同一思路):
1. 容忍 markdown 代码围栏(fence)包裹 —— 模型常手滑
2. 只做结构级校验(能解析 + 字段非空),宽松字段
3. 失败重试 1 次,并把"上次为何解析失败"回传给模型,让它自纠
4. 两次都失败就抛 PlanningError,由上层决定降级路径,绝不静默吞错
"""
import json
import logging

from ..errors import PlanningError
from ..llm.client import LLMClient
from .models import SubQuestion

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是一个研究规划 Agent。用户会给出一个研究主题,请把它拆成若干\
互不重叠、各自可独立研究回答的子问题,并为每个子问题规划 1~2 条\
用于搜索引擎的检索词(语言与主题一致)。

只输出一个 JSON 对象,不要 markdown 代码块,不要任何解释或额外文字。\
严格遵循此结构:
{"subquestions": [{"question": "...", "queries": ["...", "..."]}]}

要求:
- question 具体、不含空话,能靠检索独立回答
- queries 用高频关键词组合,让搜索结果尽量精准
"""

RETRY_SUFFIX = (
    "\n\n注意:你上一次的输出无法解析(原因: {error})。"
    "请重新输出一个合法的 JSON 对象,不要任何附加文字。"
)


class Planner:
    """研究规划 Agent。llm 由外部注入(测试传 FakeLLM)。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def plan(self, topic: str, n_sub: int = 4) -> list[SubQuestion]:
        """拆解主题为 n_sub 个(自动夹在 3~5 之间)子问题。"""
        n = max(3, min(n_sub, 5))
        prompt = f"研究主题: {topic}\n请拆解为 {n} 个子问题。"
        error: str | None = None

        for attempt in range(2):  # 首次 + 1 次自纠重试
            system = SYSTEM_PROMPT + (
                "" if error is None else RETRY_SUFFIX.format(error=error)
            )
            raw = await self._llm.complete(prompt, system=system, json_mode=True)
            try:
                return _parse_subquestions(raw)
            except ValueError as e:
                error = str(e)
                logger.warning("Planner 输出解析失败(第 %s 次): %s", attempt + 1, error)

        raise PlanningError(
            f"Planner 连续两次输出无法解析,最后错误: {error}"
        )


def _parse_subquestions(raw: str) -> list[SubQuestion]:
    """把 LLM 原始输出解析为 SubQuestion 列表;失败抛 ValueError(带原因)。"""
    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"非法 JSON: {e}") from e

    items = data.get("subquestions")
    if not isinstance(items, list) or not items:
        raise ValueError("缺少 subquestions 列表或为空")

    subs: list[SubQuestion] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"第 {i} 个子问题不是对象")
        question = str(item.get("question", "")).strip()
        if not question:
            raise ValueError(f"第 {i} 个子问题缺少 question")
        queries = item.get("queries") or []
        if not isinstance(queries, list):
            queries = []
        clean_queries = [str(q).strip() for q in queries if str(q).strip()]
        if not clean_queries:  # 模型没给检索词就退化为问题本身
            clean_queries = [question]
        # index 由系统重编,不信任模型输出的编号(可能重复/跳号/非数字)
        subs.append(SubQuestion(index=i, question=question, queries=clean_queries))
    return subs


def _strip_code_fence(text: str) -> str:
    """剥掉 ```json ... ``` 围栏(模型偶尔会裹一层)。"""
    s = text.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines)
    return s.strip()
