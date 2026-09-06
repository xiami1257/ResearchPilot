"""环境配置单点读取(全部环境变量在此落定,其它模块只 import settings)。

不引 python-dotenv:部署平台(Render/HF)直接注入环境变量;
本地开发在启动命令前 export 或由用户自行加载 .env。
"""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    search_provider: str  # "serper" | "ddg"
    serper_api_key: str
    db_path: str

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def search_ready(self) -> bool:
        return self.serper_api_key != "" or self.search_provider == "ddg"


def load_settings() -> Settings:
    return Settings(
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=os.getenv("LLM_MODEL", "deepseek-chat"),
        search_provider=os.getenv("SEARCH_PROVIDER", "serper"),
        serper_api_key=os.getenv("SERPER_API_KEY", ""),
        db_path=os.getenv("DB_PATH", "researchpilot.db"),
    )
