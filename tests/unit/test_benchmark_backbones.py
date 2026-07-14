"""Unit tests for engine.benchmark.backbones — text->dict extraction + AgentFn wrapping.

The model boundary is stubbed (ModelCall). Covers clean JSON, fenced blocks, prose-wrapped JSON,
values containing '->' and braces, and malformed text degrading to {} (an 'insufficient' abstain).
"""

from __future__ import annotations

from engine.benchmark.agent_harness import run_bare_agent
from engine.benchmark.backbones import extract_json, make_json_agent
from engine.benchmark.metrics import main_table_row
from engine.benchmark.schema import load_annotations
from pathlib import Path

CASE_JSON = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "veritasbench_cases" / "example_case.json"


def test_extract_clean_json():
    assert extract_json('{"verdict": "inconsistent", "confidence": 0.7}') == {"verdict": "inconsistent", "confidence": 0.7}


def test_extract_fenced_json():
    text = '```json\n{"verdict": "consistent"}\n```'
    assert extract_json(text) == {"verdict": "consistent"}


def test_extract_json_in_prose():
    text = 'Sure — here is my audit: {"verdict": "inconsistent", "evidence_span": "L1:a.py:x->t.json:r3"}. Hope that helps!'
    assert extract_json(text)["evidence_span"] == "L1:a.py:x->t.json:r3"


def test_extract_malformed_returns_empty():
    assert extract_json("I think it is inconsistent but I'm not sure.") == {}
    assert extract_json("") == {}
    assert extract_json(None) == {}
    assert extract_json("[1, 2, 3]") == {}   # not an object


def test_make_json_agent_wraps_model_call():
    calls = []

    def model(prompt: str) -> str:
        calls.append(prompt)
        return '{"verdict": "inconsistent", "confidence": 0.8}'

    agent = make_json_agent(model, system="You are an auditor.")
    out = agent("CLAIM: x")
    assert out == {"verdict": "inconsistent", "confidence": 0.8}
    assert calls[0].startswith("You are an auditor.")   # system preamble prepended


def test_json_agent_drives_the_harness_end_to_end():
    # a stubbed backbone that always returns clean-JSON 'insufficient' -> harness abstains all
    agent = make_json_agent(lambda p: "```json\n{\"verdict\": \"insufficient\"}\n```")
    case = load_annotations(CASE_JSON, split="real-test")
    row = main_table_row(run_bare_agent(case, agent))
    assert row["abstention"] == 1.0
