"""LLM configuration - single source of truth for model and endpoint.

All hardcoded LLM model names and base URLs live here.  Other modules
import these constants instead of embedding their own string literals.
"""
from __future__ import annotations

from engine.env import get_env

DEFAULT_LLM_MODEL: str = get_env(
    "VERITAS_LLM_MODEL", required=False, default="dashscope/qwen3.7-plus"
)
DEFAULT_LLM_BASE_URL: str = get_env(
    "VERITAS_LLM_BASE_URL",
    required=False,
    default="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
