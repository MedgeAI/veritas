"""Veritas LLM client for DashScope/OpenAI-compatible APIs."""

from __future__ import annotations

import json
import re


class VeritasLLMParseError(Exception):
    """Raised when LLM response cannot be parsed as JSON."""

    pass


class VeritasLLMClient:
    """LLM client using DashScope OpenAI-compatible API.

    Reads DASHSCOPE_API_KEY from engine.env.get_env (fail-loud if missing).
    """

    def __init__(self) -> None:
        from engine.env import get_env

        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai package not installed. Install with: uv add openai"
            ) from e

        api_key = get_env("DASHSCOPE_API_KEY")
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    def chat(
        self,
        prompt: str,
        model: str = "qwen3.7-plus",
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        """Send a chat completion request and return the text response.

        Network/timeout exceptions are propagated (not swallowed).
        """
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def chat_json(self, prompt: str, **kwargs) -> dict:
        """Send a chat request and parse the response as JSON.

        Strips markdown code fences (```json ... ```) before parsing,
        since LLMs commonly wrap JSON responses in fenced blocks.

        Raises VeritasLLMParseError if the response is not valid JSON.
        """
        text = self.chat(prompt, **kwargs)
        # Strip markdown code fences: ```json ... ``` or ``` ... ```
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.MULTILINE)
        stripped = re.sub(r"\n?```\s*$", "", stripped, flags=re.MULTILINE)
        stripped = stripped.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as e:
            raise VeritasLLMParseError(
                f"Failed to parse JSON from LLM response: {text[:200]!r}"
            ) from e
