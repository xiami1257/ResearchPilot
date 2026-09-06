"""网页正文提取:抓取 + 去噪(trafilatura)。

职责与容错:
- 抓取失败 / 非 HTML / 提取为空 → 一律返回 None,绝不抛错
  (检索阶段单个网页失败不该拖垮整个任务;Researcher 拿 snippet 兜底)
- 网络超时压短(10s):Researcher 并行抓多个页面,单个慢页面
  不值得等 —— 慢 = 失败,快速放弃换下一个
- 只回纯文本(截断由调用方做),trafilatura 负责去掉导航/广告噪音
"""
import logging

import httpx
import trafilatura

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (researchpilot demo bot; contact: none)"


async def fetch_and_extract(url: str, *, max_bytes: int = 2_000_000) -> str | None:
    """抓取 url 并返回正文纯文本;任何失败返回 None。"""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": _UA},
            timeout=10.0,
        ) as client:
            resp = await client.get(url)
    except (httpx.TransportError, httpx.TimeoutException) as e:
        logger.info("抓取失败 %s: %s", url, e)
        return None
    if resp.status_code >= 400 or not resp.text:
        return None

    text = extract_text(resp.text)
    if text is None:
        return None
    # 超长正文截断(按字符,近似即可):防大页面撑爆 prompt
    if len(text) > max_bytes:
        text = text[:max_bytes]
    return text


def extract_text(html: str) -> str | None:
    """从 HTML 提取可读正文(纯函数,可单测)。失败/无正文返回 None。"""
    try:
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
    except Exception as e:  # 畸形 HTML 等,兜底
        logger.warning("trafilatura 提取异常: %s", e)
        return None
    if text is None:
        return None
    text = text.strip()
    return text or None
