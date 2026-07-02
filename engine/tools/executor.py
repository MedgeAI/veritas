"""Engine-side facade for accessing Runtime executors.

This is the ONLY allowed path for Engine to access Runtime execution.
Do not import directly from runtime.executors in other Engine modules.
"""
from runtime.executors.base import ExecutionRequest
from runtime.executors.subprocess_executor import execute_subprocess

__all__ = ["ExecutionRequest", "execute_subprocess"]
