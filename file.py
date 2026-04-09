import shutil
from pathlib import Path
from typing import Union, List, Dict, Optional


class FileError(Exception):
    """文件操作基本错误类"""
    pass

class FileBase:
    """
    文件系统 Facade 基类。
    所有操作限制在 self.base_path 之下。
    """
    def __init__(self, base_path: Union[str, Path]):
        self.base_path = Path(base_path).resolve()
        if not self.base_path.exists():
            self.base_path.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative_path: str) -> Path:
        """安全路径转换，防止路径穿越攻击。"""
        # 移除开头的斜杠或反斜杠，确保是相对路径
        clean_rel = relative_path.lstrip("/\\")
        target_path = (self.base_path / clean_rel).resolve()
        
        if not str(target_path).startswith(str(self.base_path)):
            raise FileError(f"Access denied: Path {relative_path} is outside base directory.")
        return target_path

    def create_file(self, path: str, content: str = "") -> str:
        """创建文件或覆盖已有文件。"""
        try:
            target = self._safe_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return f"File created: {path}"
        except Exception as e:
            raise FileError(f"Failed to create file {path}: {e}")

    def delete_file(self, path: str) -> str:
        """删除指定路径的文件。"""
        try:
            target = self._safe_path(path)
            if target.is_file():
                target.unlink()
                return f"File deleted: {path}"
            raise FileError(f"Path is not a file: {path}")
        except Exception as e:
            raise FileError(f"Failed to delete file {path}: {e}")

    def create_dir(self, path: str) -> str:
        """创建文件夹（递归）。"""
        try:
            target = self._safe_path(path)
            target.mkdir(parents=True, exist_ok=True)
            return f"Directory created: {path}"
        except Exception as e:
            raise FileError(f"Failed to create directory {path}: {e}")

    def delete_dir(self, path: str) -> str:
        """递归删除文件夹。"""
        try:
            target = self._safe_path(path)
            if target.is_dir():
                shutil.rmtree(target)
                return f"Directory deleted: {path}"
            raise FileError(f"Path is not a directory: {path}")
        except Exception as e:
            raise FileError(f"Failed to delete directory {path}: {e}")

    def read_file(self, path: str) -> str:
        """读取文件内容。"""
        try:
            target = self._safe_path(path)
            if not target.is_file():
                raise FileError(f"File not found: {path}")
            return target.read_text(encoding="utf-8")
        except Exception as e:
            raise FileError(f"Failed to read file {path}: {e}")

    def search_dir(self, path: str = ".") -> List[Dict[str, Union[str, bool]]]:
        """搜索目录下文件和文件夹结构。"""
        try:
            target = self._safe_path(path)
            if not target.is_dir():
                raise FileError(f"Directory not found: {path}")
            
            results = []
            for item in target.iterdir():
                results.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "rel_path": str(item.relative_to(self.base_path))
                })
            return results
        except Exception as e:
            raise FileError(f"Failed to search directory {path}: {e}")

class ProjectFile(FileBase):
    """
    项目文件子类，限制在 /projects/{pid}。
    """
    def __init__(self, pid: str, user_uuid: str, db_facade):
        # 鉴权：检查该项目是否属于该用户
        project = db_facade.projects.get_for_user(pid=pid, user_uuid=user_uuid)
        if not project:
            raise PermissionError(f"Access Denied: Project {pid} does not belong to user {user_uuid}")
        
        # 确定物理路径
        root_dir = Path(__file__).parent.resolve()
        project_path = root_dir / "projects" / pid
        super().__init__(project_path)

class UserFile(FileBase):
    """
    用户文件子类，限制在 /users/{user_uuid}。
    """
    def __init__(self, user_uuid: str, db_facade):
        # 鉴权：简单检查用户是否存在（或由 auth 层已完成的核心校验）
        user = db_facade.users.get_by_uuid(user_uuid)
        if not user:
            raise PermissionError(f"Access Denied: User {user_uuid} not found")
        
        # 确定物理路径
        root_dir = Path(__file__).parent.resolve()
        user_path = root_dir / "users" / user_uuid
        super().__init__(user_path)

def filesystem_tool_handler(
    ctx, 
    method: str, 
    args: dict, 
    pid: Optional[str] = None, 
    user_uuid: Optional[str] = None
) -> dict:
    """
    通用文件系统工具处理器，供 tool.py 引用。
    根据参数决定是 ProjectFile 还是 UserFile。
    """
    try:
        from db import DatabaseFacade
        from config import DATABASE_PATH
        db = DatabaseFacade(DATABASE_PATH)

        if pid:
            if not user_uuid:
                return {"error": "user_uuid_required_for_project_access"}
            fs = ProjectFile(pid=pid, user_uuid=user_uuid, db_facade=db)
        elif user_uuid:
            fs = UserFile(user_uuid=user_uuid, db_facade=db)
        else:
            return {"error": "identity_context_missing"}

        # 调用方法映射
        func = getattr(fs, method, None)
        if not func or method.startswith("_"):
            return {"error": f"invalid_method: {method}"}
        
        result = func(**args)
        return {"status": "success", "result": result}

    except PermissionError as e:
        return {"status": "error", "error": "permission_denied", "message": str(e)}
    except FileError as e:
        return {"status": "error", "error": "file_operation_failed", "message": str(e)}
    except Exception as e:
        return {"status": "error", "error": "internal_error", "message": str(e)}
