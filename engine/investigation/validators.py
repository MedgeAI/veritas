from __future__ import annotations

import json
import re
from typing import Any

from engine.tools.registry import SOURCE_DATA_FINDINGS_DEFAULT_PARAMS

DEFAULT_SOURCE_FINDING_PARAMS = SOURCE_DATA_FINDINGS_DEFAULT_PARAMS

# DEPRECATED: ALLOWED_STEPS is no longer used by active code.
# Agent tool准入 now comes from engine.tools.registry.TOOLS and
# tool_catalog_for_investigation(), filtered by ExecutionPhase.AGENT_SELECTABLE.
# This constant is retained only for backward compatibility and will be removed.
ALLOWED_STEPS: set[str] = set()


def extract_json(text: str) -> dict[str, Any]:
    if not text.strip():
        raise ValueError("empty opencode output")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and parsed.get("type") == "text":
            part = parsed.get("part")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                return _extract_json_from_text(part["text"])
        if isinstance(parsed, dict) and "schema_version" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    event_texts: list[str] = []
    fallback_texts: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("type") == "text":
            part = item.get("part")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                event_texts.append(part["text"])
                continue
        fallback_texts.extend(_collect_strings(item))
    if event_texts:
        return _extract_json_from_text("\n".join(event_texts))
    combined = "\n".join(fallback_texts) if fallback_texts else text
    return _extract_json_from_text(combined)


def _extract_json_from_text(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    for candidate in _json_object_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("no JSON object found in opencode output")


def _json_object_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    starts = [idx for idx, char in enumerate(text) if char == "{"]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(text)):
            char = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : idx + 1])
                    break
    return sorted(candidates, key=len, reverse=True)


def _collect_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, list):
        for item in value:
            strings.extend(_collect_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            strings.extend(_collect_strings(item))
    return strings


def _coerce_material_source_params(params: dict[str, Any]) -> dict[str, Any]:
    coerced = dict(DEFAULT_SOURCE_FINDING_PARAMS)
    for key, default in DEFAULT_SOURCE_FINDING_PARAMS.items():
        value = params.get(key, default)
        try:
            coerced[key] = int(value) if isinstance(default, int) else float(value)
        except (TypeError, ValueError):
            coerced[key] = default
    coerced["min_overlap"] = max(8, min(50, int(coerced["min_overlap"])))
    coerced["min_support"] = max(0.90, min(1.0, float(coerced["min_support"])))
    coerced["max_findings_per_category"] = max(20, min(500, int(coerced["max_findings_per_category"])))
    return coerced


def _require(data: dict[str, Any], key: str, expected: type) -> Any:
    value = data.get(key)
    if not isinstance(value, expected):
        raise ValueError(f"{key} must be {expected.__name__}")
    return value
