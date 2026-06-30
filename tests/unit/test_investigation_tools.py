"""Tests for engine.static_audit.investigation_tools — adapter registry.

Verifies that:
1. Every registered tool_id has a corresponding output filename mapping.
2. The dispatcher (via ADAPTERS) routes to the correct adapter.
3. Adapter functions handle missing preconditions (skip gracefully).
4. Unknown tool_ids fall through to the "not yet implemented" path.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from engine.shared.types import InvestigationAction
from engine.static_audit.investigation_tools import (
    ADAPTERS,
    AdapterFn,
    _load_panels_and_figures,
    _require_source_data_dir,
    _skip,
    tool_output_filename,
)
from engine.static_audit._shared import StepResult
from engine.tools.registry import (
    IMAGE_SIMILARITY_TOOL_ID,
    SOURCE_DATA_CROSS_SHEET_TOOL_ID,
    SOURCE_DATA_FINDINGS_TOOL_ID,
    SOURCE_DATA_PAIR_FORENSICS_TOOL_ID,
    TOOL_ID_COPY_MOVE,
    TOOL_ID_OVERLAP_REUSE,
    TOOL_ID_SILA_DENSE,
)


def _make_action(
    tool_id: str = "source_data.profile",
    round_id: int = 1,
    action_id: str = "IR-01-A001",
    params: dict | None = None,
) -> InvestigationAction:
    return InvestigationAction(
        round_id=round_id,
        action_id=action_id,
        tool_id=tool_id,
        params=params or {},
        hypothesis="test",
        depends_on_artifacts=["test.json"],
        expected_evidence_type="test",
    )


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------


class TestAdapterRegistry:
    """Verify registry invariants."""

    EXPECTED_TOOL_IDS = {
        "source_data.profile",
        SOURCE_DATA_FINDINGS_TOOL_ID,
        SOURCE_DATA_PAIR_FORENSICS_TOOL_ID,
        SOURCE_DATA_CROSS_SHEET_TOOL_ID,
        IMAGE_SIMILARITY_TOOL_ID,
        TOOL_ID_COPY_MOVE,
        TOOL_ID_OVERLAP_REUSE,
        TOOL_ID_SILA_DENSE,
    }

    def test_registry_contains_all_known_tools(self):
        assert set(ADAPTERS.keys()) == self.EXPECTED_TOOL_IDS

    def test_every_adapter_is_callable(self):
        for tool_id, adapter in ADAPTERS.items():
            assert callable(adapter), f"adapter for {tool_id} is not callable"

    def test_output_filename_for_every_registered_tool(self):
        for tool_id in ADAPTERS:
            filename = tool_output_filename(tool_id)
            assert filename.endswith(".json"), (
                f"output filename for {tool_id} must be .json: {filename}"
            )

    def test_output_filename_fallback_for_unknown_tool(self):
        filename = tool_output_filename("unknown.tool")
        assert filename == "unknown_tool.json"


# ---------------------------------------------------------------------------
# Precondition helpers
# ---------------------------------------------------------------------------


class TestPreconditionHelpers:
    def test_require_source_data_dir_missing(self, tmp_path: Path):
        assert _require_source_data_dir(None, "k", None) is True
        assert _require_source_data_dir(tmp_path / "nonexistent", "k", None) is True

    def test_require_source_data_dir_present(self, tmp_path: Path):
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        assert _require_source_data_dir(source_dir, "k", None) is False

    def test_skip_produces_skipped_step(self):
        step, artifacts = _skip("test_key", "reason", None)
        assert isinstance(step, StepResult)
        assert step.status == "skipped"
        assert step.detail == "reason"
        assert step.key == "test_key"
        assert artifacts == []


# ---------------------------------------------------------------------------
# Adapter dispatch — source_data_dir precondition
# ---------------------------------------------------------------------------


class TestSourceDataDirPrecondition:
    """Adapters that require source_data_dir should skip gracefully."""

    @pytest.mark.parametrize(
        "tool_id",
        [
            "source_data.profile",
            SOURCE_DATA_FINDINGS_TOOL_ID,
            SOURCE_DATA_PAIR_FORENSICS_TOOL_ID,
        ],
    )
    def test_skips_when_source_data_dir_missing(
        self, tmp_path: Path, tool_id: str
    ):
        adapter = ADAPTERS[tool_id]
        action = _make_action(tool_id=tool_id)
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        output = action_dir / tool_output_filename(tool_id)

        step, artifacts = adapter(
            action, tmp_path, None, {}, False, None,
            "test_key", action_dir, output,
        )
        assert step.status == "skipped"
        assert artifacts == []


# ---------------------------------------------------------------------------
# Adapter dispatch — missing artifact preconditions
# ---------------------------------------------------------------------------


class TestArtifactPreconditions:
    """Adapters should skip when required artifacts are missing."""

    def test_source_data_findings_skips_without_profile(self, tmp_path: Path):
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        adapter = ADAPTERS[SOURCE_DATA_FINDINGS_TOOL_ID]
        action = _make_action(tool_id=SOURCE_DATA_FINDINGS_TOOL_ID)
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        output = action_dir / "source_data_findings.json"

        step, artifacts = adapter(
            action, tmp_path, source_dir, {}, False, None,
            "test_key", action_dir, output,
        )
        assert step.status == "skipped"
        assert "source_data_profile.json missing" in step.detail

    def test_image_similarity_skips_without_images_dir(self, tmp_path: Path):
        adapter = ADAPTERS[IMAGE_SIMILARITY_TOOL_ID]
        action = _make_action(tool_id=IMAGE_SIMILARITY_TOOL_ID)
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        output = action_dir / "image_similarity_candidates.json"

        step, artifacts = adapter(
            action, tmp_path, None, {}, False, None,
            "test_key", action_dir, output,
        )
        assert step.status == "skipped"
        assert "images directory missing" in step.detail

    def test_copy_move_skips_without_panel_evidence(self, tmp_path: Path):
        adapter = ADAPTERS[TOOL_ID_COPY_MOVE]
        action = _make_action(tool_id=TOOL_ID_COPY_MOVE)
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        output = action_dir / "visual_copy_move.json"

        step, artifacts = adapter(
            action, tmp_path, None, {}, False, None,
            "test_key", action_dir, output,
        )
        assert step.status == "skipped"
        assert "panel_evidence.json missing" in step.detail

    def test_overlap_reuse_skips_without_panel_evidence(self, tmp_path: Path):
        adapter = ADAPTERS[TOOL_ID_OVERLAP_REUSE]
        action = _make_action(tool_id=TOOL_ID_OVERLAP_REUSE)
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        output = action_dir / "overlap_reuse.json"

        step, artifacts = adapter(
            action, tmp_path, None, {}, False, None,
            "test_key", action_dir, output,
        )
        assert step.status == "skipped"

    def test_sila_dense_skips_without_panel_evidence(self, tmp_path: Path):
        adapter = ADAPTERS[TOOL_ID_SILA_DENSE]
        action = _make_action(tool_id=TOOL_ID_SILA_DENSE)
        action_dir = tmp_path / "action"
        action_dir.mkdir()
        output = action_dir / "visual_copy_move_dense.json"

        step, artifacts = adapter(
            action, tmp_path, None, {}, False, None,
            "test_key", action_dir, output,
        )
        assert step.status == "skipped"


# ---------------------------------------------------------------------------
# _load_panels_and_figures
# ---------------------------------------------------------------------------


class TestLoadPanelsAndFigures:
    def test_returns_empty_when_panel_evidence_missing(self, tmp_path: Path):
        panels, figures = _load_panels_and_figures(tmp_path)
        assert panels == []
        assert figures == []

    def test_loads_dict_with_panels_key(self, tmp_path: Path):
        panel_path = tmp_path / "visual" / "panel_evidence.json"
        panel_path.parent.mkdir(parents=True)
        panel_path.write_text(json.dumps({"panels": [{"id": "p1"}]}))

        panels, figures = _load_panels_and_figures(tmp_path)
        assert panels == [{"id": "p1"}]
        assert figures == []

    def test_loads_bare_list(self, tmp_path: Path):
        panel_path = tmp_path / "visual" / "panel_evidence.json"
        panel_path.parent.mkdir(parents=True)
        panel_path.write_text(json.dumps([{"id": "p1"}, {"id": "p2"}]))

        panels, figures = _load_panels_and_figures(tmp_path)
        assert len(panels) == 2

    def test_loads_figures_from_visual_evidence(self, tmp_path: Path):
        panel_path = tmp_path / "visual" / "panel_evidence.json"
        panel_path.parent.mkdir(parents=True)
        panel_path.write_text(json.dumps({"panels": []}))

        # resolve_artifact_path maps "visual_evidence.json" → "visual/evidence.json"
        visual_path = tmp_path / "visual" / "evidence.json"
        visual_path.write_text(json.dumps({"figures": [{"figure_id": "f1"}]}))

        panels, figures = _load_panels_and_figures(tmp_path)
        assert figures == [{"figure_id": "f1"}]
