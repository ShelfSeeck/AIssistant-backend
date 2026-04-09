from dataclasses import dataclass, field
from typing import Any, NoReturn
from fastapi import status, HTTPException
from pydantic import BaseModel

class ApiError(BaseModel):
    """API 错误响应体"""
    code: str
    message: str
    request_id: str
    retry_of_request_id: str | None = None
    retryable: bool
    detail: dict[str, Any] | None = None

@dataclass
class ToolCheck:
    """
    状态管理与工具用量校验模块。
    封装了工具调用计数、FORCE 模式校验以及循环次数限制。
    """
    max_tool_loops: int
    request_id: str
    retry_of_request_id: str | None = None
    
    total_tool_calls: int = 0
    orchestration_round: int = 0
    saw_tool_call: bool = False

    def _err(
        self,
        status_code: int,
        code: str,
        message: str,
        retryable: bool,
        detail: dict[str, Any] | None = None,
    ) -> NoReturn:
        """内部错误抛出捷径"""
        payload = ApiError(
            code=code,
            message=message,
            request_id=self.request_id,
            retry_of_request_id=self.retry_of_request_id,
            retryable=retryable,
            detail=detail,
        ).model_dump(exclude_none=True)
        raise HTTPException(status_code=status_code, detail=payload)

    def is_quota_exceeded(self) -> bool:
        """检查工具调用配额是否已用尽"""
        return self.total_tool_calls >= self.max_tool_loops

    def update_usage(self, calls_in_run: int, is_final: bool):
        """更新用量状态"""
        self.total_tool_calls += calls_in_run
        if calls_in_run > 0:
            self.saw_tool_call = True
        
        # 内部 orchestration_round 仍然用于防止逻辑死循环（例如 AI 始终不叫工具但也不结束）
        if not is_final:
            self.orchestration_round += 1
            if self.orchestration_round > self.max_tool_loops * 2: # 逻辑循环上限给宽一点，主要靠 tool_calls 限制
                self._err(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="ORCHESTRATION_LIMIT_EXCEEDED",
                    message="Orchestration loop limit exceeded",
                    retryable=True,
                )

    def should_force_continue(self, tool_mode: str) -> bool:
        """验证 FORCE 模式下是否需要强制继续"""
        from loop import ToolMode  # 延迟导入防止循环依赖
        if tool_mode == ToolMode.FORCE and not self.saw_tool_call:
            self.orchestration_round += 1
            if self.orchestration_round > self.max_tool_loops:
                self._err(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    code="TOOL_LOOP_LIMIT_EXCEEDED",
                    message="Tool loop limit exceeded",
                    retryable=True,
                )
            return True
        return False

    @property
    def remaining_calls(self) -> int:
        """返回剩余可用调用次数"""
        return max(self.max_tool_loops - self.total_tool_calls, 0)
