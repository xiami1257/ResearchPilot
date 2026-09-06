"""批量跑演示主题并输出质量摘要(M5 真机打磨的主力工具)。

用法(工作目录 = agent01,真机需先配 key):
    LLM_API_KEY=sk-xxx python scripts/run_demo_topics.py            # 跑全部主题
    LLM_API_KEY=sk-xxx python scripts/run_demo_topics.py "MCP"      # 只跑含该词的

逐个主题跑完整 SessionRunner(真实 LLM + 真实检索),输出:
    状态 / 耗时 / 报告字数 / 引用数 / 证据不足块数 / 报告前 120 字
末尾给一句质量速览,便于快速判断哪些主题值得进前端演示位。

提示:无 Serper key 时自动降级 DuckDuckGo(检索质量较弱,适合先跑通,
演示前建议配 SERPER_API_KEY 提升命中率)。
"""
import asyncio
import re
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from researchpilot.app.settings import load_settings  # noqa: E402
from researchpilot.app.tasks import SessionRunner, build_default_runner  # noqa: E402

# 与 web/src/views/HomeView.tsx 的 DEMO_TOPICS 保持同步
DEMO_TOPICS = [
    "MCP 协议为什么成为 AI Agent 的事实标准?",
    "大模型 RAG 系统的主流评测基准与短板",
    "AI 编程助手对软件工程师日常工作的实际影响",
]


async def run_one(runner: SessionRunner, topic: str) -> dict:
    run_id = f"demo-{abs(hash(topic)) % 10**6}"
    runner.store.create_session(run_id, topic, status="running", stage="plan")
    t0 = time.monotonic()
    await runner.run(run_id, topic, n_sub=3)
    elapsed = time.monotonic() - t0

    s = runner.store.get_session(run_id)
    md = s["report_md"] or ""
    n_refs = len(re.findall(r"^\s*\[\d+\]\s+\S", md, re.M))
    n_insufficient = md.count("> 证据不足")
    return {
        "topic": topic,
        "ok": s["status"] == "succeeded",
        "error": s["error"] or "",
        "seconds": round(elapsed),
        "chars": len(md),
        "refs": n_refs,
        "insufficient": n_insufficient,
        "preview": md[:120].replace("\n", " "),
    }


def print_summary(results: list[dict]) -> None:
    print("\n" + "=" * 70)
    print(f"{'主题':<34}{'状态':<6}{'秒':<5}{'字数':<6}{'引用':<5}{'不足'}")
    print("-" * 70)
    for r in results:
        status = "OK " if r["ok"] else "FAIL"
        print(
            f"{r['topic'][:32]:<34}{status:<6}{r['seconds']:<5}"
            f"{r['chars']:<6}{r['refs']:<5}{r['insufficient']}"
        )
    ok_n = sum(1 for r in results if r["ok"])
    print("-" * 70)
    print(f"通过 {ok_n}/{len(results)}")
    for r in results:
        if not r["ok"]:
            print(f"  ✗ {r['topic']}: {r['error']}")
        elif r["refs"] == 0:
            print(f"  ⚠ {r['topic']}: 零引用(检索/核验全挂?看报告是否如实标证据不足)")
        else:
            print(f"  ✓ {r['topic']}: {r['preview']}…")
    print("=" * 70)


def _utf8_stdio() -> None:
    """Windows 控制台默认 GBK,强制 UTF-8 输出避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main() -> None:
    _utf8_stdio()
    settings = load_settings()
    if not settings.llm_ready:
        sys.exit("未配置 LLM_API_KEY —— 真机运行前先 export(见 README 快速开始)")

    filter_word = sys.argv[1] if len(sys.argv) > 1 else ""
    topics = [t for t in DEMO_TOPICS if filter_word in t] if filter_word else DEMO_TOPICS
    if not topics:
        sys.exit(f"没有主题包含 {filter_word!r};现有主题:\n" + "\n".join(DEMO_TOPICS))

    db = ROOT / "demo_topics.db"
    runner = build_default_runner(replace(settings, db_path=str(db)))
    print(f"搜索引擎: {'Serper' if settings.serper_api_key else 'DuckDuckGo(降级)'} | 模型: {settings.llm_model}")

    results: list[dict] = []
    try:
        for topic in topics:
            print(f"\n▶ {topic} ...")
            results.append(asyncio.run(run_one(runner, topic)))
    except KeyboardInterrupt:
        print("\n中断 —— 已跑主题摘要如下")
    print_summary(results)


if __name__ == "__main__":
    main()
