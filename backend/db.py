from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_core import to_json


class _DataBase:
    """数据对象基类，统一访问根 Facade 的连接与工具能力。"""

    def __init__(self, root: "DatabaseFacade"):
        self._root = root

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._root.db_cursor() as cursor:
            yield cursor

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        return self._root._row_to_dict(row)

    def _now_timestamp(self) -> float:
        return self._root._now_timestamp()


class UsersFacade(_DataBase):
    def create(self, username: str, email: str, password_hash: str) -> dict:
        user_uuid = str(uuid.uuid4())
        created_at = self._now_timestamp()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (uuid, username, email, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_uuid, username, email, password_hash, created_at),
            )
        user = self.get_by_uuid(user_uuid)
        if user is None:
            raise RuntimeError("User was inserted but could not be loaded.")
        return user

    def get_by_email(self, email: str) -> dict | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT uuid, username, email, password_hash, created_at FROM users WHERE email = ?",
                (email,),
            )
            row = cursor.fetchone()
        return self._row_to_dict(row)

    def get_by_uuid(self, user_uuid: str) -> dict | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT uuid, username, email, password_hash, created_at FROM users WHERE uuid = ?",
                (user_uuid,),
            )
            row = cursor.fetchone()
        return self._row_to_dict(row)

    def delete_by_uuid(self, user_uuid: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE uuid = ?", (user_uuid,))
            affected = cursor.rowcount
        return affected > 0


class ProjectsFacade(_DataBase):
    def create(self, projectname: str, user_uuid: str) -> dict:
        pid = str(uuid.uuid4())
        now_ts = self._now_timestamp()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO projects (pid, projectname, user_uuid, timestamp, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (pid, projectname, user_uuid, now_ts, now_ts),
            )
        project = self.get_by_id(pid)
        if project is None:
            raise RuntimeError("Project was inserted but could not be loaded.")
        return project

    def list_by_user(self, user_uuid: str) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT pid, projectname, user_uuid, timestamp, created_at
                FROM projects
                WHERE user_uuid = ?
                ORDER BY timestamp DESC
                """,
                (user_uuid,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_by_id(self, pid: str) -> dict | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT pid, projectname, user_uuid, timestamp, created_at FROM projects WHERE pid = ?",
                (pid,),
            )
            row = cursor.fetchone()
        return self._row_to_dict(row)

    def get_for_user(self, pid: str, user_uuid: str) -> dict | None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT pid, projectname, user_uuid, timestamp, created_at
                FROM projects
                WHERE pid = ? AND user_uuid = ?
                """,
                (pid, user_uuid),
            )
            row = cursor.fetchone()
        return self._row_to_dict(row)

    def delete_for_user(self, pid: str, user_uuid: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute(
                "DELETE FROM projects WHERE pid = ? AND user_uuid = ?",
                (pid, user_uuid),
            )
            affected = cursor.rowcount
        return affected > 0


class SessionsFacade(_DataBase):
    def create(self, pid: str, sessionname: str) -> dict:
        sid = str(uuid.uuid4())
        now_ts = self._now_timestamp()
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO sessions (sid, pid, sessionname, timestamp, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sid, pid, sessionname, now_ts, now_ts),
            )
        session = self.get_by_id(sid)
        if session is None:
            raise RuntimeError("Session was inserted but could not be loaded.")
        return session

    def touch_timestamp(self, sid: str) -> bool:
        now_ts = self._now_timestamp()
        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE sessions SET timestamp = ? WHERE sid = ?",
                (now_ts, sid),
            )
            affected = cursor.rowcount
        return affected > 0

    def list_by_project(self, pid: str) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT sid, pid, sessionname, timestamp, created_at
                FROM sessions
                WHERE pid = ?
                ORDER BY timestamp DESC
                """,
                (pid,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_by_id(self, sid: str) -> dict | None:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT sid, pid, sessionname, timestamp, created_at FROM sessions WHERE sid = ?",
                (sid,),
            )
            row = cursor.fetchone()
        return self._row_to_dict(row)

    def get_for_user(self, sid: str, user_uuid: str) -> dict | None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT s.sid, s.pid, s.sessionname, s.timestamp, s.created_at
                FROM sessions AS s
                JOIN projects AS p ON s.pid = p.pid
                WHERE s.sid = ? AND p.user_uuid = ?
                """,
                (sid, user_uuid),
            )
            row = cursor.fetchone()
        return self._row_to_dict(row)

    def list_by_user(self, user_uuid: str) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT s.sid, s.pid, s.sessionname, s.timestamp, s.created_at
                FROM sessions AS s
                JOIN projects AS p ON s.pid = p.pid
                WHERE p.user_uuid = ?
                ORDER BY s.timestamp DESC
                """,
                (user_uuid,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def delete_by_id(self, sid: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
            affected = cursor.rowcount
        return affected > 0

    def delete_for_user(self, sid: str, user_uuid: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM sessions
                WHERE sid = ?
                  AND pid IN (SELECT pid FROM projects WHERE user_uuid = ?)
                """,
                (sid, user_uuid),
            )
            affected = cursor.rowcount
        return affected > 0


