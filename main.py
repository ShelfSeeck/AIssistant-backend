from contextlib import asynccontextmanager

from fastapi import FastAPI

from auth import router as auth_router
from config import APP_NAME, DATABASE_PATH
from db import setup_database
from loop import router as loop_router


@asynccontextmanager
async def lifespan(_: FastAPI):
	"""应用生命周期管理器（就是资源（例如说数据库）的初始化和清理），在应用启动时设置数据库连接，并在应用关闭时进行清理（如果需要）。"""
	setup_database(db_path=DATABASE_PATH)
	yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)


@app.get("/")
def root() -> dict[str, str]:
	"""服务根路由，用于快速确认服务在线。"""
	return {"service": APP_NAME, "status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
	"""健康检查路由，用于探针与联调。"""
	return {"status": "healthy"}


# 认证路由包含 register/login/refresh/logout。
app.include_router(auth_router)

# 聊天主循环路由，包含会话消息发送和工具注册信息。
app.include_router(loop_router)