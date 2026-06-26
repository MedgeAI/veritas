"""Real behavior tests for extract_json (no mocks).

extract_json is a data transformation function; per AGENTS.md it must not
be mocked. These tests exercise the real parsing logic across the input
shapes the agent runtime actually encounters.
"""

from __future__ import annotations

import pytest

from engine.investigation.validators import extract_json


# ---------------------------------------------------------------------------
# 1. Clean JSON object
# ---------------------------------------------------------------------------


def test_valid_json() -> None:
    raw = '{"schema_version": "1.0", "claim": "test", "score": 42}'
    result = extract_json(raw)
    assert result == {"schema_version": "1.0", "claim": "test", "score": 42}


# ---------------------------------------------------------------------------
# 2. JSON wrapped in a markdown fence
# ---------------------------------------------------------------------------


def test_json_with_markdown_fence() -> None:
    raw = (
        "Here is the result:\n"
        "```json\n"
        '{"schema_version": "1.0", "items": [1, 2, 3]}\n'
        "```\n"
        "Done."
    )
    result = extract_json(raw)
    assert result == {"schema_version": "1.0", "items": [1, 2, 3]}


def test_json_with_plain_code_fence() -> None:
    raw = (
        "```\n"
        '{"status": "ok"}\n'
        "```"
    )
    result = extract_json(raw)
    assert result == {"status": "ok"}


# ---------------------------------------------------------------------------
# 3. Truncated / incomplete JSON — should raise, not silently return garbage
# ---------------------------------------------------------------------------


def test_truncated_json_raises() -> None:
    raw = '{"schema_version": "1.0", "claim": "tes'
    with pytest.raises(ValueError, match="no JSON object found"):
        extract_json(raw)


# ---------------------------------------------------------------------------
# 4. Deeply nested JSON
# ---------------------------------------------------------------------------


def test_nested_json() -> None:
    raw = '{"a": {"b": {"c": {"d": [1, 2, {"e": true}]}}}}'
    result = extract_json(raw)
    assert result["a"]["b"]["c"]["d"][2]["e"] is True


# ---------------------------------------------------------------------------
# 5. Empty / whitespace / None-like inputs
# ---------------------------------------------------------------------------


def test_empty_string_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        extract_json("")


def test_whitespace_only_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        extract_json("   \n\t  ")


# ---------------------------------------------------------------------------
# 6. JSON embedded in natural language text (not fenced)
# ---------------------------------------------------------------------------


def test_mixed_content_extracts_json_object() -> None:
    raw = (
        "The analysis found the following result:\n"
        '{"schema_version": "1.0", "verdict": "needs_review"}\n'
        "This suggests further investigation is warranted."
    )
    result = extract_json(raw)
    assert result["verdict"] == "needs_review"


# ---------------------------------------------------------------------------
# 7. JSONL text-event envelope (opencode wire format)
# ---------------------------------------------------------------------------


def test_jsonl_text_event_envelope() -> None:
    inner = '{"schema_version": "1.0", "claim": "from_event"}'
    raw = (
        '{"type":"text","part":{"text":"' + inner.replace('"', '\\"') + '"}}'
    )
    result = extract_json(raw)
    assert result["claim"] == "from_event"


# ---------------------------------------------------------------------------
# 8. Multiple JSON objects — should return the largest (heuristic)
# ---------------------------------------------------------------------------


def test_multiple_json_objects_returns_largest() -> None:
    raw = (
        'Brief: {"small": 1}\n'
        'Full result: {"schema_version": "1.0", "claims": ["a", "b"], "score": 99}'
    )
    result = extract_json(raw)
    assert result["schema_version"] == "1.0"
    assert len(result["claims"]) == 2


# ---------------------------------------------------------------------------
# 9. JSON array at top level — first object extracted by candidate heuristic
# ---------------------------------------------------------------------------


def test_top_level_array_extracts_first_object() -> None:
    """_json_object_candidates finds {} blocks even inside a top-level array."""
    raw = '[{"a": 1}, {"b": 2}]'
    result = extract_json(raw)
    assert result == {"a": 1}
