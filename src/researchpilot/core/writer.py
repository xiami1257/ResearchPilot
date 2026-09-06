"""Writer:把核验过的素材写成带 [n] 引用的 Markdown 报告。

防幻觉最后一道闸的执行点(配合 report.py 的确定性规则):
- 模型只能引用给它编号表中的引用(编号对应 SUPPORTED 来源)
- 引用编号表之外任何 [n] 都被 _sanitize_citations 确定性替换掉
- 证据不足的子问题节被要求明示标注,不许硬凑内容
"""
import json
import logging
import re

from ..errors import WritingError
from ..llm.client import LLMClient
from .report import CitedSource, SectionDraft

logger = logging.getLogger(__name__)

SYSTEM = """\
你是一名资深研究报告撰写者。你会收到一份主题、若干小节的素材
(每个小节对应一个研究子问题)以及一份带编号的引用来源表。

请输出一篇结构清晰的 Markdown 报告(输出为 JSON 包装):
{"report_md": "完整 markdown 全文"}

规则:
1. 组织:报告以主题为一级标题;每个子问题为独立小节(合理拟定
   小节标题,不必照抄子问题原文)
2. 引用:文中需要支撑事实的地方用 [n] 引用,只允许使用素材中
   明确列出的引用编号,严禁使用编号表之外的任何编号
3. 标记为【证据不足】的小节:必须用 "> 证据不足:..." 引用块明示,
   如实转述素材给出的说明,不得编造事实、不得引用(该节没有可用编号)
4. 只输出 JSON,不要 markdown 代码块包裹
5. 不要输出文末"引用来源"标题及其下的 URL 列表 —— 引用表由系统
   按编号表确定性生成(文末再出现即视为重复,必须避免)
"""

_RETRY = (
    "\n\n注意:你上次的输出无法解析(原因: {error})。"
    "请重新输出一个合法 JSON 对象。"
)

_CT = re.compile(r"\[(\d+)\]")


class Writer:
    """报告撰写 Agent。llm 注入。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def write(
        self,
        topic: str,
        sections: list[SectionDraft],
        pool: list[CitedSource],
    ) -> str:
        """产出报告 markdown(已做引用消毒)。"""
        prompt = self._build_prompt(topic, sections, pool)
        error: str | None = None
        for attempt in range(2):
            raw = await self._llm.complete(prompt, system=SYSTEM, json_mode=True)
            try:
                md = _extract_report(raw)
            except ValueError as e:
                error = str(e)
                logger.warning("Writer 输出解析失败(第 %s 次): %s", attempt + 1, error)
                continue
            return _sanitize_citations(md, max_no=len(pool))

        raise WritingError(f"Writer 连续两次输出无法解析: {error}")

    # -- 内部 -------------------------------------------------------------

    def _build_prompt(
        self, topic: str, sections: list[SectionDraft], pool: list[CitedSource]
    ) -> str:
        lines = [f"报告主题: {topic}", "", "引用来源表(写作时唯一可用编号):"]
        if not pool:
            lines.append("(没有任何通过核验的来源 —— 报告应整体如实说明证据不足)")
        for c in pool:
            lines.append(f"[{c.citation_no}] {c.title} | {c.url}")
        lines.append("")

        for s in sections:
            tag = "【证据不足】" if s.insufficient else ""
            usable = (
                "无可用引用编号" if s.insufficient
                else ", ".join(f"[{n}]" for n in s.citation_nos)
            )
            lines.append(
                f"\n## 小节素材({tag}): {s.question}\n"
                f"可用引用: {usable}\n"
                f"主张: {s.claim}\n"
                f"论证: {s.details or '(无)'}\n"
                f"要求: {'按规则 3 明示证据不足' if s.insufficient else '正常成文并恰当引用'}"
            )
        return "\n".join(lines)


def _extract_report(raw: str) -> str:
    """从 LLM 输出提取 report_md 字段。"""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"非法 JSON: {e}") from e
    md = str(data.get("report_md", "")).strip()
    if not md:
        raise ValueError("缺少 report_md 或为空")
    return md


def _sanitize_citations(md: str, *, max_no: int) -> str:
    """确定性消毒:编号表外的 [n] / 越界编号替换为 [?](不信任模型)。"""
    def fix(m: re.Match) -> str:
        n = int(m.group(1))
        return f"[{n}]" if 1 <= n <= max_no else "[?]"

    return _CT.sub(fix, md)
