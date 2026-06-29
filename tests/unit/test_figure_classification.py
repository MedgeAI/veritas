"""Unit tests for LLM figure classification pipeline step.

Tests cover:
- Legend parsing from full.md
- LLM classification (mocked client)
- Panel classification with YOLO priority
- filter_wet_lab_panels helper
- Pipeline step integration
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.static_audit._shared import WET_LAB_TYPES, filter_wet_lab_panels
from engine.static_audit.figure_classification import (
    _normalize_figure_label,
    classify_all_figures,
    classify_figure,
    build_figure_id_to_paper_label_mapping,
    build_image_to_paper_label_mapping,
    classify_panel_with_llm_priority,
    classify_panel_with_yolo_priority,
    parse_figure_legends,
    run_figure_classification_step,
)


# ---------------------------------------------------------------------------
# Legend parsing
# ---------------------------------------------------------------------------


class TestParseFigureLegends:
    """Test figure legend extraction from full.md."""

    def test_heading_based_legend(self) -> None:
        """Parse legend from markdown heading."""
        full_md = """
# Results

# Fig. 1 | Title of figure 1.
a, Description of panel a. b, Description of panel b.

# Discussion
"""
        legends = parse_figure_legends(full_md)
        assert "Fig. 1" in legends
        assert "Title of figure 1" in legends["Fig. 1"]
        assert "Description of panel a" in legends["Fig. 1"]

    def test_extended_data_figure(self) -> None:
        """Parse Extended Data figure legend."""
        full_md = """
# Extended Data Fig. 1 | Supplementary figure.
a, Panel a description.

# Results
"""
        legends = parse_figure_legends(full_md)
        assert "Extended Data Fig. 1" in legends
        assert "Supplementary figure" in legends["Extended Data Fig. 1"]

    def test_multiple_figures(self) -> None:
        """Parse multiple figure legends."""
        full_md = """
# Fig. 1 | First figure.
a, First panel a.

# Fig. 2 | Second figure.
b, Second panel b.

# Fig. 3 | Third figure.
c, Third panel c.
"""
        legends = parse_figure_legends(full_md)
        assert len(legends) == 3
        assert "Fig. 1" in legends
        assert "Fig. 2" in legends
        assert "Fig. 3" in legends

    def test_empty_text(self) -> None:
        """Handle empty input."""
        legends = parse_figure_legends("")
        assert legends == {}

    def test_no_figures(self) -> None:
        """Handle text with no figures."""
        full_md = """
# Results

Some text without figure legends.

