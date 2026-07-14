"""Live model backbones aligned to the MedgeBench eval matrix (network I/O, tooling layer).

Model set + routing mirror build-kit/eval_runner.py + run-harbor.sh on the server (the models the
team actually evaluates), NOT ad-hoc picks. Keys read from .env (never hard-coded/logged).

Routing (run-harbor.sh: qwen|deepseek -> DashScope, else -> NewAPI; glm -> DashScope per w_gd):
  dashscope : qwen3.7-plus, deepseek-v4-pro, glm-5.2   (OpenAI-compatible chat/completions)
  newapi    : claude-opus-4-8, gemini-3.1-pro         (chat/completions)
              gpt-5.5                                  (Responses API, streamed — codex channel)

Reasoning models (glm-5.2, deepseek, gpt-5.5) spend tokens thinking, so max_tokens defaults high.

    from engine.benchmark.backbones import make_json_agent
    from scripts.live_backbones import CANONICAL_MODELS, make_backbone, AUDITOR_SYSTEM
    agents = {m: make_json_agent(make_backbone(m), system=AUDITOR_SYSTEM) for m in CANONICAL_MODELS}
"""

from __future__ import annotations

from functools import lru_cache, partial
from pathlib import Path

from openai import OpenAI

from engine.env import load_project_env

AUDITOR_SYSTEM = "You are a rigorous scientific-paper auditor. Respond with JSON only, no prose."

# the team's 6-model evaluation matrix (see build-kit/eval_runner.py --models)
CANONICAL_MODELS = ["qwen3.7-plus", "deepseek-v4-pro", "glm-5.2", "claude-opus-4-8", "gemini-3.1-pro", "gpt-5.5"]

_DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _route(model: str) -> str:
    """qwen / deepseek / glm -> dashscope; everything else -> newapi (matches run-harbor.sh)."""
    return "dashscope" if model.startswith(("qwen", "deepseek", "glm")) else "newapi"


@lru_cache(maxsize=2)
def _client(provider: str) -> OpenAI:
    env = load_project_env(Path("."))
    if provider == "dashscope":
        return OpenAI(api_key=env["DASHSCOPE_API_KEY"], base_url=_DASHSCOPE_BASE)
    key = env.get("NEWAPI_API_KEY")
    if not key:
        raise RuntimeError("NEWAPI_API_KEY not set (environment or .env)")
    return OpenAI(api_key=key, base_url=env["NEWAPI_BASE_URL"])


def _responses_call(client: OpenAI, model: str, prompt: str, max_tokens: int) -> str:
    """gpt-5.x codex channel: Responses API, streamed (chat/completions is rejected there)."""
    chunks: list[str] = []
    for event in client.responses.create(
        model=model, input=[{"role": "user", "content": prompt}],
        max_output_tokens=max_tokens, stream=True,
    ):
        delta = getattr(event, "delta", None)
        if isinstance(delta, str):
            chunks.append(delta)
    return "".join(chunks)


def model_call(prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 2000) -> str:
    """One completion via the model's routed provider/endpoint; returns raw text."""
    client = _client(_route(model))
    if model.startswith("gpt-5"):
        return _responses_call(client, model, prompt, max_tokens)
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=temperature, max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def make_backbone(model: str, **kw):
    """A ModelCall bound to one model (provider auto-routed) — a single competitor backbone."""
    return partial(model_call, model=model, **kw)
