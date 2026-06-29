"""Veritas 异常层次结构。

所有领域异常继承 VeritasError，调用方可以按粒度捕获。
"""
from __future__ import annotations


class VeritasError(Exception):
    """Veritas 系统级基类。"""


class ConfigError(VeritasError):
    """配置/环境变量缺失或无效。"""


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


class PipelineError(VeritasError):
    """流水线编排级失败。"""

    def __init__(
        self,
        message: str,
        *,
        failed_step: str | None = None,
        cause: Exception | None = None,
    ):
        self.failed_step = failed_step
        if cause is not None:
            self.__cause__ = cause
        super().__init__(message)


class EarlyTerminationError(PipelineError):
    """关键上游依赖失败（如 MinerU），流水线不可继续。"""


class StageTimeoutError(PipelineError):
    """阶段执行超时。"""


class AgentError(VeritasError):
    """Agent 执行失败。

    Attributes:
        category: 错误分类（timeout / parse / execution / validation）。
        trace_id: Agent trace 标识，用于关联日志。
    """

    def __init__(
        self,
        message: str,
        *,
        category: str | None = None,
        trace_id: str | None = None,
    ):
        self.category = category
        self.trace_id = trace_id
        super().__init__(message)


class DataIntegrityError(VeritasError):
    """数据不一致（ORM / 文件系统 / schema 漂移）。"""
