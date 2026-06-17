"""Tool Registry DB seed and investigation catalog query."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from engine.tools.registry import TOOLS, ToolDefinition

from .models import ToolRegistryModel


def seed_tool_registry(db: Session) -> int:
    """Write all Tool Definitions from engine.tools.registry into the DB.

    Called at app startup.  Returns the number of tools seeded.
    """
    count = 0
    for tool_id, tool_def in TOOLS.items():
        existing = db.get(ToolRegistryModel, tool_id)
        if existing:
            # Update in place
            for key, value in _tool_to_dict(tool_def).items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
        else:
            db.add(ToolRegistryModel(**_tool_to_dict(tool_def)))
        count += 1
    db.commit()
    return count


def get_investigation_catalog(db: Session) -> list[dict[str, Any]]:
    """Return tools that are agent-selectable and deterministic."""
    models = (
        db.query(ToolRegistryModel)
        .filter(
            ToolRegistryModel.agent_selectable == True,  # noqa: E712
            ToolRegistryModel.deterministic == True,  # noqa: E712
        )
        .all()
    )
    return [m.to_dict() for m in models]


def _tool_to_dict(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "tool_id": tool.tool_id,
        "step_key": tool.step_key,
        "title": tool.title,
        "source": tool.source,
        "description": tool.description,
        "deterministic": tool.deterministic,
        "agent_selectable": tool.agent_selectable,
        "input_artifacts": list(tool.input_artifacts),
        "output_artifacts": list(tool.output_artifacts or tool.expected_outputs),
        "parameter_defaults": tool.parameter_defaults,
        "param_schema": tool.param_schema,
        "execution_phase": tool.execution_phase,
    }
