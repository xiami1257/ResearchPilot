"""内核数据对象(任务在 Agent 间传递的"重数据")。

与 events.py 的分工:事件是轻量广播(说"发生了什么"),
models 是重量内容(子问题、笔记、来源),只在进程内流转,
最终沉淀为报告;不进事件流、不落 SSE。

注意与事件层相反:这里的模型允许"多余字段被忽略"(默认行为),
因为字段大多来自 LLM 的 JSON 输出 —— 模型偶尔多输出一个 key
不该导致整个任务失败;我们对"外部产出的内容"宽容,
对"自己定义的事件结构"严格(events.py 的 extra="forbid")。

Reviewer 相关的产物(EvidenceReview/NoteReview)字段全部来自
我们的确定性逻辑或受控枚举,理论上可 strict —— 但保留宽松默认,
让新增诊断字段时不破坏历史数据,权衡后放弃 strict。
"""
from pydantic import BaseModel, Field

from .events import Verdict


class SubQuestion(BaseModel):
    """Planner 拆出的一个研究子问题。

    queries: 针对该子问题的候选检索词(1~2 条)。
    检索词由 Planner 显式产出,而不是 Researcher 拿着问题裸搜 ——
    好检索词是研究质量的一半,值得让模型专门规划。
    """
    index: int
    question: str
    queries: list[str] = Field(default_factory=list)


class SearchSource(BaseModel):
    """一次检索命中并被 Researcher 收录的来源(M2 起使用)。"""
    url: str
    title: str
    snippet: str = ""
    content: str = ""  # 抓取并截断后的网页正文(可能为空 = 抓取失败)


class Note(BaseModel):
    """Researcher 对一个子问题的提炼笔记。

    claim: 可被事实核验的主张(Reviewer 逐条核验的就是它);
    details: 对 claim 的展开论证;
    sources: Researcher 实际读过的来源全文(模型只能"看"这些,
        不能凭空发明 URL —— 这是防幻觉的第一道闸);
    evidence_indexes: 模型声明支撑 claim 的来源下标(指向 sources)。
        空列表 = "这些来源都不足以支撑任何主张",Reviewer 会按
        证据不足处理,而不是让模型硬编。
    """
    sub_index: int
    claim: str
    details: str = ""
    sources: list[SearchSource] = Field(default_factory=list)
    evidence_indexes: list[int] = Field(default_factory=list)


class EvidenceReview(BaseModel):
    """Reviewer 对"笔记中的一条证据引用"的核验结论。

    index: 指向 Note.sources 的下标(与 Note.evidence_indexes 同坐标系)。
    """
    index: int
    verdict: Verdict
    reason: str


class NoteReview(BaseModel):
    """Reviewer 对一个子问题笔记的整体核验结果。"""
    sub_index: int
    evidence: list[EvidenceReview] = Field(default_factory=list)

    def verdict_of(self, index: int) -> Verdict | None:
        for r in self.evidence:
            if r.index == index:
                return r.verdict
        return None
