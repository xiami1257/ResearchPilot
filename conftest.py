"""pytest 根配置:保证 src 可导入(沿用 taobao_100mdate 的做法)"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    """注册自定义 marker,消除 -m e2e 的未注册警告。"""
    config.addinivalue_line("markers", "e2e: 真实 LLM + 真实检索的端到端冒烟(需配 LLM_API_KEY,慢)")
    config.addinivalue_line("markers", "slow: 慢速测试,默认不跑")
