"""
data.py - 数据传输与查询路由模块

职责：
1. 提供资源查询相关 HTTP 端点
2. 提供工具注册表查询端点
3. 提供消息版本查询与切换端点
4. 提供基础健康检查端点（root/health）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.config import APP_NAME, DATABASE_PATH
from backend.db import DatabaseFacade
from backend.tool import get_registered_tool_names


db = DatabaseFacade(db_path=DATABASE_PATH)
router = APIRouter(tags=["data"])


@router.get("/")
def root() -> dict[str, str]:
    """服务根路由，用于快速确认服务在线。"""
    return {"service": APP_NAME, "status": "ok"}


@router.get("/health")
def health() -> dict[str, str]:
    """健康检查路由，用于探针与联调。"""
    return {"status": "healthy"}


class ProjectItem(BaseModel):
    """项目信息"""

    pid: str
    projectname: str
    timestamp: float
    created_at: float


class ProjectListResponse(BaseModel):
    """用户项目列表响应"""

    projects: list[ProjectItem]


class CreateProjectRequest(BaseModel):
    """创建项目请求"""

    projectname: str = Field(..., min_length=1, max_length=100, description="项目名称")


class SessionItem(BaseModel):
    """会话信息"""

    sid: str
    sessionname: str
    timestamp: float
    created_at: float


class SessionListResponse(BaseModel):
    """项目会话列表响应"""

    sessions: list[SessionItem]


class CreateSessionRequest(BaseModel):
    """创建会话请求"""

    sessionname: str = Field(..., min_length=1, max_length=100, description="会话名称")


class MessageItem(BaseModel):
    """消息信息"""

    msg_id: str
    kind: str
    raw_json: str
    timestamp: float
    created_at: float
    parent_msg_id: str | None = None
    version: int = 1
    is_latest: int = 1


class MessageListResponse(BaseModel):
    """会话消息列表响应"""

    messages: list[MessageItem]


@router.get("/users/{user_id}/projects", response_model=ProjectListResponse)
def list_user_projects(
    user_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ProjectListResponse:
    """查询用户所拥有的项目"""
    jwt_user_uuid = current_user.get("uuid")
    if user_id != jwt_user_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Cannot access other user's projects"},
        )

    projects = db.projects.list_by_user(user_uuid=user_id)
    return ProjectListResponse(
        projects=[
            ProjectItem(
                pid=p["pid"],
                projectname=p["projectname"],
                timestamp=float(p["timestamp"]),
                created_at=float(p["created_at"]),
            )
            for p in projects
        ]
    )


@router.post(
    "/users/{user_id}/projects",
    response_model=ProjectItem,
    status_code=status.HTTP_201_CREATED,
)
def create_user_project(
    user_id: str,
    payload: CreateProjectRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ProjectItem:
    """为用户创建新项目。"""
    jwt_user_uuid = current_user.get("uuid")
    if user_id != jwt_user_uuid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Cannot create project for other user"},
        )
    project = db.projects.create(
        projectname=payload.projectname,
        user_uuid=user_id,
    )
    return ProjectItem(
        pid=project["pid"],
        projectname=project["projectname"],
        timestamp=float(project["timestamp"]),
        created_at=float(project["created_at"]),
    )


@router.get("/projects/{pid}/sessions", response_model=SessionListResponse)
def list_project_sessions(
    pid: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SessionListResponse:
    """查询项目下的所有会话"""
    user_uuid = current_user.get("uuid")
    if not isinstance(user_uuid, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )

    project = db.projects.get_for_user(pid=pid, user_uuid=user_uuid)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "Project not found"},
        )

    sessions = db.sessions.list_by_project(pid=pid)
    return SessionListResponse(
        sessions=[
            SessionItem(
                sid=s["sid"],
                sessionname=s["sessionname"],
                timestamp=float(s["timestamp"]),
                created_at=float(s["created_at"]),
            )
            for s in sessions
        ]
    )


@router.post(
    "/projects/{pid}/sessions",
    response_model=SessionItem,
    status_code=status.HTTP_201_CREATED,
)
def create_project_session(
    pid: str,
    payload: CreateSessionRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SessionItem:
    """在项目下创建新会话。"""
    user_uuid = current_user.get("uuid")
    if not isinstance(user_uuid, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )

    project = db.projects.get_for_user(pid=pid, user_uuid=user_uuid)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "Project not found"},
        )

    session = db.sessions.create(
        pid=pid,
        sessionname=payload.sessionname,
    )
    return SessionItem(
        sid=session["sid"],
        sessionname=session["sessionname"],
        timestamp=float(session["timestamp"]),
        created_at=float(session["created_at"]),
    )


@router.get("/sessions/{sid}/messages", response_model=MessageListResponse)
def list_session_messages(
    sid: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> MessageListResponse:
    """查询会话的所有消息"""
    user_uuid = current_user.get("uuid")
    if not isinstance(user_uuid, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )

    session = db.sessions.get_for_user(sid=sid, user_uuid=user_uuid)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "RESOURCE_NOT_FOUND", "message": "Session not found"},
        )

    messages = db.messages.list_by_session_for_user(sid=sid, user_uuid=user_uuid)
    return MessageListResponse(
        messages=[
            MessageItem(
                msg_id=m["msg_id"],
                kind=m["kind"],
                raw_json=m["raw_json"],
                timestamp=float(m["timestamp"]),
                created_at=float(m["created_at"]),
                parent_msg_id=m.get("parent_msg_id"),
                version=m.get("version", 1),
                is_latest=m.get("is_latest", 1),
            )
            for m in messages
        ]
    )


class ToolRegistryResponse(BaseModel):
    """工具注册表查询响应"""

    tools: list[str]
    global_allowed_tools: list[str]


@router.get("/tools/registry", response_model=ToolRegistryResponse)
def list_tool_registry() -> ToolRegistryResponse:
    """查询工具注册表。"""
    return ToolRegistryResponse(
        tools=sorted(get_registered_tool_names()),
        global_allowed_tools=sorted(get_registered_tool_names()),
    )


class MessageVersionItem(BaseModel):
    """消息版本项"""

    msg_id: str
    kind: str
    raw_json: str
    version: int
    is_latest: int
    timestamp: float
    created_at: float


class MessageVersionsResponse(BaseModel):
    """消息版本列表响应"""

    versions: list[MessageVersionItem]


@router.get("/messages/{msg_id}/versions", response_model=MessageVersionsResponse)
def get_message_versions(
    msg_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> MessageVersionsResponse:
    """查询某条消息作为 parent 的所有版本。"""
    user_uuid = current_user.get("uuid")
    if not isinstance(user_uuid, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )

    versions = db.messages.list_versions(
        parent_msg_id=msg_id,
        user_uuid=user_uuid,
    )
    return MessageVersionsResponse(
        versions=[
            MessageVersionItem(
                msg_id=v["msg_id"],
                kind=v["kind"],
                raw_json=v["raw_json"],
                version=v["version"],
                is_latest=v["is_latest"],
                timestamp=float(v["timestamp"]),
                created_at=float(v["created_at"]),
            )
            for v in versions
        ]
    )


class SwitchVersionRequest(BaseModel):
    """切换版本请求"""

    target_version_msg_id: str = Field(..., description="要切换到的版本的消息 ID")


class SwitchVersionResponse(BaseModel):
    """切换版本响应"""

    success: bool
    switched_msg_id: str


@router.post("/messages/{msg_id}/switch-version", response_model=SwitchVersionResponse)
def switch_to_message_version(
    msg_id: str,
    payload: SwitchVersionRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SwitchVersionResponse:
    """切换到指定版本。"""
    user_uuid = current_user.get("uuid")
    if not isinstance(user_uuid, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_TOKEN_INVALID", "message": "Invalid token"},
        )

    success = db.messages.switch_version(
        msg_id=payload.target_version_msg_id,
        user_uuid=user_uuid,
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "SWITCH_FAILED", "message": "Failed to switch version"},
        )

    return SwitchVersionResponse(
        success=True,
        switched_msg_id=payload.target_version_msg_id,
    )