# Discussion
"""
        legends = parse_figure_legends(full_md)
        assert legends == {}


class TestNormalizeFigureLabel:
    """Test figure label normalization."""

    def test_figure_abbreviation(self) -> None:
        """Normalize 'Figure' to 'Fig.'."""
        assert _normalize_figure_label("Figure 1") == "Fig. 1"

    def test_extra_whitespace(self) -> None:
        """Remove extra whitespace."""
        assert _normalize_figure_label("Fig.   2") == "Fig. 2"

    def test_extended_data(self) -> None:
        """Preserve Extended Data prefix."""
        assert _normalize_figure_label("Extended Data Figure 3") == "Extended Data Fig. 3"

    def test_case_insensitive(self) -> None:
        """Normalize mixed-case LLM labels."""
        assert _normalize_figure_label("extended data figure 4") == "Extended Data Fig. 4"
        assert _normalize_figure_label("fig 5") == "Fig. 5"


# ---------------------------------------------------------------------------
# LLM classification
# ---------------------------------------------------------------------------


class TestClassifyFigure:
    """Test LLM-based figure classification."""

    def test_wet_lab_classification(self) -> None:
        """Classify wet-lab panels."""
        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "a": {"description": "Western blot", "classification": "wet_lab"},
            "b": {"description": "Microscopy image", "classification": "wet_lab"},
        }

        result = classify_figure(
            "Fig. 1",
            "a, Western blot showing protein expression. b, Microscopy image of cells.",
            mock_client,
        )

        assert "a" in result
        assert result["a"]["classification"] == "wet_lab"
        assert "b" in result
        assert result["b"]["classification"] == "wet_lab"

    def test_bioinformatics_classification(self) -> None:
        """Classify bioinformatics panels."""
        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "a": {"description": "UMAP plot", "classification": "bioinformatics"},
            "b": {"description": "Heatmap", "classification": "bioinformatics"},
        }

        result = classify_figure(
            "Fig. 2",
            "a, UMAP plot showing cell clusters. b, Heatmap of gene expression.",
            mock_client,
        )

        assert result["a"]["classification"] == "bioinformatics"
        assert result["b"]["classification"] == "bioinformatics"

    def test_mixed_classification(self) -> None:
        """Classify figure with mixed panel types."""
        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "a": {"description": "Western blot", "classification": "wet_lab"},
            "b": {"description": "Bar chart", "classification": "bioinformatics"},
        }

        result = classify_figure(
            "Fig. 3",
            "a, Western blot. b, Bar chart showing quantification.",
            mock_client,
        )

        assert result["a"]["classification"] == "wet_lab"
        assert result["b"]["classification"] == "bioinformatics"

    def test_empty_legend(self) -> None:
        """Handle empty legend text."""
        mock_client = MagicMock()
        result = classify_figure("Fig. 4", "", mock_client)
        assert result == {}
        mock_client.chat_json.assert_not_called()

    def test_llm_returns_empty_dict(self) -> None:
        """Handle LLM returning empty dict."""
        mock_client = MagicMock()
        mock_client.chat_json.return_value = {}

        result = classify_figure("Fig. 5", "Some unclear legend", mock_client)
        assert result == {}

    def test_llm_exception(self) -> None:
        """Handle LLM exception gracefully."""
        mock_client = MagicMock()
        mock_client.chat_json.side_effect = Exception("API error")

        result = classify_figure("Fig. 6", "Valid legend text", mock_client)
        assert result == {}


class TestClassifyAllFigures:
    """Test batch classification of all figures."""

    def test_multiple_figures(self) -> None:
        """Classify multiple figures."""
        mock_client = MagicMock()
        mock_client.chat_json.side_effect = [
            {"a": {"description": "Blot", "classification": "wet_lab"}},
            {"b": {"description": "Plot", "classification": "bioinformatics"}},
        ]

        legends = {
            "Fig. 1": "a, Western blot.",
            "Fig. 2": "b, UMAP plot.",
        }

        result = classify_all_figures(legends, mock_client)
        assert len(result) == 2
        assert "Fig. 1" in result
        assert "Fig. 2" in result


# ---------------------------------------------------------------------------
# Image → paper label mapping
# ---------------------------------------------------------------------------


class TestImageToPaperLabelMapping:
    """Test LLM mapping from markdown image refs to paper figure labels."""

    def test_normalizes_llm_labels(self) -> None:
        full_md = """
![](images/toc.jpg)

# Fig. 1 | First figure.
![](images/fig1.jpg)

# Extended Data Fig. 2 | Supplementary figure.
![](images/ed2.jpg)
"""
        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "toc.jpg": "Other",
            "fig1.jpg": "figure 1",
            "ed2.jpg": "extended data figure 2",
        }

        result = build_image_to_paper_label_mapping(full_md, mock_client)

        assert result == {
            "toc.jpg": "other",
            "fig1.jpg": "Fig. 1",
            "ed2.jpg": "Extended Data Fig. 2",
        }

    def test_figure_id_mapping_uses_supported_ledger_paths(
        self,
        tmp_path: Path,
    ) -> None:
        mineru_dir = tmp_path / "mineru"
        mineru_dir.mkdir()
        (mineru_dir / "full.md").write_text(
            """
![](images/rel.jpg)
# Fig. 1 | Relative path figure.

![](images/raw.jpg)
# Fig. 2 | Raw path figure.

