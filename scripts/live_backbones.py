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

import os
import sys
import threading
from functools import lru_cache, partial
from pathlib import Path

from openai import OpenAI

from engine.env import load_project_env

AUDITOR_SYSTEM = "You are a rigorous scientific-paper auditor. Respond with JSON only, no prose."

# the team's 6-model evaluation matrix (see build-kit/eval_runner.py --models)
CANONICAL_MODELS = ["qwen3.7-plus", "deepseek-v4-pro", "glm-5.2", "claude-opus-4-8", "gemini-3.1-pro", "gpt-5.5"]

_DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# Hard per-attempt wall-clock cap + retry budget. Root cause we hit: DashScope's hostname resolves
# to a Clash/Karing fake-ip (198.x, a LOCAL proxy hop, not Alibaba) and the proxy's upstream tunnel
# intermittently STALLS — it accepts the local TCP instantly but never returns bytes, so httpx's
# read timeout may not fire and a call hangs indefinitely (observed 49min), wedging the whole
# B1-B5 x N-backbone matrix. So we do NOT trust the HTTP client's own timeout: each attempt runs in
# a daemon thread with a hard join() deadline, and we retry on a FRESH connection (which may route
# through a working tunnel). Healthy calls finish in 4-90s; a stall is cut at the deadline and
# retried, then degrades to '' (abstain) — one dead call costs one claim, never the run.
_CALL_TIMEOUT_S = float(os.environ.get("EVAL_CALL_TIMEOUT_S", "120"))  # per-attempt wall clock
_MAX_RETRIES = int(os.environ.get("EVAL_MAX_RETRIES", "2"))            # our own retries (fresh conn)


def _route(model: str) -> str:
    """qwen / deepseek / glm -> dashscope; everything else -> newapi (matches run-harbor.sh)."""
    return "dashscope" if model.startswith(("qwen", "deepseek", "glm")) else "newapi"


@lru_cache(maxsize=2)
def _client(provider: str) -> OpenAI:
    # SDK timeout is only a secondary reaper for orphaned attempts; max_retries=0 because we own
    # retries at the wall-clock layer (below), so the SDK never silently double-waits under us.
    env = load_project_env(Path("."))
    sdk_timeout = _CALL_TIMEOUT_S + 30
    if provider == "dashscope":
        return OpenAI(api_key=env["DASHSCOPE_API_KEY"], base_url=_DASHSCOPE_BASE,
                      timeout=sdk_timeout, max_retries=0)
    key = env.get("NEWAPI_API_KEY")
    if not key:
        raise RuntimeError("NEWAPI_API_KEY not set (environment or .env)")
    return OpenAI(api_key=key, base_url=env["NEWAPI_BASE_URL"],
                  timeout=sdk_timeout, max_retries=0)


def _run_with_deadline(fn, timeout_s: float):
    """Run fn() in a daemon thread and enforce a hard wall-clock cap independent of the HTTP
    client's own timeout (a fake-ip/flaky proxy can hold a socket open sending nothing). Returns
    (result, error); on deadline, error is TimeoutError and the orphan thread is abandoned — being
    a daemon it never blocks process exit, and its own `box` is discarded so it cannot corrupt a
    later attempt's state."""
    box: dict = {}

    def run():
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001 - surfaced to the caller via the error slot
            box["error"] = e

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        return None, TimeoutError(f"call exceeded {timeout_s:g}s wall-clock")
    return box.get("result"), box.get("error")


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


def model_call(prompt: str, *, model: str, temperature: float = 0.0, max_tokens: int = 2000,
               usage_sink: list | None = None) -> str:
    """One completion via the model's routed provider/endpoint; returns raw text.

    If `usage_sink` is given, append this call's token usage to it — lets a caller record per-run
    token totals + cost for the job manifest (mirrors the MedgeBench jobs' cost accounting).

    Each attempt is hard-capped by a wall-clock deadline and retried on a fresh connection; after
    the retry budget is spent, the call degrades to '' — the harness reads empty text as an
    'insufficient' abstention, so one dead call costs one claim, never the whole matrix. Every
    failed attempt is logged loudly to stderr (Fail-Loud), it just does not crash the run."""
    client = _client(_route(model))

    def _once() -> dict:
        if model.startswith("gpt-5"):
            return {"text": _responses_call(client, model, prompt, max_tokens), "usage": None}
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}],
            temperature=temperature, max_tokens=max_tokens,
        )
        return {"text": resp.choices[0].message.content or "", "usage": getattr(resp, "usage", None)}

    for attempt in range(_MAX_RETRIES + 1):
        result, err = _run_with_deadline(_once, _CALL_TIMEOUT_S)
        if err is None and result is not None:
            if usage_sink is not None:
                u = result["usage"]
                usage_sink.append({
                    "prompt_tokens": getattr(u, "prompt_tokens", None),
                    "completion_tokens": getattr(u, "completion_tokens", None),
                    "total_tokens": getattr(u, "total_tokens", None),
                } if u else {})
            return result["text"]
        tail = "retry" if attempt < _MAX_RETRIES else "abstain"
        print(f"[live_backbones] {model} attempt {attempt + 1}/{_MAX_RETRIES + 1} failed "
              f"({type(err).__name__}: {err}) -> {tail}", file=sys.stderr, flush=True)
    return ""


def make_backbone(model: str, **kw):
    """A ModelCall bound to one model (provider auto-routed) — a single competitor backbone."""
    return partial(model_call, model=model, **kw)
