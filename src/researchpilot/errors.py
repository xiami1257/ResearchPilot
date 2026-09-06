"""全包共享异常。

放包根而不是 core/ 里,是因为 llm / search / app 各层都可能抛错,
都来 import core 会形成不合理的耦合;异常是横切概念,归属包根最自然。
"""


class AgentError(Exception):
    """所有业务异常的统一基类(方便上层 except AgentError 一把接住)。"""


class StageMachineError(AgentError):
    """状态机非法迁移。"""


class LlmError(AgentError):
    """LLM 调用失败(网络、限流、响应格式异常)。"""


class PlanningError(AgentError):
    """规划阶段失败(LLM 输出多次无法解析等)。"""


class SearchError(AgentError):
    """检索服务调用失败(限流、上游错误、响应异常)。"""


class ResearchError(AgentError):
    """研究(检索/提炼)阶段失败。"""


class WritingError(AgentError):
    """报告撰写阶段失败(LLM 输出多次无法解析等)。"""
