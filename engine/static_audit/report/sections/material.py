"""Material inventory section builder."""

from __future__ import annotations

from typing import Any

from engine.static_audit._shared import markdown_table, fmt_int
from engine.static_audit.report.sections._shared import ReportData
from engine.static_audit.report.claims import brief_list


def material_section(data: ReportData) -> list[str]:
    if not (data.material_inventory or data.material_plan):
        return []
    inventory_summary = (data.material_inventory or {}).get("summary", {})
    material_by_type = (
        inventory_summary.get("by_material_type")
        if isinstance(inventory_summary.get("by_material_type"), dict)
        else {}
    )
    selected_lanes_raw = (data.material_plan or {}).get("selected_optional_lanes")
    selected_lanes: list[Any] = (
        selected_lanes_raw  # type: ignore[assignment]
        if isinstance((data.material_plan or {}).get("selected_optional_lanes"), list)
        else []
    )
    selected_lane_text = brief_list(
        [
            f"{lane.get('lane_id')}:{lane.get('status')}:{lane.get('root') or '-'}"
            for lane in (selected_lanes or [])  # Type narrow: ensure not None
            if isinstance(lane, dict)
        ],
        limit=5,
    )
    lines: list[str] = []
    lines.append("## Material Inventory and Optional Lanes")
    lines.append("")
    lines.append(
        markdown_table(
            ["Metric", "Value"],
            [
                ["material_files", fmt_int(inventory_summary.get("file_count"))],
                [
                    "material_types",
                    ", ".join(
                        f"{key}={value}" for key, value in material_by_type.items()
                    )
                    or "-",
                ],
                [
                    "candidate_source_roots",
                    fmt_int(inventory_summary.get("candidate_source_roots")),
                ],
                [
                    "supported_optional_lanes",
                    fmt_int(inventory_summary.get("supported_optional_lanes")),
                ],
                [
                    "material_plan_status",
                    (data.material_plan or {}).get("status", "ok"),
                ],
                ["selected_optional_lanes", selected_lane_text],
                [
                    "missing_materials",
                    brief_list((data.material_plan or {}).get("missing_materials")),
                ],
            ],
        )
    )
    unsupported = (data.material_plan or {}).get("unsupported_materials") or []
    if unsupported:
        lines.append("")
        lines.append("Unsupported optional materials detected:")
        for item in unsupported[:8]:
            if isinstance(item, dict):
                lines.append(
                    f"- `{item.get('path', '-')}` ({item.get('material_type', '-')})"
                )
    lines.append("")
    return lines
