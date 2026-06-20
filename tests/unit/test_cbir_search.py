"""Tests for the visual.cbir_search tool and its Agent investigation integration."""

from __future__ import annotations

import json
from pathlib import Path


from PIL import Image

from engine.static_audit.tools.cbir_search import (
    _compute_hsv_histogram,
    _cosine_similarity,
    _FEATURE_DIM,
    _is_valid_panel,
    _panel_image_path,
    run_cbir_search,
)
from engine.tools.registry import TOOLS, TOOL_ID_CBIR_SEARCH, ExecutionPhase


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestCbirSearchRegistry:
    def test_tool_registered(self):
        assert TOOL_ID_CBIR_SEARCH in TOOLS

    def test_tool_definition_fields(self):
        tool = TOOLS[TOOL_ID_CBIR_SEARCH]
        assert tool.tool_id == "visual.cbir_search"
        assert tool.step_key == "visual_cbir_search"
        assert tool.output_artifacts == ("visual/cbir_search.json",)
        assert tool.execution_phase == ExecutionPhase.AGENT_SELECTABLE
        assert tool.agent_selectable is True
        assert tool.deterministic is True

    def test_tool_not_in_mandatory_baseline(self):
        from engine.tools.registry import (
            PAPER_STATIC_AUDIT_TOOL_IDS,
            STATIC_AUDIT_V1_TOOL_IDS,
        )

        assert TOOL_ID_CBIR_SEARCH not in PAPER_STATIC_AUDIT_TOOL_IDS
        assert TOOL_ID_CBIR_SEARCH not in STATIC_AUDIT_V1_TOOL_IDS

    def test_tool_in_investigation_catalog(self):
        from engine.tools.registry import tool_catalog_for_investigation

        catalog = tool_catalog_for_investigation()
        exposed = {item["tool_id"] for item in catalog}
        assert TOOL_ID_CBIR_SEARCH in exposed

    def test_param_schema(self):
        tool = TOOLS[TOOL_ID_CBIR_SEARCH]
        assert "top_k" in tool.param_schema
        assert "min_score" in tool.param_schema
        assert "max_pairs" in tool.param_schema


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_is_valid_panel_with_panel_id(self):
        assert _is_valid_panel({"panel_id": "p1", "crop_path": "/tmp/x.png"}) is True

    def test_is_valid_panel_without_panel_id(self):
        assert _is_valid_panel({"crop_path": "/tmp/x.png"}) is False

    def test_panel_image_path_prefers_crop_path(self):
        panel = {
            "crop_path": "visual/crops/p1.png",
            "source_image_path": "visual/images/fig1.png",
        }
        assert _panel_image_path(panel) == Path("visual/crops/p1.png")

    def test_panel_image_path_falls_back_to_source(self):
        panel = {"source_image_path": "visual/images/fig1.png"}
        assert _panel_image_path(panel) == Path("visual/images/fig1.png")

    def test_panel_image_path_none_when_empty(self):
        assert _panel_image_path({}) is None
        assert _panel_image_path({"panel_id": "p1"}) is None

    def test_compute_hsv_histogram_deterministic(self):
        img = Image.new("RGB", (64, 64), (100, 150, 200))
        h1 = _compute_hsv_histogram(img)
        h2 = _compute_hsv_histogram(img)
        assert h1 == h2

    def test_compute_hsv_histogram_dimension(self):
        img = Image.new("RGB", (32, 32), (255, 0, 0))
        h = _compute_hsv_histogram(img)
        assert len(h) == _FEATURE_DIM

    def test_compute_hsv_histogram_unit_norm(self):
        import math

        img = Image.new("RGB", (32, 32), (0, 255, 0))
        h = _compute_hsv_histogram(img)
        norm = math.sqrt(sum(x * x for x in h))
        assert abs(norm - 1.0) < 1e-6

    def test_cosine_similarity_identical(self):
        import math

        v = [0.1, 0.2, 0.3, 0.4]
        norm = math.sqrt(sum(x * x for x in v))
        unit = [x / norm for x in v]
        assert abs(_cosine_similarity(unit, unit) - 1.0) < 1e-9

    def test_cosine_similarity_orthogonal(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(_cosine_similarity(a, b)) < 1e-9


# ---------------------------------------------------------------------------
# Functional tests
# ---------------------------------------------------------------------------


class TestRunCbirSearch:
    def test_empty_panels_returns_skipped(self):
        result = run_cbir_search([], workdir=Path("/nonexistent"))
        assert result["status"] == "skipped"
        assert result["pair_count"] == 0
        assert result["pairs"] == []

    def test_single_panel_no_pairs(self, tmp_path: Path):
        img_path = tmp_path / "panel.png"
        Image.new("RGB", (64, 64), (100, 150, 200)).save(img_path)
        panels = [{"panel_id": "p1", "crop_path": str(img_path)}]
        result = run_cbir_search(panels, workdir=tmp_path)
        assert result["status"] == "ran"
        assert result["pair_count"] == 0

    def test_identical_images_high_similarity(self, tmp_path: Path):
        """Two panels with identical images should have cosine similarity ~1.0."""
        img1 = tmp_path / "p1.png"
        img2 = tmp_path / "p2.png"
        Image.new("RGB", (64, 64), (200, 100, 50)).save(img1)
        Image.new("RGB", (64, 64), (200, 100, 50)).save(img2)
        panels = [
            {"panel_id": "p1", "parent_figure_id": "fig1", "crop_path": str(img1)},
            {"panel_id": "p2", "parent_figure_id": "fig1", "crop_path": str(img2)},
        ]
        result = run_cbir_search(panels, workdir=tmp_path, min_score=0.90)
        assert result["status"] == "ran"
        assert result["pair_count"] == 1
        pair = result["pairs"][0]
        assert pair["score"] > 0.99
        assert pair["source_type"] == "cbir_similar"
        assert pair["method"] == "hsv_histogram_cosine"

    def test_different_images_below_threshold(self, tmp_path: Path):
        """Panels with very different colors should not produce pairs above threshold."""
        img1 = tmp_path / "p1.png"
        img2 = tmp_path / "p2.png"
        Image.new("RGB", (64, 64), (255, 0, 0)).save(img1)
        Image.new("RGB", (64, 64), (0, 0, 255)).save(img2)
        panels = [
            {"panel_id": "p1", "crop_path": str(img1)},
            {"panel_id": "p2", "crop_path": str(img2)},
        ]
        result = run_cbir_search(panels, workdir=tmp_path, min_score=0.95)
        assert result["status"] == "ran"
        assert result["pair_count"] == 0

    def test_missing_image_skipped(self, tmp_path: Path):
        panels = [
            {"panel_id": "p1", "crop_path": str(tmp_path / "nonexistent.png")},
            {"panel_id": "p2", "crop_path": str(tmp_path / "also_missing.png")},
        ]
        result = run_cbir_search(panels, workdir=tmp_path)
        assert result["status"] == "ran"
        assert result["skipped_panels"] == 2
        assert result["pair_count"] == 0

    def test_max_pairs_limit(self, tmp_path: Path):
        """max_pairs should cap the output."""
        for i in range(10):
            img_path = tmp_path / f"p{i}.png"
            Image.new("RGB", (64, 64), (100, 100, 100)).save(img_path)
        panels = [
            {"panel_id": f"p{i}", "crop_path": str(tmp_path / f"p{i}.png")}
            for i in range(10)
        ]
        result = run_cbir_search(panels, workdir=tmp_path, min_score=0.50, max_pairs=3)
        assert result["pair_count"] <= 3

    def test_output_schema(self, tmp_path: Path):
        img_path = tmp_path / "p1.png"
        Image.new("RGB", (64, 64), (128, 128, 128)).save(img_path)
        panels = [{"panel_id": "p1", "crop_path": str(img_path)}]
        result = run_cbir_search(panels, workdir=tmp_path)
        assert "schema_version" in result
        assert "created_by" in result
        assert "status" in result
        assert "method" in result
        assert "panel_count" in result
        assert "pair_count" in result
        assert "pairs" in result
        assert "errors" in result
        assert "limitations" in result

    def test_pair_deduplication(self, tmp_path: Path):
        """The same pair should not appear twice (p1->p2 and p2->p1)."""
        img1 = tmp_path / "p1.png"
        img2 = tmp_path / "p2.png"
        Image.new("RGB", (64, 64), (100, 100, 100)).save(img1)
        Image.new("RGB", (64, 64), (101, 101, 101)).save(img2)
        panels = [
            {"panel_id": "p1", "crop_path": str(img1)},
            {"panel_id": "p2", "crop_path": str(img2)},
        ]
        result = run_cbir_search(panels, workdir=tmp_path, min_score=0.50, top_k=5)
        pair_keys = set()
        for pair in result["pairs"]:
            key = tuple(sorted([pair["source_panel_id"], pair["target_panel_id"]]))
            assert key not in pair_keys, f"Duplicate pair: {key}"
            pair_keys.add(key)


# ---------------------------------------------------------------------------
# Investigation dispatch integration
# ---------------------------------------------------------------------------


class TestCbirInvestigationDispatch:
    """Test that TOOL_ID_CBIR_SEARCH is handled in the investigation dispatch."""

    def test_dispatch_resolves_tool_id(self):
        """The tool_id constant should be importable from investigation_dispatch."""
        from engine.static_audit.investigation_dispatch import (
            TOOL_ID_CBIR_SEARCH as dispatched_id,
        )

        assert dispatched_id == "visual.cbir_search"

    def test_dispatch_runs_cbir_tool(self, tmp_path: Path):
        """run_investigation_tool_action should handle TOOL_ID_CBIR_SEARCH."""
        from engine.static_audit.investigation import InvestigationAction
        from engine.static_audit.investigation_dispatch import (
            run_investigation_tool_action,
        )

        # Create fake panel evidence with real images
        visual_dir = tmp_path / "visual"
        visual_dir.mkdir()
        img1 = visual_dir / "panel_p1.png"
        img2 = visual_dir / "panel_p2.png"
        Image.new("RGB", (64, 64), (100, 150, 200)).save(img1)
        Image.new("RGB", (64, 64), (100, 150, 200)).save(img2)

        panel_evidence = {
            "panels": [
                {"panel_id": "p1", "parent_figure_id": "fig1", "crop_path": str(img1)},
                {"panel_id": "p2", "parent_figure_id": "fig1", "crop_path": str(img2)},
            ]
        }
        (visual_dir / "panel_evidence.json").write_text(json.dumps(panel_evidence))

        action = InvestigationAction(
            round_id=1,
            action_id="IA-01",
            tool_id=TOOL_ID_CBIR_SEARCH,
            params={"top_k": 3, "min_score": 0.50, "max_pairs": 10},
            hypothesis="test cbir",
            depends_on_artifacts=["visual/panel_evidence.json"],
            expected_evidence_type="image_similarity",
        )

        step, outputs = run_investigation_tool_action(
            action=action,
            workdir=tmp_path,
            source_data_dir=None,
            env={},
            force=True,
            progress=None,
        )

        assert step.status in ("ran", "failed")
        assert len(outputs) == 1
        output_path = Path(outputs[0])
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["status"] in ("ran", "failed")
        assert "pair_count" in data
