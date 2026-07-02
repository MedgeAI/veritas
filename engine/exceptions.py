"""Veritas 异常层次结构。

所有领域异常继承 VeritasError，调用方可以按粒度捕获。

跨层共享的异常（VeritasError, ToolExecutionError）定义在
``common.exceptions``，本模块 re-export 以保持向后兼容。
"""
from __future__ import annotations

from common.exceptions import ToolExecutionError, VeritasError

__all__ = [
    "VeritasError",
    "ConfigError",
    "ToolExecutionError",
    "PipelineError",
    "EarlyTerminationError",
    "StageTimeoutError",
    "AgentError",
    "DataIntegrityError",
]


class ConfigError(VeritasError):
    """配置/环境变量缺失或无效。"""

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
