"""LLM prompt template for generating follow-up questions from findings.

The prompt is designed to produce PI-friendly questions that:
1. Reference concrete data (column names, row numbers, values, figure IDs)
2. Use language a non-technical PI can understand
3. Avoid accusatory or definitive terms (e.g. "造假", "篡改", "抄袭")
4. Are specific and answerable, not generic "please explain"
"""

from __future__ import annotations

import json


def build_follow_up_prompt(finding: dict) -> str:
    """Build an LLM prompt for generating 1-2 follow-up questions for a finding.

    Args:
        finding: A finding dict with keys like finding_id, category, risk_level,
                 summary, issue_category, metadata, evidence_refs.

    Returns:
        A prompt string ready to send to the LLM.
    """
    metadata_json = json.dumps(
        finding.get("metadata", {}),
        ensure_ascii=False,
        indent=2,
    )
    evidence_refs = finding.get("evidence_refs", [])

    return f"""\
你是 PI（通讯作者/导师）的助手，帮助 PI 向学生提出具体的追问问题。

## 任务
根据以下 finding 信息，生成 1-2 个追问问题。问题应该：
1. 具体、可回答（不是泛泛的"请解释"）
2. 引用具体数据（列名、行号、数值、图片 ID）
3. 使用 PI 能理解的语言（不使用技术术语）
4. 保持中立、不预判学术不端
5. 不使用定罪性措辞（如"造假"、"篡改"、"抄袭"）

## Finding 信息
- finding_id: {finding.get("finding_id", "N/A")}
- category: {finding.get("category", "unknown")}
- risk_level: {finding.get("risk_level", "medium")}
- summary: {finding.get("summary", "N/A")}
- issue_category: {finding.get("issue_category", "N/A")}
- metadata: {metadata_json}
- evidence_refs: {json.dumps(evidence_refs, ensure_ascii=False)}

## 输出格式
严格返回 JSON，不要包含任何其他文字：
{{"questions": ["问题1", "问题2"]}}
"""
