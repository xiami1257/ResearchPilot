"""Reviewer:对 Researcher 产出的笔记做第二道防幻觉闸。

核验什么(诚实的能力边界要讲清楚):
- Reviewer **不重新上网**:它手里只有 Researcher 抓回来的来源内容
  (以及失败的标记)。它核验的是"**声称 vs 证据的一致性**":
  claim 是否真的被列出的来源支撑?有没有言过其实?引用是否张冠李戴?
- 它**不能**验证网页真实性/时效性 —— 那需要独立检索,超出 V1 范围
  (面试被问到就说:这道闸查"内部一致性",外部真实性靠 Reviewer
  的可访问性+多源交叉在流程上是缺失的,是已知限制,记录在案)

确定性预检(零 LLM 调用、零网络):
- 笔记声明引用的来源如果"既没有正文也没有摘要"(抓取失败的),
  直接判 UNVERIFIABLE —— 没有证据可核,不许模型脑补

故障降级策略(与 Planner/Researcher 不同,有意为之):
- 单个笔记的核验输出两次解析失败 → 该笔记全部证据标 UNVERIFIABLE,
  不抛错。核验是质量增强层,不该成为单点故障 —— 宁可"未核验"
  地进入报告,也不要一个解析错误让整个任务失败。这个取舍写进
  设计文档,面试官问"为什么这里和 Planner 不一样"时能讲出依据。
"""
import asyncio
import json
import logging

from ..errors import LlmError
from ..llm.client import LLMClient
from .events import Verdict
from .models import EvidenceReview, Note, NoteReview

logger = logging.getLogger(__name__)

_SYSTEM = """\
你是一名事实核查员。你会收到一个研究主张(claim)及其论证(details),
以及若干编号的证据来源(真实抓取的网页内容或摘要)。

请逐条核查:该来源的内容是否真正支撑了 claim 中对应的事实。
只输出一个 JSON 对象:
{"reviews": [{"index": 0, "verdict": "supported", "reason": "..."}]}

verdict 取值仅限:supported / unsupported / unverifiable
- supported:   该来源确实支撑 claim(或其相应部分)
- unsupported: 该来源与 claim 不符、无关或不能支撑(应被剔除)
- unverifiable:内容不足以判断(太短/无关片段/质量太差)
reason 一句话说明判断依据。严禁新增规则之外的编号与字段。
"""

_RETRY = (
    "\n\n注意:你上次的输出无法解析(原因: {error})。"
    "请重新输出一个合法 JSON 对象。"
)


class Reviewer:
    """逐笔记核验。llm 注入;失败降级为 UNVERIFIABLE。"""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def review_note(self, note: Note) -> NoteReview:
        """核验一个笔记,返回逐条证据的判定。"""
        # -- 第 0 步:确定性预检 ------------------------------------------
        # 声明引用的来源没有任何可核内容 => 直接 UNVERIFIABLE,不进 LLM
        candidates: list[int] = []
        auto: list[EvidenceReview] = []
        for i in note.evidence_indexes:
            src = note.sources[i]
            if not src.content and not src.snippet:
                auto.append(EvidenceReview(
                    index=i, verdict=Verdict.UNVERIFIABLE,
                    reason="来源抓取失败,无正文也无摘要,无法核验",
                ))
            else:
                candidates.append(i)

        if not candidates:  # 全部自动判死,无需调 LLM
            return NoteReview(sub_index=note.sub_index, evidence=auto)

        error: str | None = None
        for attempt in range(2):
            raw = await self._llm.complete(
                self._build_prompt(note, candidates),
                system=_SYSTEM + ("" if error is None else _RETRY.format(error=error)),
                json_mode=True,
            )
            try:
                judged = _parse_reviews(raw, allowed=set(candidates))
                return NoteReview(
                    sub_index=note.sub_index,
                    evidence=auto + judged,  # 自动判定 + 模型判定
                )
            except ValueError as e:
                error = str(e)
                logger.warning(
                    "Reviewer 解析失败(第 %s 次, sub=%s): %s",
                    attempt + 1, note.sub_index, error,
                )

        # 降级:全部候选证据标 UNVERIFIABLE(见模块 docstring 的取舍说明)
        logger.warning("Reviewer 降级:sub=%s 全部证据标记为未核验", note.sub_index)
        return NoteReview(
            sub_index=note.sub_index,
            evidence=auto
            + [
                EvidenceReview(
                    index=i, verdict=Verdict.UNVERIFIABLE,
                    reason="核验输出无法解析,保守标记未核验",
                )
                for i in candidates
            ],
        )

    # -- 内部 -------------------------------------------------------------

    def _build_prompt(self, note: Note, candidates: list[int]) -> str:
        lines = [
            f"研究主张(claim): {note.claim}",
            f"论证(details): {note.details or '(无)'}",
            "",
            "可核查的证据来源(只核查下列编号):",
        ]
        for i in candidates:
            src = note.sources[i]
            body = src.content or src.snippet or "(无内容)"
            if len(body) > 1500:
                body = body[:1500]
            lines.append(
                f"\n[{i}] 标题: {src.title}\n    地址: {src.url}\n    内容: {body}"
            )
        return "\n".join(lines)


async def run_review_phase(
    notes: list[Note], *, llm: LLMClient, max_concurrent: int = 5
) -> list[NoteReview]:
    """并行核验全部笔记,返回与 notes 顺序一致的 NoteReview 列表。"""
    cap = min(max_concurrent, len(notes)) or 1
    semaphore = asyncio.Semaphore(cap)
    reviewer = Reviewer(llm)

    async def worker(note: Note) -> NoteReview:
        async with semaphore:
            return await reviewer.review_note(note)

    return list(await asyncio.gather(*(worker(n) for n in notes)))


def _parse_reviews(raw: str, *, allowed: set[int]) -> list[EvidenceReview]:
    """解析核验 JSON;编号必须落在 allowed 集合内(模型不许发明编号)。"""
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

    items = data.get("reviews")
    if not isinstance(items, list) or not items:
        raise ValueError("缺少 reviews 列表或为空")

    out: list[EvidenceReview] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("review 项不是对象")
        index = item.get("index")
        verdict_raw = item.get("verdict")
        reason = str(item.get("reason", "")).strip()
        if isinstance(index, bool) or not isinstance(index, int):
            raise ValueError(f"index 非法: {index!r}")
        if index not in allowed:
            raise ValueError(f"编号 {index} 不在可核验集合内")
        try:
            verdict = Verdict(verdict_raw)
        except ValueError:
            raise ValueError(f"verdict 非法: {verdict_raw!r}") from None
        if not reason:
            raise ValueError(f"编号 {index} 缺少 reason")
        out.append(EvidenceReview(index=index, verdict=verdict, reason=reason))
    return out
