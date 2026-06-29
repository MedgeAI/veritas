"""Integration tests for figure classification pipeline step.

Exercises the REAL ``run_figure_classification_step`` function with
real I/O on disk (writing full.md, reading artifact output), but
mocks only the LLM client at the external-API boundary (network I/O).

Tests cover:
- Pipeline step with real legend parsing + LLM classification
- Artifact reuse path
- Skip path (no full.md)
- Multi-figure classification with YOLO + LLM merge
- filter_wet_lab_panels integration with pipeline output
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from engine.static_audit._shared import WET_LAB_TYPES, filter_wet_lab_panels
from engine.static_audit.figure_classification import (
    classify_all_figures,
    classify_panel_with_yolo_priority,
    parse_figure_legends,
    run_figure_classification_step,
)


# ---------------------------------------------------------------------------
# Pipeline step integration
# ---------------------------------------------------------------------------


class TestRunFigureClassificationStepIntegration:
    """End-to-end: full.md -> run_figure_classification_step -> artifact."""

    def test_full_pipeline_with_multi_figure_input(self, tmp_path: Path):
        """Real legend parsing + mocked LLM produces expected artifact shape."""
        # Write a realistic full.md with multiple figures
        full_md = """
# Results

We observed significant effects across all conditions.

# Fig. 1 | Characterization of the cell population.
a, Western blot showing protein expression levels. b, Flow cytometry analysis of cell surface markers. c, UMAP embedding of single-cell transcriptomes.

# Fig. 2 | Functional validation.
a, Representative microscopy images of transfected cells. b, Quantification of fluorescence intensity across conditions. c, Dose-response curve for drug treatment.

# Extended Data Fig. 1 | Control experiments.
a, Gel electrophoresis confirming protein purity.
"""
        (tmp_path / "full.md").write_text(full_md)

        # Mock LLM client — first call is the batch attempt which fails,
        # triggering fallback to 3 per-figure calls.
        mock_client = MagicMock()
        mock_client.chat_json.side_effect = [
            # Batch call: raise to trigger fallback
            RuntimeError("batch disabled in test"),
            # Fig. 1: 3 panels (wet_lab, wet_lab, bioinformatics)
            {
                "a": {"description": "Western blot", "classification": "wet_lab"},
                "b": {"description": "Flow cytometry", "classification": "wet_lab"},
                "c": {"description": "UMAP plot", "classification": "bioinformatics"},
            },
            # Fig. 2: 3 panels (wet_lab, bioinformatics, bioinformatics)
            {
                "a": {"description": "Microscopy image", "classification": "wet_lab"},
                "b": {"description": "Bar chart", "classification": "bioinformatics"},
                "c": {"description": "Dose-response curve", "classification": "bioinformatics"},
            },
            # Extended Data Fig. 1: 1 panel
            {
                "a": {"description": "Gel image", "classification": "wet_lab"},
            },
        ]

        steps, manifest = run_figure_classification_step(
            workdir=tmp_path,
            force=True,
            llm_client=mock_client,
            progress=None,
        )

        # Verify step status
        assert len(steps) == 1
        assert steps[0].status == "ran"
        assert manifest["figure_classification"]["status"] == "ran"
        assert manifest["figure_classification"]["figure_count"] == 3

        # Verify artifact was written
        fc_path = tmp_path / "figure_classification.json"
        assert fc_path.exists()
        artifact = json.loads(fc_path.read_text())

        # Artifact wraps classifications under "classifications" key
        assert "classifications" in artifact
        assert artifact["status"] == "ran"
        assert artifact["figure_count"] == 3

        cls = artifact["classifications"]
        assert "Fig. 1" in cls
        assert "Fig. 2" in cls
        assert "Extended Data Fig. 1" in cls

        # Verify panel classifications
        assert cls["Fig. 1"]["a"]["classification"] == "wet_lab"
        assert cls["Fig. 1"]["c"]["classification"] == "bioinformatics"
        assert cls["Fig. 2"]["b"]["classification"] == "bioinformatics"
        assert cls["Extended Data Fig. 1"]["a"]["classification"] == "wet_lab"

        # Verify LLM was called 4 times: 1 batch + 3 per-figure (batch failed, fallback)
        assert mock_client.chat_json.call_count == 4

    def test_skip_when_full_md_missing(self, tmp_path: Path):
        """Pipeline step skips gracefully when full.md is absent."""
        steps, manifest = run_figure_classification_step(
            workdir=tmp_path,
            force=False,
            progress=None,
        )

        assert len(steps) == 1
        assert steps[0].status == "skipped"
        assert manifest["figure_classification"]["status"] == "skipped"

        # No artifact should be created
        fc_path = tmp_path / "figure_classification.json"
        assert not fc_path.exists()

    def test_reuse_existing_artifact(self, tmp_path: Path):
        """When artifact exists and force=False, step reuses it."""
        fc_path = tmp_path / "figure_classification.json"
        # Existing artifact should have status field
        fc_path.write_text(json.dumps({
            "status": "ran",
            "figure_count": 1,
            "classifications": {"Fig. 1": {"a": {"classification": "wet_lab"}}},
        }))

        steps, manifest = run_figure_classification_step(
            workdir=tmp_path,
            force=False,
            progress=None,
        )

        assert len(steps) == 1
        assert steps[0].status == "reused"
        # Manifest returns the existing artifact data as-is
        assert manifest["figure_classification"]["status"] == "ran"
        assert manifest["figure_classification"]["figure_count"] == 1


# ---------------------------------------------------------------------------
# Legend parsing + LLM classification integration
# ---------------------------------------------------------------------------


class TestLegendParsingAndClassification:
    """Real legend parsing -> mocked LLM classification."""

    def test_parse_and_classify_multi_figure(self):
        """Parse legends from markdown, then classify all panels."""
        full_md = """
