import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
"""做了最底层"""

def _configure_connection(conn: sqlite3.Connection) -> None:
    """统一连接配置，确保外键和写入策略与建库阶段一致。"""
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=OFF;")
    conn.row_factory = sqlite3.Row


def get_connection(db_path: str = "project.db") -> sqlite3.Connection:
    """创建并返回一个已配置好的数据库连接。"""
    conn = sqlite3.connect(db_path)
    _configure_connection(conn)
    return conn


@contextmanager
def db_cursor(db_path: str = "project.db"):
    """提供事务游标：成功提交，失败回滚。逻辑：try 然后执行with中的语句（相当于暂停本函数内的代码执行），如果成功就执行commit失败就回滚抛出错误，最终都要关闭连接"""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise   
    finally:
        conn.close()


def setup_database(db_path="project.db"):
    """
    初始化数据库，创建用户->项目->会话->消息的表结构
    所有的默认值还有键值约束都交给上层逻辑来处理，数据库只负责存储和关联数据
    注意时间戳需要补充俩个，一个是msg_timestamp用于记录机器浮点数，一个是msg_time记录字符串形式的时间，方便人类阅读
    """
    with db_cursor(db_path) as cursor:

        schema = """
        CREATE TABLE IF NOT EXISTS users (
            uuid TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS projects (
            pid TEXT PRIMARY KEY,
            projectname TEXT NOT NULL,
            user_uuid TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_uuid) REFERENCES users(uuid) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS sessions (
            sid TEXT PRIMARY KEY,
            pid TEXT NOT NULL,
            sessionname TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pid) REFERENCES projects(pid) ON DELETE CASCADE    
        );
        CREATE TABLE IF NOT EXISTS messages (
            msg_id TEXT PRIMARY KEY,
            sid TEXT NOT NULL,
            kind TEXT NOT NULL,
            raw_json TEXT NOT NULL,
            msg_timestamp REAL NOT NULL,
            msg_time TEXT NOT NULL,
            parent_msg_id TEXT,
            version INTEGER DEFAULT 1,
            is_latest INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sid) REFERENCES sessions(sid) ON DELETE CASCADE,
            FOREIGN KEY (parent_msg_id) REFERENCES messages(msg_id) ON DELETE SET NULL
        );
        """
        cursor.executescript(schema)
        print("Database setup completed.")


def _time_pair() -> tuple[float, str]:
    """返回机器可排序时间戳与人类可读时间字符串。"""
    now = datetime.now()
    return now.timestamp(), now.strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """将 sqlite3.Row 转换为普通字典，若输入为 None 则返回 None。"""
    if row is None:
        return None
    return dict(row)


def create_user(username: str, email: str, password_hash: str, db_path: str = "project.db") -> dict:
    """创建用户并返回用户记录。"""
    user_uuid = str(uuid.uuid4())
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO users (uuid, username, email, password_hash)
            VALUES (?, ?, ?, ?)
            """,
            (user_uuid, username, email, password_hash),
        )
    user = get_user_by_uuid(user_uuid, db_path=db_path)
    if user is None:
        raise RuntimeError("User was inserted but could not be loaded.")
    return user


def get_user_by_email(email: str, db_path: str = "project.db") -> dict | None:
    """按邮箱查询用户。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            "SELECT uuid, username, email, password_hash, created_at FROM users WHERE email = ?",
            (email,),
        )
        row = cursor.fetchone()
    return _row_to_dict(row)


def get_user_by_uuid(user_uuid: str, db_path: str = "project.db") -> dict | None:
    """按用户 UUID 查询用户。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            "SELECT uuid, username, email, password_hash, created_at FROM users WHERE uuid = ?",
            (user_uuid,),
        )
        row = cursor.fetchone()
    return _row_to_dict(row)


def create_project(projectname: str, user_uuid: str, db_path: str = "project.db") -> dict:
    """创建项目并返回项目记录。"""
    pid = str(uuid.uuid4())
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO projects (pid, projectname, user_uuid)
            VALUES (?, ?, ?)
            """,
            (pid, projectname, user_uuid),
        )
    project = get_project_by_id(pid, db_path=db_path)
    if project is None:
        raise RuntimeError("Project was inserted but could not be loaded.")
    return project


