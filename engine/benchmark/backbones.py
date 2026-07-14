"""Real AgentFn backbone adapters — turn a text-in / text-out model into the harness AgentFn.

The ablation harness (agent_harness) drives B1/B2 through `AgentFn = prompt -> dict`. A real
LLM returns free TEXT (often wrapped in prose or ```json fences), so this module provides the
robust text->dict layer and wraps a `ModelCall = prompt -> text` into an AgentFn. Malformed
replies degrade to `{}` -> the harness reads that as an 'insufficient' abstention (a real,
measurable bare-agent behaviour), never a crash.

The `model_call` itself is the network boundary and is INJECTED, so this stays pure and testable
and the harness is backbone-agnostic. Wire a real backbone through the runtime layer, e.g.:

    from engine.investigation.opencode_agent import ...        # project LLM agent, or an API client
    def claude_call(prompt: str) -> str: ...                   # -> raw model text (runtime does I/O)
    b1 = make_json_agent(claude_call)                          # a Claude-Code backbone
    codex = make_json_agent(codex_call)                        # a Codex backbone (same protocol)

so the same B1 protocol yields the different competitor backbones the story arc compares.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from engine.benchmark.agent_harness import AgentFn

# The network boundary: a prompt in, raw model text out. Implemented via the runtime layer.
ModelCall = Callable[[str], str]

_FENCE_OPEN = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"\s*```\s*$")


def _first_to_last_brace(s: str) -> str | None:
    start, end = s.find("{"), s.rfind("}")
    return s[start : end + 1] if start != -1 and end > start else None


def extract_json(text: str | None) -> dict[str, Any]:
    """Best-effort parse of a JSON object out of model text. Returns {} if none is recoverable.

    Handles: clean JSON, ```json fenced blocks, and a JSON object embedded in surrounding prose.
    """
    if not text:
        return {}
    stripped = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text.strip()))
    for candidate in (stripped, _first_to_last_brace(stripped)):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def make_json_agent(model_call: ModelCall, *, system: str | None = None) -> AgentFn:
    """Wrap a raw text model into an AgentFn: prepend an optional system preamble, extract JSON."""

    def agent_fn(prompt: str) -> dict[str, Any]:
        full = f"{system}\n\n{prompt}" if system else prompt
        return extract_json(model_call(full))

    return agent_fn