class MessagesFacade(_DataBase):
    @staticmethod
    def _serialize_message(message: ModelMessage) -> str:
        return to_json(message).decode("utf-8")

    def create(
        self,
        sid: str,
        kind: str,
        raw_json: str,
        parent_msg_id: str | None = None,
        version: int | None = None,
        is_latest: int = 1,
    ) -> dict:
        msg_id = str(uuid.uuid4())
        message_timestamp = self._now_timestamp()
        # 设置默认版本号
        if version is None:
            version = 1
        with self._cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO messages (msg_id, sid, kind, raw_json, timestamp, parent_msg_id, version, is_latest, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    sid,
                    kind,
                    raw_json,
                    message_timestamp,
                    parent_msg_id,
                    version,
                    is_latest,
                    message_timestamp,
                ),
            )
        message = self.get_by_id(msg_id)
        if message is None:
            raise RuntimeError("Message was inserted but could not be loaded.")
        return message

    def create_for_user(
        self,
        sid: str,
        user_uuid: str,
        kind: str,
        raw_json: str,
        parent_msg_id: str | None = None,
        version: int | None = None,
        is_latest: int = 1,
    ) -> dict:
        owned_session = self._root.sessions.get_for_user(sid=sid, user_uuid=user_uuid)
        if owned_session is None:
            raise PermissionError("Session does not belong to the current user.")
        return self.create(
            sid=sid,
            kind=kind,
            raw_json=raw_json,
            parent_msg_id=parent_msg_id,
            version=version,
            is_latest=is_latest,
        )

    def get_by_id(self, msg_id: str) -> dict | None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT msg_id, sid, kind, raw_json, timestamp, parent_msg_id, version, is_latest, created_at
                FROM messages
                WHERE msg_id = ?
                """,
                (msg_id,),
            )
            row = cursor.fetchone()
        return self._row_to_dict(row)

    def get_for_user(self, msg_id: str, user_uuid: str) -> dict | None:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.timestamp, m.parent_msg_id, m.version, m.is_latest, m.created_at
                FROM messages AS m
                JOIN sessions AS s ON m.sid = s.sid
                JOIN projects AS p ON s.pid = p.pid
                WHERE m.msg_id = ? AND p.user_uuid = ?
                """,
                (msg_id, user_uuid),
            )
            row = cursor.fetchone()
        return self._row_to_dict(row)

    def list_by_session(self, sid: str) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT msg_id, sid, kind, raw_json, timestamp, parent_msg_id, version, is_latest, created_at
                FROM messages
                WHERE sid = ?
                ORDER BY timestamp ASC
                """,
                (sid,),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def list_by_session_for_user(self, sid: str, user_uuid: str) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.timestamp, m.parent_msg_id, m.version, m.is_latest, m.created_at
                FROM messages AS m
                JOIN sessions AS s ON m.sid = s.sid
                JOIN projects AS p ON s.pid = p.pid
                WHERE m.sid = ? AND p.user_uuid = ?
                ORDER BY m.timestamp ASC
                """,
                (sid, user_uuid),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def list_latest_by_session_for_user(self, sid: str, user_uuid: str) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.timestamp, m.parent_msg_id, m.version, m.is_latest, m.created_at
                FROM messages AS m
                JOIN sessions AS s ON m.sid = s.sid
                JOIN projects AS p ON s.pid = p.pid
                WHERE m.sid = ? AND p.user_uuid = ? AND m.is_latest = 1
                ORDER BY m.timestamp ASC
                """,
                (sid, user_uuid),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def list_by_session_page(self, sid: str, limit: int = 20, offset: int = 0) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT msg_id, sid, kind, raw_json, timestamp, parent_msg_id, version, is_latest, created_at
                FROM messages
                WHERE sid = ?
                ORDER BY timestamp ASC
                LIMIT ? OFFSET ?
                """,
                (sid, limit, offset),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def list_by_session_page_for_user(
        self,
        sid: str,
        user_uuid: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.timestamp, m.parent_msg_id, m.version, m.is_latest, m.created_at
                FROM messages AS m
                JOIN sessions AS s ON m.sid = s.sid
                JOIN projects AS p ON s.pid = p.pid
                WHERE m.sid = ? AND p.user_uuid = ?
                ORDER BY m.timestamp ASC
                LIMIT ? OFFSET ?
                """,
                (sid, user_uuid, limit, offset),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def count_by_session(self, sid: str) -> int:
        with self._cursor() as cursor:
            cursor.execute("SELECT COUNT(1) AS total FROM messages WHERE sid = ?", (sid,))
            row = cursor.fetchone()
        return int(row["total"]) if row else 0

    def count_by_session_for_user(self, sid: str, user_uuid: str) -> int:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(1) AS total
                FROM messages AS m
                JOIN sessions AS s ON m.sid = s.sid
                JOIN projects AS p ON s.pid = p.pid
                WHERE m.sid = ? AND p.user_uuid = ?
                """,
                (sid, user_uuid),
            )
            row = cursor.fetchone()
        return int(row["total"]) if row else 0

    def delete_by_id(self, msg_id: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM messages WHERE msg_id = ?", (msg_id,))
            affected = cursor.rowcount
        return affected > 0

    def delete_for_user(self, msg_id: str, user_uuid: str) -> bool:
        with self._cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM messages
                WHERE msg_id = ?
                    AND sid IN (
                        SELECT s.sid
                        FROM sessions AS s
                        JOIN projects AS p ON s.pid = p.pid
                        WHERE p.user_uuid = ?
                    )
                """,
                (msg_id, user_uuid),
            )
            affected = cursor.rowcount
        return affected > 0

    def mark_not_latest_after(self, sid: str, timestamp: float) -> int:
        with self._cursor() as cursor:
            cursor.execute(
                """
                UPDATE messages
                SET is_latest = 0
                WHERE sid = ? AND timestamp > ?
                """,
                (sid, timestamp),
            )
            affected = cursor.rowcount
        return affected

    def get_max_version_for_parent(self, parent_msg_id: str) -> int:
        with self._cursor() as cursor:
            cursor.execute(
                "SELECT MAX(version) AS max_ver FROM messages WHERE parent_msg_id = ?",
                (parent_msg_id,),
            )
            row = cursor.fetchone()
        return int(row["max_ver"]) if row and row["max_ver"] else 0

    def list_versions(self, parent_msg_id: str, user_uuid: str) -> list[dict]:
        with self._cursor() as cursor:
            cursor.execute(
                """
                SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.timestamp, m.parent_msg_id, m.version, m.is_latest, m.created_at
                FROM messages AS m
                JOIN sessions AS s ON m.sid = s.sid
                JOIN projects AS p ON s.pid = p.pid
                WHERE m.parent_msg_id = ? AND p.user_uuid = ?
                ORDER BY m.version ASC
                """,
                (parent_msg_id, user_uuid),
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def switch_version(self, msg_id: str, user_uuid: str) -> bool:
        msg = self.get_for_user(msg_id=msg_id, user_uuid=user_uuid)
        if msg is None:
            return False

        parent_msg_id = msg.get("parent_msg_id")
        if not parent_msg_id:
            return False

        with self._cursor() as cursor:
            cursor.execute(
                "UPDATE messages SET is_latest = 0 WHERE parent_msg_id = ?",
                (parent_msg_id,),
            )
            cursor.execute(
                "UPDATE messages SET is_latest = 1 WHERE msg_id = ?",
                (msg_id,),
            )
            affected = cursor.rowcount
        return affected > 0

    def save_agent_messages(
        self,
        *,
        sid: str,
        user_uuid: str,
        new_messages: list[ModelMessage],
        is_final_turn: bool = False,
        parent_msg_id: str | None = None,
        version: int | None = None,
    ) -> str | None:
        """
        保存 Agent 产生的消息到数据库。
        
        注意：工具调用次数现在通过 Pydantic AI 的 result.usage().tool_calls 获取，
        本函数不再负责计数。
        
        参数：
        - version: 消息版本号。仅在 regenerate 场景（parent_msg_id 非空时）使用
        
        返回值：最终消息的 msg_id（仅在 is_final_turn=True 且有 assistant 消息时有值）
        """
        final_msg_id: str | None = None

        for message in new_messages:
            if isinstance(message, ModelResponse):
                has_tool_call = any(isinstance(part, ToolCallPart) for part in message.parts)
                if has_tool_call:
                    self.create_for_user(
                        sid=sid,
                        user_uuid=user_uuid,
                        kind="tool_call",
                        raw_json=self._serialize_message(message),
                        parent_msg_id=parent_msg_id,
                        version=version,
                    )
                else:
                    if is_final_turn:
                        row = self.create_for_user(
                            sid=sid,
                            user_uuid=user_uuid,
                            kind="assistant",
                            raw_json=self._serialize_message(message),
                            parent_msg_id=parent_msg_id,
                            version=version,
                        )
                        final_msg_id = str(row["msg_id"])
                    else:
                        self.create_for_user(
                            sid=sid,
                            user_uuid=user_uuid,
                            kind="agent_response",
                            raw_json=self._serialize_message(message),
                            parent_msg_id=parent_msg_id,
                            version=version,
                        )
            elif isinstance(message, ModelRequest):
                has_tool_return = any(isinstance(part, ToolReturnPart) for part in message.parts)
                if has_tool_return:
                    self.create_for_user(
                        sid=sid,
                        user_uuid=user_uuid,
                        kind="tool_result",
                        raw_json=self._serialize_message(message),
                        parent_msg_id=parent_msg_id,
                        version=version,
                    )

        return final_msg_id


class AccessFacade(_DataBase):
    """跨领域访问校验聚合。"""

    def validate_project_session(self, *, user_uuid: str, pid: str, sid: str) -> bool:
        project = self._root.projects.get_for_user(pid=pid, user_uuid=user_uuid)
        if project is None:
            return False

        session = self._root.sessions.get_for_user(sid=sid, user_uuid=user_uuid)
        if session is None:
            return False

        return session.get("pid") == pid


class NoncesFacade(_DataBase):
    """
    Nonce 管理（防重放攻击）。
    """

    def is_nonce_used(self, nonce: str) -> bool:
        """检查 nonce 是否已被使用"""
        with self._cursor() as cursor:
            cursor.execute("SELECT 1 FROM nonces WHERE nonce = ?", (nonce,))
            row = cursor.fetchone()
        return row is not None

    def use_nonce(self, nonce: str, user_uuid: str, timestamp: float) -> bool:
        """记录并使用 nonce"""
        created_at = self._now_timestamp()
        try:
            with self._cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO nonces (nonce, user_uuid, timestamp, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (nonce, user_uuid, timestamp, created_at),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def clean_old_nonces(self, before_timestamp: float) -> int:
        """从数据库中删除过期的 nonce"""
        with self._cursor() as cursor:
            cursor.execute("DELETE FROM nonces WHERE timestamp < ?", (before_timestamp,))
            affected = cursor.rowcount
        return affected


class DatabaseFacade:
    """数据库门面对象：统一提供 users/projects/sessions/messages/access/nonces 能力。"""

    def __init__(self, db_path: str = "project.db"):
        self.db_path = db_path
        self.users = UsersFacade(self)
        self.projects = ProjectsFacade(self)
        self.sessions = SessionsFacade(self)
        self.messages = MessagesFacade(self)
        self.access = AccessFacade(self)
        self.nonces = NoncesFacade(self)

    @staticmethod
    def _configure_connection(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=OFF;")
        conn.row_factory = sqlite3.Row

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        self._configure_connection(conn)
        return conn

    @contextmanager
    def db_cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _now_timestamp() -> float:
        return datetime.now().timestamp()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return dict(row)

    def setup_database(self) -> None:
        with self.db_cursor() as cursor:
            schema = """
            CREATE TABLE IF NOT EXISTS users (
                uuid TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
                pid TEXT PRIMARY KEY,
                projectname TEXT NOT NULL,
                user_uuid TEXT NOT NULL,
                timestamp REAL NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (user_uuid) REFERENCES users(uuid) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS sessions (
                sid TEXT PRIMARY KEY,
                pid TEXT NOT NULL,
                sessionname TEXT NOT NULL,
                timestamp REAL NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (pid) REFERENCES projects(pid) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS messages (
                msg_id TEXT PRIMARY KEY,
                sid TEXT NOT NULL,
                kind TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                timestamp REAL NOT NULL,
                parent_msg_id TEXT,
                version INTEGER DEFAULT 1,
                is_latest INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                FOREIGN KEY (sid) REFERENCES sessions(sid) ON DELETE CASCADE,
                FOREIGN KEY (parent_msg_id) REFERENCES messages(msg_id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS nonces (
                nonce TEXT PRIMARY KEY,
                user_uuid TEXT NOT NULL,
                timestamp REAL NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (user_uuid) REFERENCES users(uuid) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_nonces_timestamp ON nonces(timestamp);
            """
            cursor.executescript(schema)

        print("Database setup completed.")


if __name__ == "__main__":
    DatabaseFacade().setup_database()

