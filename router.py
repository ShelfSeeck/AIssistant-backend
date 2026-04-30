from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.auth import router as auth_router
from backend.config import APP_NAME, DATABASE_PATH
from backend.data import router as data_router
from backend.db import DatabaseFacade
from backend.loop import router as loop_router


db = DatabaseFacade(db_path=DATABASE_PATH)


@asynccontextmanager
async def lifespan(_: FastAPI):
	"""应用生命周期管理器（就是资源（例如说数据库）的初始化和清理），在应用启动时设置数据库连接，并在应用关闭时进行清理（如果需要）。"""
	db.setup_database()
	yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)


# 认证路由包含 register/login/refresh/logout。
app.include_router(auth_router)

# 数据查询与基础健康路由。
app.include_router(data_router)

# 聊天主循环路由，包含会话消息发送与 regenerate。
app.include_router(loop_router)