def list_projects_by_user(user_uuid: str, db_path: str = "project.db") -> list[dict]:
    """返回某个用户的全部项目。返回的是一个列表，每个元素是一个项目的字典,有项目的所有信息"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT pid, projectname, user_uuid, created_at
            FROM projects
            WHERE user_uuid = ?
            ORDER BY created_at DESC
            """,
            (user_uuid,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]
    #


def get_project_by_id(pid: str, db_path: str = "project.db") -> dict | None:
    """按项目 ID 查询项目。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            "SELECT pid, projectname, user_uuid, created_at FROM projects WHERE pid = ?",
            (pid,),
        )
        row = cursor.fetchone()
    return _row_to_dict(row)


def get_project_for_user(pid: str, user_uuid: str, db_path: str = "project.db") -> dict | None:
    """项目所有权检查：只有项目归属用户才能查询到。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT pid, projectname, user_uuid, created_at
            FROM projects
            WHERE pid = ? AND user_uuid = ?
            """,
            (pid, user_uuid),
        )
        row = cursor.fetchone()
    
    return _row_to_dict(row)


def create_session(pid: str, sessionname: str, db_path: str = "project.db") -> dict:
    """在指定项目下创建会话。"""
    sid = str(uuid.uuid4())
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO sessions (sid, pid, sessionname)
            VALUES (?, ?, ?)
            """,
            (sid, pid, sessionname),
        )
    session = get_session_by_id(sid, db_path=db_path)
    if session is None:
        raise RuntimeError("Session was inserted but could not be loaded.")
    return session


