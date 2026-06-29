"""Follow-up question generator: abstract interface and concrete implementations.

Two implementations are provided:
- ``TemplateFollowUpGenerator``: deterministic fallback using category templates.
  Always available, no external dependencies.
- ``LLMFollowUpGenerator``: calls an LLM to generate context-aware questions.
  Falls back to templates on failure.

The factory ``create_follow_up_generator`` selects the implementation based on
the availability of an LLM client in the app dependencies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from .templates import generate_fallback_questions

log = logging.getLogger(__name__)


class FollowUpGenerator(ABC):
    """Abstract interface for generating follow-up questions from a finding."""

    @abstractmethod
    async def generate(self, finding: dict) -> list[str]:
        """Generate 1-2 follow-up questions for a finding.

        Args:
            finding: A finding dict from the static audit bundle.

        Returns:
            A list of question strings (1-2 items).
        """


class TemplateFollowUpGenerator(FollowUpGenerator):
    """Deterministic fallback: uses category-specific templates."""

    name = "template"

    async def generate(self, finding: dict) -> list[str]:
        return generate_fallback_questions(finding)


class LLMFollowUpGenerator(FollowUpGenerator):
    """Calls an LLM to generate context-aware follow-up questions.

    Falls back to template-based generation on any failure (LLM error,
    parse error, timeout, etc.).
    """

    def __init__(self, llm_client: Any) -> None:
        self.llm_client = llm_client
        self.name = "llm"

    async def generate(self, finding: dict) -> list[str]:
        from .prompts import build_follow_up_prompt

        prompt = build_follow_up_prompt(finding)
        try:
            # Run blocking LLM call in a thread to avoid blocking the event loop
            response = await asyncio.to_thread(
                self.llm_client.chat,
                model="qwen-plus",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            content = getattr(response, "content", None) or str(response)
            result = json.loads(content)
            questions = result.get("questions", [])
            if questions and all(isinstance(q, str) for q in questions):
                return questions[:2]
        except Exception:  # Deliberately broad: LLM client can raise VeritasLLMParseError, network errors, etc.; always fall back to template
            log.debug(
                "LLM follow-up generation failed for %s, falling back to template",
                finding.get("finding_id", "?"),
                exc_info=True,
            )
        # Fallback to template on any failure
        return generate_fallback_questions(finding)


def create_follow_up_generator(deps: Any) -> FollowUpGenerator:
    """Factory: choose implementation based on available infrastructure.

    Args:
        deps: AppDependencies instance. If it has an available ``llm_client``,
              the LLM generator is returned; otherwise the template generator.
    """
    llm_client = getattr(deps, "llm_client", None)
    if llm_client is not None and getattr(llm_client, "is_available", lambda: False)():
        return LLMFollowUpGenerator(llm_client)
    return TemplateFollowUpGenerator()
