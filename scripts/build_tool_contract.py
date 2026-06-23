#!/usr/bin/env python3
"""Generate configs/opencode/generated/tool_contract.md from engine/tools/registry.py.

Produces a compact Markdown summary grouped by ExecutionPhase.
No parameter details — just tool_id, deterministic, agent_selectable, artifacts.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path so imports work regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from engine.tools.registry import TOOLS, ExecutionPhase


def _fmt_artifacts(artifacts: tuple[str, ...]) -> str:
    if not artifacts:
        return "-"
    return ", ".join(artifacts)


def _phase_label(phase: ExecutionPhase) -> str:
    return phase.value.replace("_", " ").title()


def _build_markdown() -> str:
    lines: list[str] = []

    # Header
    lines.append("# Tool Contract (Auto-Generated)")
    lines.append("")
    lines.append(
        "> DO NOT EDIT — generated from `engine/tools/registry.py` "
        "by `scripts/build_tool_contract.py`"
    )
    lines.append("")

    # Summary
    phase_counts: dict[ExecutionPhase, int] = {p: 0 for p in ExecutionPhase}
    for tool in TOOLS.values():
        phase_counts[tool.execution_phase] += 1

    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Total tools | {len(TOOLS)} |")
    for phase in ExecutionPhase:
        lines.append(f"| {_phase_label(phase)} | {phase_counts[phase]} |")
    lines.append("")

    # Per-phase sections
    for phase in ExecutionPhase:
        tools_in_phase = [
            t for t in TOOLS.values() if t.execution_phase == phase
        ]
        if not tools_in_phase:
            continue

        lines.append(f"## {_phase_label(phase)}")
        lines.append("")
        lines.append(
            "| tool_id | deterministic | agent_selectable | "
            "input_artifacts | output_artifacts |"
        )
        lines.append(
            "|---|---|---|---|---|"
        )
        for t in tools_in_phase:
            lines.append(
                f"| `{t.tool_id}` | {'yes' if t.deterministic else '**no**'} | "
                f"{'yes' if t.agent_selectable else 'no'} | "
                f"`{_fmt_artifacts(t.input_artifacts)}` | "
                f"`{_fmt_artifacts(t.output_artifacts)}` |"
            )
        lines.append("")

        # Selection rules for agent-selectable phase
        if phase == ExecutionPhase.AGENT_SELECTABLE:
            lines.append("### Selection Rules")
            lines.append("")
            lines.append(
                "Agent investigation rounds may only select tools from this phase. "
                "Constraints enforced by `validate_investigation_tool_action()`:"
            )
            lines.append("")
            lines.append("- Tool must have `execution_phase = agent_selectable`")
            lines.append("- Tool must be `deterministic = true` (non-deterministic agents are invoked via role layer, not investigation)")
            lines.append("- Params are validated against `param_schema` ranges in registry")
            lines.append("- Max 3 investigation rounds per audit run")
            lines.append("- Each action requires `hypothesis`, `depends_on_artifacts`, and `expected_evidence_type`")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    out_dir = _PROJECT_ROOT / "configs" / "opencode" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "tool_contract.md"

    md = _build_markdown()
    out_path.write_text(md, encoding="utf-8")

    phase_set = {t.execution_phase for t in TOOLS.values()}
    print(f"Generated tool_contract.md: {len(TOOLS)} tools, {len(phase_set)} phases")


if __name__ == "__main__":
    main()
