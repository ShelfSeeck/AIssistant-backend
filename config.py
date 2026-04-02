import os
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


# 项目根目录用于拼接默认数据库和技能存储目录。
BASE_DIR = Path(__file__).resolve().parent

# 后端基础配置（后续文件直接 import 使用）。
APP_NAME = os.getenv("APP_NAME", "Agentist")
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "project.db"))
SKILL_STORAGE_DIR = os.getenv("SKILL_STORAGE_DIR", str(BASE_DIR / "skills_storage"))

# JWT 配置，先给开发默认值，生产环境请务必通过环境变量覆盖。
JWT_SECRET = os.getenv("JWT_SECRET", "")#JWT密钥
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# 模型配置，统一由环境变量驱动，避免密钥硬编码在代码中。
MODEL_PROVIDER_API_KEY = os.getenv("MODEL_PROVIDER_API_KEY", "")
MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "")
MODEL_NAME = os.getenv("MODEL_NAME", "")


def get_chat_model() -> OpenAIChatModel:
    """构建聊天模型实例。"""
    if not MODEL_PROVIDER_API_KEY:
        raise RuntimeError(
            "Missing MODEL_PROVIDER_API_KEY. Please set it in environment variables."
        )

    provider = OpenAIProvider(
        base_url=MODEL_BASE_URL,
        api_key=MODEL_PROVIDER_API_KEY,
    )
    return OpenAIChatModel(
        MODEL_NAME,
        provider=provider,
    )


def create_chat_agent(instructions: str | None = None) -> Agent:
    """创建一个可复用的 Pydantic AI Agent。使用函数来实现复用"""
    return Agent(
        get_chat_model(),
        instructions=instructions or "You are a helpful assistant.",
    )
