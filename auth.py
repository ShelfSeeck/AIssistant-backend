#后续可能需要处理好旧refreshtoken的吊销
import hashlib
import hmac
import os
import secrets
# 认证相关逻辑，包括注册、登录、刷新 token，以及获取当前用户等功能。
from datetime import datetime, timedelta, timezone
from typing import Literal, TypedDict, cast
# 这里使用 PyJWT 来处理 JWT 生成和验证，使用 PBKDF2-HMAC 来做密码哈希，避免引入额外的依赖库。
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    DATABASE_PATH,
    JWT_ALGORITHM,
    JWT_SECRET,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from db import DatabaseFacade


router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)
db = DatabaseFacade(db_path=DATABASE_PATH)

REFRESH_COOKIE_NAME = os.getenv("REFRESH_COOKIE_NAME", "refresh_token")
REFRESH_COOKIE_PATH = os.getenv("REFRESH_COOKIE_PATH", "/auth")
REFRESH_COOKIE_SECURE = os.getenv("REFRESH_COOKIE_SECURE", "false").lower() == "true"#是否仅通过 HTTPS 传输刷新令牌 Cookie，生产环境建议设置为 true。

# 令牌类型：访问令牌和刷新令牌。
TokenType = Literal["access", "refresh"]
SameSiteType = Literal["lax", "strict", "none"]


def _normalize_samesite(raw_value: str) -> SameSiteType:
    value = raw_value.strip().lower()
    if value in ("lax", "strict", "none"):
        return cast(SameSiteType, value)
    return "lax"


REFRESH_COOKIE_SAMESITE = _normalize_samesite(os.getenv("REFRESH_COOKIE_SAMESITE", "lax"))


class UserRecord(TypedDict):
    """数据库用户对象（认证层实际用到的字段）。"""

    uuid: str
    username: str
    email: str
    password_hash: str
    created_at: float


class TokenPayload(TypedDict):
    """JWT 载荷对象。"""

    sub: str    
    type: TokenType
    iat: int
    exp: int


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    """登录请求模型，包含 email 和 password 字段。"""
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=128)


class RefreshRequest(BaseModel):
    """刷新访问令牌请求模型，只包含 refresh_token 字段。"""
    refresh_token: str = Field(min_length=1)


class UserOut(BaseModel):
    """用户信息输出模型，不包含敏感字段。"""
    uuid: str
    username: str
    email: str
    created_at: float


class TokenPair(BaseModel):
    """登录/刷新时返回的 token 对。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AccessTokenOut(BaseModel):
    """只返回 access token，refresh token 改由 HttpOnly Cookie 承载。"""

    access_token: str
    token_type: str = "bearer"


# 使用 PBKDF2-HMAC 做密码哈希，不引入额外依赖，便于先把链路跑通。
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120000)
    return f"{salt}${digest.hex()}"


# 比较时使用常量时间比较，减少时序攻击风险。
def verify_password(password: str, stored_password_hash: str) -> bool:
    """验证密码是否匹配存储的哈希值。"""
    try:
        salt_hex, digest_hex = stored_password_hash.split("$", 1)
    except ValueError:
        return False

    current_digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        120000,
    ).hex()
    return hmac.compare_digest(current_digest, digest_hex)


def _build_token(user_uuid: str, token_type: TokenType, expires_delta: timedelta) -> str:
    """生成 JWT 令牌的内部函数，统一构建 payload 和签名逻辑。"""
    now = datetime.now(timezone.utc)#获取当前 UTC 时间，确保时间相关字段的一致性和正确性。
    payload = {
        "sub": user_uuid,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_access_token(user_uuid: str) -> str:
    return _build_token(
        user_uuid=user_uuid,
        token_type="access",
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(user_uuid: str) -> str:
    return _build_token(
        user_uuid=user_uuid,
        token_type="refresh",
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, expected_type: TokenType) -> TokenPayload:
    """解码并验证 JWT 令牌，确保类型和有效性。解析JWT判断是否过期，是否有效"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    token_type = payload.get("type")
    if token_type != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token type mismatch")

    user_uuid = payload.get("sub")
    if not user_uuid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    # 这里做显式转换，帮助阅读和类型提示。
    typed_payload: TokenPayload = {
        "sub": str(payload["sub"]),
        "type": cast(TokenType, payload["type"]),
        "iat": int(payload["iat"]),
        "exp": int(payload["exp"]),
    }
    return typed_payload#返回解码后的JWT载荷，包含用户UUID、令牌类型、签发时间和过期时间等信息


def _ensure_user_record(user: dict | None) -> UserRecord:
    """把数据库查询结果规范成认证层使用的用户对象。"""

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return cast(UserRecord, user)


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """把 refresh token 写入 HttpOnly Cookie。"""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=REFRESH_COOKIE_SECURE,
        samesite=REFRESH_COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def _clear_refresh_cookie(response: Response) -> None:
    """清空 refresh token Cookie。"""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_user(payload: RegisterRequest) -> UserOut:
    existing = db.users.get_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    created = db.users.create(
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
    )
    created_user = cast(UserRecord, created)
    return UserOut(
        uuid=created_user["uuid"],
        username=created_user["username"],
        email=created_user["email"],
        created_at=float(created_user["created_at"]),
    )


@router.post("/login", response_model=AccessTokenOut)
def login_user(payload: LoginRequest, response: Response) -> AccessTokenOut:
    """登录流程：验证用户凭据，生成访问令牌和刷新令牌，并通过 HttpOnly Cookie 返回刷新令牌。"""
    user = db.users.get_by_email(payload.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user_record = cast(UserRecord, user)

    if not verify_password(payload.password, user_record["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(user_record["uuid"])
    refresh_token = create_refresh_token(user_record["uuid"])
    _set_refresh_cookie(response, refresh_token)
    return AccessTokenOut(access_token=access_token)


@router.post("/refresh", response_model=AccessTokenOut)
def refresh_access_token(request: Request, response: Response) -> AccessTokenOut:
    refresh_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token cookie")

    token_payload = decode_token(refresh_token, expected_type="refresh")
    user_uuid = token_payload["sub"]

    user = db.users.get_by_uuid(user_uuid)
    _ensure_user_record(user)

    access_token = create_access_token(user_uuid)
    new_refresh_token = create_refresh_token(user_uuid)
    _set_refresh_cookie(response, new_refresh_token)
    return AccessTokenOut(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    """退出登录：清除 refresh token Cookie。"""
    _clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT#因为fastapi默认的相应码返回只有在你返回了一个非空响应体才会生效，因此这里需要自己补全
    return response#返回空响应保证可读性


def get_current_user_uuid(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    """从 Authorization 头中提取访问令牌，解码并验证后返回用户 UUID,源文件中暂未被调用"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token")

    token_payload = decode_token(credentials.credentials, expected_type="access")
    return token_payload["sub"]


def get_current_user(user_uuid: str = Depends(get_current_user_uuid)) -> UserRecord:
    """根据用户 UUID 获取当前用户信息，供其他接口使用,源文件中暂未被调用"""
    user = db.users.get_by_uuid(user_uuid)
    return _ensure_user_record(user)