def list_sessions_by_project(pid: str, db_path: str = "project.db") -> list[dict]:
    """返回某项目下所有会话。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT sid, pid, sessionname, created_at
            FROM sessions
            WHERE pid = ?
            ORDER BY created_at DESC
            """,
            (pid,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_session_by_id(sid: str, db_path: str = "project.db") -> dict | None:
    """按会话 ID 查询会话。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            "SELECT sid, pid, sessionname, created_at FROM sessions WHERE sid = ?",
            (sid,),
        )
        row = cursor.fetchone()
    return _row_to_dict(row)


def get_session_for_user(sid: str, user_uuid: str, db_path: str = "project.db") -> dict | None:
    """按用户归属查询会话，防止通过 sid 越权读取。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT s.sid, s.pid, s.sessionname, s.created_at
            FROM sessions AS s
            JOIN projects AS p ON s.pid = p.pid
            WHERE s.sid = ? AND p.user_uuid = ?
            """,
            (sid, user_uuid),
        )
        row = cursor.fetchone()
    return _row_to_dict(row)


def list_sessions_by_user(user_uuid: str, db_path: str = "project.db") -> list[dict]:
    """按用户读取其全部会话（跨项目），用于用户维度会话管理。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT s.sid, s.pid, s.sessionname, s.created_at
            FROM sessions AS s
            JOIN projects AS p ON s.pid = p.pid
            WHERE p.user_uuid = ?
            ORDER BY s.created_at DESC
            """,
            (user_uuid,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def create_message(
    sid: str,
    kind: str,
    raw_json: str,
    parent_msg_id: str | None = None,
    version: int = 1,
    is_latest: int = 1,
    db_path: str = "project.db",
) -> dict:
    """创建消息记录，raw_json 存储 Pydantic AI 消息的原始 JSON。"""
    msg_id = str(uuid.uuid4())
    msg_timestamp, msg_time = _time_pair()
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO messages (msg_id, sid, kind, raw_json, msg_timestamp, msg_time, parent_msg_id, version, is_latest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, sid, kind, raw_json, msg_timestamp, msg_time, parent_msg_id, version, is_latest),
        )
    message = get_message_by_id(msg_id, db_path=db_path)
    if message is None:
        raise RuntimeError("Message was inserted but could not be loaded.")
    return message


def create_message_for_user(
    sid: str,
    user_uuid: str,
    kind: str,
    raw_json: str,
    parent_msg_id: str | None = None,
    version: int = 1,
    is_latest: int = 1,
    db_path: str = "project.db",
) -> dict:
    """按用户归属写入消息，只有会话归属该用户时才允许写入。"""
    owned_session = get_session_for_user(sid=sid, user_uuid=user_uuid, db_path=db_path)
    if owned_session is None:
        raise PermissionError("Session does not belong to the current user.")
    return create_message(
        sid=sid,
        kind=kind,
        raw_json=raw_json,
        parent_msg_id=parent_msg_id,
        version=version,
        is_latest=is_latest,
        db_path=db_path,
    )


def get_message_by_id(msg_id: str, db_path: str = "project.db") -> dict | None:
    """按消息 ID 查询消息。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT msg_id, sid, kind, raw_json, msg_timestamp, msg_time, parent_msg_id, version, is_latest, created_at
            FROM messages
            WHERE msg_id = ?
            """,
            (msg_id,),
        )
        row = cursor.fetchone()
    return _row_to_dict(row)


def get_message_for_user(msg_id: str, user_uuid: str, db_path: str = "project.db") -> dict | None:
    """按用户归属查询消息，防止通过 msg_id 越权读取。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.msg_timestamp, m.msg_time, m.parent_msg_id, m.version, m.is_latest, m.created_at
            FROM messages AS m
            JOIN sessions AS s ON m.sid = s.sid
            JOIN projects AS p ON s.pid = p.pid
            WHERE m.msg_id = ? AND p.user_uuid = ?
            """,
            (msg_id, user_uuid),
        )
        row = cursor.fetchone()
    return _row_to_dict(row)


def list_messages_by_session(
    sid: str,
    db_path: str = "project.db",
) -> list[dict]:
    """按会话读取全部消息，按时间正序返回，适合直接重放上下文。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT msg_id, sid, kind, raw_json, msg_timestamp, msg_time, parent_msg_id, version, is_latest, created_at
            FROM messages
            WHERE sid = ?
            ORDER BY msg_timestamp ASC
            """,
            (sid,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def list_messages_by_session_for_user(
    sid: str,
    user_uuid: str,
    db_path: str = "project.db",
) -> list[dict]:
    """按用户归属读取会话全部消息，适合安全上下文加载。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.msg_timestamp, m.msg_time, m.parent_msg_id, m.version, m.is_latest, m.created_at
            FROM messages AS m
            JOIN sessions AS s ON m.sid = s.sid
            JOIN projects AS p ON s.pid = p.pid
            WHERE m.sid = ? AND p.user_uuid = ?
            ORDER BY m.msg_timestamp ASC
            """,
            (sid, user_uuid),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def list_latest_messages_by_session_for_user(
    sid: str,
    user_uuid: str,
    db_path: str = "project.db",
) -> list[dict]:
    """按用户归属读取会话中 is_latest=1 的消息，用于构建 AI 对话历史。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.msg_timestamp, m.msg_time, m.parent_msg_id, m.version, m.is_latest, m.created_at
            FROM messages AS m
            JOIN sessions AS s ON m.sid = s.sid
            JOIN projects AS p ON s.pid = p.pid
            WHERE m.sid = ? AND p.user_uuid = ? AND m.is_latest = 1
            ORDER BY m.msg_timestamp ASC
            """,
            (sid, user_uuid),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def list_messages_by_session_page(
    sid: str,
    limit: int = 20,
    offset: int = 0,
    db_path: str = "project.db",
) -> list[dict]:
    """按会话分页读取消息，主要用于客户端分页展示。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT msg_id, sid, kind, raw_json, msg_timestamp, msg_time, parent_msg_id, version, is_latest, created_at
            FROM messages
            WHERE sid = ?
            ORDER BY msg_timestamp ASC
            LIMIT ? OFFSET ?
            """,
            (sid, limit, offset),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def list_messages_by_session_page_for_user(
    sid: str,
    user_uuid: str,
    limit: int = 20,
    offset: int = 0,
    db_path: str = "project.db",
) -> list[dict]:
    """按用户归属分页读取会话消息，适合客户端安全分页展示。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.msg_timestamp, m.msg_time, m.parent_msg_id, m.version, m.is_latest, m.created_at
            FROM messages AS m
            JOIN sessions AS s ON m.sid = s.sid
            JOIN projects AS p ON s.pid = p.pid
            WHERE m.sid = ? AND p.user_uuid = ?
            ORDER BY m.msg_timestamp ASC
            LIMIT ? OFFSET ?
            """,
            (sid, user_uuid, limit, offset),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def count_messages_by_session(sid: str, db_path: str = "project.db") -> int:
    """统计会话消息数量，供分页接口返回总数。"""
    with db_cursor(db_path) as cursor:
        cursor.execute("SELECT COUNT(1) AS total FROM messages WHERE sid = ?", (sid,))
        row = cursor.fetchone()
    return int(row["total"]) if row else 0


def count_messages_by_session_for_user(sid: str, user_uuid: str, db_path: str = "project.db") -> int:
    """按用户归属统计会话消息数量，供安全分页接口返回总数。"""
    with db_cursor(db_path) as cursor:
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


def delete_project_for_user(pid: str, user_uuid: str, db_path: str = "project.db") -> bool:
    """按项目归属删除项目，删除成功返回 True。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            "DELETE FROM projects WHERE pid = ? AND user_uuid = ?",
            (pid, user_uuid),
        )
        affected = cursor.rowcount
    return affected > 0