# Fig. 1 | Title of figure 1.
a, Description of panel a. b, Description of panel b.

# Fig. 2 | Title of figure 2.
c, Description of panel c. d, Description of panel d.
"""
        legends = parse_figure_legends(full_md)
        assert len(legends) == 2
        assert "Fig. 1" in legends
        assert "Fig. 2" in legends

        # Mock LLM client — first call is the batch attempt which fails,
        # triggering fallback to per-figure calls.
        mock_client = MagicMock()
        mock_client.chat_json.side_effect = [
            # Batch call: raise to trigger fallback
            RuntimeError("batch disabled in test"),
            {"a": {"description": "Blot", "classification": "wet_lab"},
             "b": {"description": "Plot", "classification": "bioinformatics"}},
            {"c": {"description": "Image", "classification": "wet_lab"},
             "d": {"description": "Chart", "classification": "bioinformatics"}},
        ]

        result = classify_all_figures(legends, mock_client)

        assert len(result) == 2
        assert result["Fig. 1"]["a"]["classification"] == "wet_lab"
        assert result["Fig. 1"]["b"]["classification"] == "bioinformatics"
        assert result["Fig. 2"]["c"]["classification"] == "wet_lab"
        assert result["Fig. 2"]["d"]["classification"] == "bioinformatics"


# ---------------------------------------------------------------------------
# YOLO + LLM merge
# ---------------------------------------------------------------------------


class TestYoloLLMMerge:
    """YOLO panel_type takes priority; LLM fills gaps."""

    def test_yolo_overrides_llm_for_known_types(self):
        """When YOLO knows the panel type, it wins over LLM."""
        # YOLO says "Blots" -> wet_lab, even though LLM says bioinformatics
        panel = {"panel_type": "Blots", "label": "a", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"a": {"classification": "bioinformatics"}}}

        result = classify_panel_with_yolo_priority(panel, llm_cls)
        assert result == "wet_lab"

    def test_yolo_graphs_type(self):
        """YOLO 'Graphs' -> bioinformatics."""
        panel = {"panel_type": "Graphs", "label": "b", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"b": {"classification": "wet_lab"}}}

        result = classify_panel_with_yolo_priority(panel, llm_cls)
        assert result == "bioinformatics"

    def test_yolo_unknown_falls_back_to_llm(self):
        """When YOLO is empty/unknown, use LLM classification."""
        panel = {"panel_type": "", "label": "a", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"a": {"classification": "wet_lab"}}}

        result = classify_panel_with_yolo_priority(panel, llm_cls)
        assert result == "wet_lab"

    def test_both_unknown_returns_unknown(self):
        """When both YOLO and LLM fail, return 'unknown'."""
        panel = {"panel_type": "", "label": "z", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"a": {"classification": "wet_lab"}}}

        result = classify_panel_with_yolo_priority(panel, llm_cls)
        assert result == "unknown"


# ---------------------------------------------------------------------------
# filter_wet_lab_panels integration
# ---------------------------------------------------------------------------


class TestFilterWetLabPanelsIntegration:
    """filter_wet_lab_panels with realistic pipeline output."""

    def test_filter_pipeline_output(self):
        """Filter panels from pipeline output, keeping only wet_lab + mixed."""
        panels = [
            {"panel_id": "fig1-a", "panel_classification": "wet_lab"},
            {"panel_id": "fig1-b", "panel_classification": "bioinformatics"},
            {"panel_id": "fig1-c", "panel_classification": "mixed"},
            {"panel_id": "fig2-a", "panel_classification": "wet_lab"},
            {"panel_id": "fig2-b", "panel_classification": "other"},
            {"panel_id": "fig2-c", "panel_classification": "unknown"},
        ]

        result = filter_wet_lab_panels(panels, {})

        # WET_LAB_TYPES = {"wet_lab", "mixed"}; unknown/bioinformatics/other excluded
        # So: fig1-a (wet_lab), fig1-c (mixed), fig2-a (wet_lab) = 3
        assert len(result) == 3
        result_ids = {p["panel_id"] for p in result}
        assert result_ids == {"fig1-a", "fig1-c", "fig2-a"}

    def test_filter_with_llm_classifications(self):
        """When panel_classification not set, use LLM classifications dict."""
        panels = [
            {"panel_id": "p1", "label": "a", "parent_figure_id": "fig1"},
            {"panel_id": "p2", "label": "b", "parent_figure_id": "fig1"},
            {"panel_id": "p3", "label": "c", "parent_figure_id": "fig1"},
        ]
        classifications = {
            "classifications": {
                "Fig. 1": {
                    "a": {"classification": "wet_lab"},
                    "b": {"classification": "bioinformatics"},
                    "c": {"classification": "mixed"},
                }
            }
        }

        result = filter_wet_lab_panels(panels, classifications)

        # Should include wet_lab (p1) and mixed (p3)
        assert len(result) == 2
        result_ids = {p["panel_id"] for p in result}
        assert result_ids == {"p1", "p3"}

    def test_wet_lab_types_constant(self):
        """WET_LAB_TYPES includes expected values."""
        assert "wet_lab" in WET_LAB_TYPES
        assert "mixed" in WET_LAB_TYPES
        assert "bioinformatics" not in WET_LAB_TYPES
        assert "other" not in WET_LAB_TYPES
        # Note: "unknown" is NOT in WET_LAB_TYPES, but filter_wet_lab_panels
        # includes it as a conservative fallback
