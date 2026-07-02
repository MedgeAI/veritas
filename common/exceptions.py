"""Common exceptions shared across layers.

This module is the single source of truth for exception classes that cross
the engine/runtime boundary.  Engine-specific domain exceptions remain in
``engine.exceptions`` and re-export from here where needed.
"""
from __future__ import annotations


class VeritasError(Exception):
    """Veritas 系统级基类。"""


class ToolExecutionError(VeritasError):
    """Tool subprocess 执行失败。

    Attributes:
        tool_id: 注册在 Tool Registry 中的工具标识。
        exit_code: 进程退出码。None 表示未启动。
        stderr_tail: stderr 尾部（最多 2000 字符）。
        timed_out: 是否因超时终止。
    """

    def __init__(
        self,
        message: str,
        *,
        tool_id: str | None = None,
        exit_code: int | None = None,
        stderr_tail: str = "",
        timed_out: bool = False,
    ):
        self.tool_id = tool_id
        self.exit_code = exit_code
        self.stderr_tail = stderr_tail
        self.timed_out = timed_out
        super().__init__(message)
