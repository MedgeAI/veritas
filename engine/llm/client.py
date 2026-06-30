"""Veritas LLM client for DashScope with litellm cost tracking."""

from __future__ import annotations

import json
import logging
import re


from engine.exceptions import VeritasError

logger = logging.getLogger(__name__)


class VeritasLLMParseError(VeritasError):
    """Raised when LLM response cannot be parsed as JSON."""

    pass


class VeritasLLMClient:
    """LLM client using OpenAI SDK for DashScope with litellm cost tracking.

    Uses OpenAI SDK (with proxy bypass) for API calls, and litellm for:
    - Cost calculation from token usage
    - Model pricing database

    This hybrid approach avoids litellm's proxy compatibility issues while
    still leveraging its mature cost tracking infrastructure.
    """

    def __init__(self) -> None:
        from engine.env import get_env

        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai package not installed. Install with: uv add openai"
            ) from e

        try:
            import litellm
            self.litellm = litellm
        except ImportError:
            logger.warning("litellm not installed, cost tracking disabled")
            self.litellm = None

        api_key = get_env("DASHSCOPE_API_KEY")

        # Register custom pricing for models not in litellm's default registry
        if self.litellm:
            self.litellm.register_model({
                "dashscope/qwen3.7-plus": {
                    "max_tokens": 8192,
                    "input_cost_per_token": 0.000004,   # ¥0.004/1K tokens
                    "output_cost_per_token": 0.000012,  # ¥0.012/1K tokens
                    "litellm_provider": "dashscope"
                }
            })

        # Bypass system proxy env vars (ALL_PROXY/HTTPS_PROXY etc.) to avoid
        # "Unknown scheme for proxy URL" errors with unsupported schemes like
        # socks5h://. LLM API calls should go direct.
        import httpx

        http_client = httpx.Client(trust_env=False)

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            http_client=http_client,
        )

    def chat(
        self,
        prompt: str,
        model: str = "qwen3.7-plus",
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        """Send a chat completion request and return the text response.

        Token usage is logged, and cost is calculated via litellm if available.
        Network/timeout exceptions are propagated (not swallowed).
        """
        response = self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content or ""

        # Extract and log token usage + cost
        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            prompt_tokens = getattr(usage, "prompt_tokens", 0)
            completion_tokens = getattr(usage, "completion_tokens", 0)
            total_tokens = getattr(usage, "total_tokens", prompt_tokens + completion_tokens)

            # Calculate cost using litellm if available
            cost = None
            if self.litellm:
                try:
                    cost = self.litellm.completion_cost(
                        completion_response=response,
                        model=f"dashscope/{model}",
                    )
                except Exception as e:
                    logger.debug(f"Cost calculation failed: {e}")

            logger.info(
                "LLM call: model=%s prompt_tokens=%d completion_tokens=%d total_tokens=%d cost=%s",
                model,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                f"${cost:.6f}" if cost is not None else "N/A",
            )

        return content

    def chat_json(self, prompt: str, max_tokens: int = 8192, **kwargs) -> dict:
        """Send a chat request and parse the response as JSON.

        Strips markdown code fences (```json ... ```) before parsing,
        since LLMs commonly wrap JSON responses in fenced blocks.

        Raises VeritasLLMParseError if the response is not valid JSON.
        """
        text = self.chat(prompt, max_tokens=max_tokens, **kwargs)
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