# ============================================================
# 消息版本管理
# ============================================================


def mark_messages_not_latest_after(
    sid: str,
    msg_timestamp: float,
    db_path: str = "project.db",
) -> int:
    """将某消息时间戳之后的所有消息标记为非最新（is_latest=0），用于 regenerate 前清理。返回受影响行数。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            UPDATE messages
            SET is_latest = 0
            WHERE sid = ? AND msg_timestamp > ?
            """,
            (sid, msg_timestamp),
        )
        affected = cursor.rowcount
    return affected


def get_max_version_for_parent(parent_msg_id: str, db_path: str = "project.db") -> int:
    """查询某个 parent_msg_id 下的最大版本号，用于新版本号计算。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            "SELECT MAX(version) AS max_ver FROM messages WHERE parent_msg_id = ?",
            (parent_msg_id,),
        )
        row = cursor.fetchone()
    return int(row["max_ver"]) if row and row["max_ver"] else 0


def list_message_versions(
    parent_msg_id: str,
    user_uuid: str,
    db_path: str = "project.db",
) -> list[dict]:
    """按 parent_msg_id 查询该用户消息的所有版本（可切换展示）。"""
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            SELECT m.msg_id, m.sid, m.kind, m.raw_json, m.msg_timestamp, m.msg_time, m.parent_msg_id, m.version, m.is_latest, m.created_at
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


def switch_message_version(
    msg_id: str,
    user_uuid: str,
    db_path: str = "project.db",
) -> bool:
    """切换某消息为最新版本：先将同 parent 的所有版本设为非最新，再将目标设为最新。"""
    # 先获取消息信息
    msg = get_message_for_user(msg_id=msg_id, user_uuid=user_uuid, db_path=db_path)
    if msg is None:
        return False

    parent_msg_id = msg.get("parent_msg_id")
    if not parent_msg_id:
        return False  # 没有 parent 的消息不支持版本切换

    with db_cursor(db_path) as cursor:
        # 将同 parent 的所有版本设为非最新
        cursor.execute(
            "UPDATE messages SET is_latest = 0 WHERE parent_msg_id = ?",
            (parent_msg_id,),
        )
        # 将目标消息设为最新
        cursor.execute(
            "UPDATE messages SET is_latest = 1 WHERE msg_id = ?",
            (msg_id,),
        )
        affected = cursor.rowcount
    return affected > 0


def delete_session_by_id(sid: str, db_path: str = "project.db") -> bool:
    """删除会话，删除成功返回 True。"""
    with db_cursor(db_path) as cursor:
        cursor.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
        affected = cursor.rowcount
    return affected > 0


def delete_session_for_user(sid: str, user_uuid: str, db_path: str = "project.db") -> bool:
    """按用户归属删除会话，防止通过 sid 越权删除。"""
    with db_cursor(db_path) as cursor:
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


def delete_message_by_id(msg_id: str, db_path: str = "project.db") -> bool:
    """删除单条消息，删除成功返回 True。"""
    with db_cursor(db_path) as cursor:
        cursor.execute("DELETE FROM messages WHERE msg_id = ?", (msg_id,))
        affected = cursor.rowcount
    return affected > 0


def delete_message_for_user(msg_id: str, user_uuid: str, db_path: str = "project.db") -> bool:
        """按用户归属删除消息，防止通过 msg_id 越权删除。"""
        with db_cursor(db_path) as cursor:
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


def delete_user_by_uuid(user_uuid: str, db_path: str = "project.db") -> bool:
    """删除用户，删除成功返回 True。会触发项目/会话/消息级联删除。"""
    with db_cursor(db_path) as cursor:
        cursor.execute("DELETE FROM users WHERE uuid = ?", (user_uuid,))
        affected = cursor.rowcount
    return affected > 0

if __name__ == "__main__":
    """直接运行这个文件会执行数据库初始化，创建必要的表结构。后续可以在这里添加一些测试数据插入逻辑，方便开发初期使用。"""
    setup_database()

