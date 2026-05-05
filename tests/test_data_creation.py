"""测试项目创建端点 POST /users/{uid}/projects"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.auth import create_access_token, hash_password
from backend.db import DatabaseFacade


@pytest.fixture()
def tmp_db(tmp_path):
    """创建临时数据库实例并初始化 schema。"""
    db_path = str(tmp_path / "test.db")
    db = DatabaseFacade(db_path=db_path)
    db.setup_database()
    return db


@pytest.fixture()
def client(tmp_db, monkeypatch):
    """使用临时数据库构造 TestClient，替换 backend.data.db。"""
    # 设置 JWT_SECRET 以便 create_access_token 能正常工作
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-unit-tests")

    import backend.data as data_mod

    monkeypatch.setattr(data_mod, "db", tmp_db)

    # 同步替换 backend.auth.db，确保 get_current_user 查的是同一个数据库
    import backend.auth as auth_mod

    monkeypatch.setattr(auth_mod, "db", tmp_db)

    from backend.main import app

    return TestClient(app)


def _create_user_and_token(db: DatabaseFacade, username: str = "testuser", email: str | None = None):
    """在数据库中创建测试用户并返回 (user_uuid, access_token)。"""
    if email is None:
        email = f"{username}@example.com"
    user = db.users.create(
        username=username,
        email=email,
        password_hash=hash_password("password123"),
    )
    token = create_access_token(user["uuid"])
    return user["uuid"], token


def test_create_project_success(client: TestClient, tmp_db):
    """成功创建项目，返回 201 及完整项目信息。"""
    user_uuid, token = _create_user_and_token(tmp_db)

    resp = client.post(
        f"/users/{user_uuid}/projects",
        json={"projectname": "我的项目"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["projectname"] == "我的项目"
    assert "pid" in body and len(body["pid"]) > 0
    assert "timestamp" in body and isinstance(body["timestamp"], float)
    assert "created_at" in body and isinstance(body["created_at"], float)


def test_create_project_empty_name_rejected(client: TestClient, tmp_db):
    """空项目名应被拒绝，返回 422。"""
    user_uuid, token = _create_user_and_token(tmp_db)

    resp = client.post(
        f"/users/{user_uuid}/projects",
        json={"projectname": ""},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 422


def test_create_project_for_other_user_rejected(client: TestClient, tmp_db):
    """为其他用户创建项目应被拒绝，返回 403。"""
    user_uuid, token = _create_user_and_token(tmp_db, username="attacker")
    other_uuid, _ = _create_user_and_token(tmp_db, username="victim", email="victim@example.com")

    resp = client.post(
        f"/users/{other_uuid}/projects",
        json={"projectname": "不该创建的项目"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 403
    body = resp.json()
    assert body["detail"]["code"] == "FORBIDDEN"