![](images/source.jpg)
# Fig. 3 | Source image path figure.
""",
            encoding="utf-8",
        )
        (mineru_dir / "evidence_ledger.json").write_text(
            json.dumps(
                {
                    "figures": [
                        {
                            "id": "figure-md-0001",
                            "type": "figure",
                            "image_ref": {"relative_path": "images/rel.jpg"},
                        },
                        {
                            "id": "figure-md-0002",
                            "type": "figure",
                            "image_ref": {"raw": "images/raw.jpg?token=1"},
                        },
                        {
                            "id": "figure-md-0003",
                            "type": "figure",
                            "source_image_path": "images/source.jpg",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "rel.jpg": "Figure 1",
            "raw.jpg": "fig. 2",
            "source.jpg": "Fig. 3",
        }

        result = build_figure_id_to_paper_label_mapping(tmp_path, mock_client)

        assert result == {
            "figure-md-0001": "Fig. 1",
            "figure-md-0002": "Fig. 2",
            "figure-md-0003": "Fig. 3",
        }


# ---------------------------------------------------------------------------
# Panel classification with YOLO priority
# ---------------------------------------------------------------------------


class TestClassifyPanelWithYoloPriority:
    """Test panel classification combining YOLO and LLM."""

    def test_yolo_wet_lab_types(self) -> None:
        """YOLO panel_type takes priority for wet-lab types."""
        panel = {"panel_type": "Blots", "label": "a", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"a": {"classification": "bioinformatics"}}}

        result = classify_panel_with_yolo_priority(panel, llm_cls)
        assert result == "wet_lab"

    def test_yolo_bioinformatics_types(self) -> None:
        """YOLO panel_type takes priority for bioinformatics types."""
        panel = {"panel_type": "Graphs", "label": "a", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"a": {"classification": "wet_lab"}}}

        result = classify_panel_with_yolo_priority(panel, llm_cls)
        assert result == "bioinformatics"

    def test_yolo_unknown_fallback_to_llm(self) -> None:
        """When YOLO is unknown, fall back to LLM classification."""
        panel = {"panel_type": "", "label": "a", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"a": {"classification": "wet_lab"}}}

        result = classify_panel_with_yolo_priority(panel, llm_cls)
        assert result == "wet_lab"

    def test_both_fail_returns_unknown(self) -> None:
        """When both YOLO and LLM fail, return unknown."""
        panel = {"panel_type": "", "label": "x", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"a": {"classification": "wet_lab"}}}

        result = classify_panel_with_yolo_priority(panel, llm_cls)
        assert result == "unknown"

    def test_missing_panel_label(self) -> None:
        """Handle panel without label."""
        panel = {"panel_type": "", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"a": {"classification": "wet_lab"}}}

        result = classify_panel_with_yolo_priority(panel, llm_cls)
        assert result == "unknown"


class TestClassifyPanelWithLlmPriority:
    """Test figure-aware panel classification."""

    def test_uses_figure_key_for_single_image_figure(self) -> None:
        panel = {"panel_type": "", "label": "a", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"figure": {"classification": "wet_lab"}}}
        fig_mapping = {"fig1": "Fig. 1"}

        result = classify_panel_with_llm_priority(panel, llm_cls, fig_mapping)

        assert result == "wet_lab"

    def test_llm_lookup_takes_priority_over_yolo_type(self) -> None:
        panel = {"panel_type": "Graphs", "label": "a", "parent_figure_id": "fig1"}
        llm_cls = {"Fig. 1": {"a": {"classification": "wet_lab"}}}
        fig_mapping = {"fig1": "Fig. 1"}

        result = classify_panel_with_llm_priority(panel, llm_cls, fig_mapping)

        assert result == "wet_lab"


# ---------------------------------------------------------------------------
# Filter wet-lab panels
# ---------------------------------------------------------------------------


class TestFilterWetLabPanels:
    """Test filtering panels to wet-lab only."""

    def test_filter_by_panel_classification(self) -> None:
        """Filter panels by pre-set panel_classification field."""
        panels = [
            {"panel_id": "p1", "panel_classification": "wet_lab"},
            {"panel_id": "p2", "panel_classification": "bioinformatics"},
            {"panel_id": "p3", "panel_classification": "mixed"},
            {"panel_id": "p4", "panel_classification": "other"},
            {"panel_id": "p5", "panel_classification": "unknown"},
        ]
        classifications = {}  # Not used when panel_classification is set

        result = filter_wet_lab_panels(panels, classifications)

        # Should include only wet_lab and mixed (unknown excluded)
        assert len(result) == 2
        result_ids = [p["panel_id"] for p in result]
        assert "p1" in result_ids  # wet_lab
        assert "p3" in result_ids  # mixed
        assert "p5" not in result_ids  # unknown — excluded
        assert "p2" not in result_ids  # bioinformatics
        assert "p4" not in result_ids  # other

    def test_include_unknown_panels(self) -> None:
        """Unknown panels are excluded (only wet_lab + mixed analyzed)."""
        panels = [
            {"panel_id": "p1", "panel_classification": "unknown"},
        ]
        classifications = {}

        result = filter_wet_lab_panels(panels, classifications)
        assert len(result) == 0

    def test_empty_classifications(self) -> None:
        """When classifications is empty, filter by panel_classification only."""
        panels = [
            {"panel_id": "p1", "panel_classification": "wet_lab"},
            {"panel_id": "p2", "panel_classification": "bioinformatics"},
        ]
        classifications = {}

        result = filter_wet_lab_panels(panels, classifications)
        # Only wet_lab should pass (bioinformatics filtered out)
        assert len(result) == 1
        assert result[0]["panel_id"] == "p1"

    def test_no_panel_classification_uses_llm(self) -> None:
        """When panel_classification not set, use LLM classifications."""
        panels = [
            {"panel_id": "p1", "label": "a"},
            {"panel_id": "p2", "label": "b"},
        ]
        classifications = {
            "classifications": {
                "Fig. 1": {
                    "a": {"classification": "wet_lab"},
                    "b": {"classification": "bioinformatics"},
                }
            }
        }

        result = filter_wet_lab_panels(panels, classifications)
        assert len(result) == 1
        assert result[0]["panel_id"] == "p1"

    def test_no_classification_found_defaults_to_unknown(self) -> None:
        """When no classification found, default to unknown (exclude panel)."""
        panels = [
            {"panel_id": "p1", "label": "z"},  # Not in classifications
        ]
        classifications = {
            "classifications": {
                "Fig. 1": {
                    "a": {"classification": "wet_lab"},
                }
            }
        }

        result = filter_wet_lab_panels(panels, classifications)
        # Panel with unknown classification should be excluded
        assert len(result) == 0

    def test_wet_lab_types_constant(self) -> None:
        """Verify WET_LAB_TYPES includes expected values."""
        assert "wet_lab" in WET_LAB_TYPES
        assert "mixed" in WET_LAB_TYPES
        assert "bioinformatics" not in WET_LAB_TYPES
        assert "other" not in WET_LAB_TYPES


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class TestRunFigureClassificationStep:
    """Test the pipeline step function."""

    def test_reuse_existing_artifact(self, tmp_path: Path) -> None:
        """Reuse existing figure_classification.json."""
        # Create existing artifact
        fc_path = tmp_path / "figure_classification.json"
        fc_path.write_text(json.dumps({"status": "ran"}))

        steps, manifest = run_figure_classification_step(
            workdir=tmp_path,
            force=False,
            progress=None,
        )

        assert len(steps) == 1
        assert steps[0].status == "reused"
        assert "figure_classification" in manifest

    def test_skip_when_full_md_missing(self, tmp_path: Path) -> None:
        """Skip when full.md is missing."""
        steps, manifest = run_figure_classification_step(
            workdir=tmp_path,
            force=False,
            progress=None,
        )

        assert len(steps) == 1
        assert steps[0].status == "skipped"
        assert manifest["figure_classification"]["status"] == "skipped"

    @pytest.mark.xfail(
        raises=Exception,
        reason="Known failure: engine.llm package shadowing, tracked in review-fix-decisions.md"
    )
    @patch("engine.llm.client.VeritasLLMClient")
    def test_runs_with_mock_client(self, mock_client_cls: MagicMock, tmp_path: Path) -> None:
        """Run classification with mocked LLM client."""
        # Create full.md
        full_md_path = tmp_path / "full.md"
        full_md_path.write_text("# Fig. 1 | Test figure.\na, Panel a.")

        # Mock LLM client
        mock_client = MagicMock()
        mock_client.chat_json.return_value = {
            "a": {"description": "Test panel", "classification": "wet_lab"}
        }
        mock_client_cls.return_value = mock_client

        steps, manifest = run_figure_classification_step(
            workdir=tmp_path,
            force=True,
            llm_client=mock_client,
            progress=None,
        )

        assert len(steps) == 1
        assert steps[0].status == "ran"
        assert manifest["figure_classification"]["status"] == "ran"
        assert manifest["figure_classification"]["figure_count"] == 1

        # Verify artifact was created
        fc_path = tmp_path / "figure_classification.json"
        assert fc_path.exists()
