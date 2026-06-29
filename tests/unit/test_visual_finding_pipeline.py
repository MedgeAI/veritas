"""Tests for visual finding pipeline: relationship builder + finding builder."""

from engine.static_audit.tools.visual_finding_pipeline import (
    build_relationships,
    build_visual_finding_clusters,
    build_visual_findings,
    visual_review_queue,
)
from engine.static_audit.visual_schemas import (
    ImageRelationship,
    VisualFinding,
    check_language_compliance,
)


# ---------------------------------------------------------------------------
# build_relationships tests
# ---------------------------------------------------------------------------


class TestBuildRelationships:
    """Tests for build_relationships function."""

    def test_merge_all_sources(self):
        """Merge from copy-move and dHash."""
        copy_move = {
            "relationships": [
                {
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "score": 0.85,
                    "match_method": "orb_ransac",
                    "inlier_count": 42,
                },
            ],
        }
        dhash = {
            "candidates": [
                {
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0002-02",
                    "score": 0.55,
                },
            ],
        }

        rels = build_relationships(copy_move, dhash_candidates=dhash)
        assert len(rels) == 2

        types = {r["source_type"] for r in rels}
        assert types == {"copy_move_single", "dhash_similar"}

    def test_copy_move_wins_over_dhash(self):
        """Copy-move takes priority over dHash for same pair (was: exact wins over copy-move)."""
        copy_move = {
            "relationships": [
                {
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "score": 0.9,
                    "match_method": "orb_ransac",
                    "inlier_count": 50,
                },
            ],
        }

        rels = build_relationships(copy_move)
        assert len(rels) == 1
        assert rels[0]["source_type"] == "copy_move_single"
        assert rels[0]["score"] == 0.9

    def test_dhash_does_not_override_copy_move(self):
        """Copy-move takes priority over dHash for same pair."""
        copy_move = {
            "relationships": [
                {
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "score": 0.6,
                    "match_method": "sift_ransac",
                    "inlier_count": 30,
                },
            ],
        }
        dhash = {
            "candidates": [
                {
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "score": 0.8,
                },
            ],
        }

        rels = build_relationships(copy_move, dhash_candidates=dhash)
        assert len(rels) == 1
        assert rels[0]["source_type"] == "copy_move_single"
        assert rels[0]["score"] == 0.6

    def test_empty_inputs(self):
        """All-None inputs produce empty list."""
        assert build_relationships(None) == []
        assert build_relationships(None, None, None) == []
        assert build_relationships({}) == []
        assert build_relationships({"relationships": []}) == []

    def test_skip_self_pairs(self):
        """Self-pairs are allowed for copy_move_single but skipped for other types."""
        # copy_move_single allows source == target (within-panel detection)
        copy_move_single = {
            "relationships": [
                {
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-01",
                    "source_type": "copy_move_single",
                    "score": 1.0,
                    "match_method": "rootsift_magsac_single",
                    "inlier_count": 100,
                },
            ],
        }
        rels = build_relationships(copy_move_single)
        assert len(rels) == 1

        # copy_move_cross with source == target should be skipped
        copy_move_cross = {
            "relationships": [
                {
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-01",
                    "source_type": "copy_move_cross",
                    "score": 0.75,
                    "match_method": "rootsift_magsac_cross",
                    "inlier_count": 50,
                },
            ],
        }
        rels = build_relationships(copy_move_cross)
        assert rels == []

    def test_relationship_ids_are_sequential(self):
        """Relationship IDs follow IR-NNNN pattern."""
        copy_move = {
            "relationships": [
                {
                    "source_panel_id": "A",
                    "target_panel_id": "B",
                    "score": 0.8,
                    "match_method": "orb",
                    "inlier_count": 10,
                },
                {
                    "source_panel_id": "C",
                    "target_panel_id": "D",
                    "score": 0.7,
                    "match_method": "orb",
                    "inlier_count": 8,
                },
            ],
        }
        rels = build_relationships(copy_move)
        assert rels[0]["relationship_id"] == "IR-0001"
        assert rels[1]["relationship_id"] == "IR-0002"

    def test_output_matches_image_relationship_schema(self):
        """Output dicts can be loaded into ImageRelationship and validate."""
        copy_move = {
            "relationships": [
                {
                    "source_panel_id": "PE-0001-01",
                    "target_panel_id": "PE-0001-02",
                    "score": 0.75,
                    "match_method": "orb_ransac",
                    "inlier_count": 25,
                    "homography": [
                        [1.0, 0.0, 10.0],
                        [0.0, 1.0, 20.0],
                        [0.0, 0.0, 1.0],
                    ],
                },
            ],
        }
        rels = build_relationships(copy_move)
        assert len(rels) == 1

        ir = ImageRelationship.from_dict(rels[0])
        errors = ir.validate()
        assert errors == [], f"Validation errors: {errors}"

    def test_copy_move_relationships_map_correctly(self):
        """Copy-move relationships produce correct panel IDs."""
        copy_move = {
            "relationships": [
                {
                    "source_panel_id": "FE-0001-01",
                    "target_panel_id": "FE-0002-01",
                    "score": 0.85,
                    "match_method": "rootsift",
                    "inlier_count": 42,
                }
            ]
        }

        rels = build_relationships(copy_move)

        assert len(rels) == 1
        assert rels[0]["source_type"] == "copy_move_single"
        assert rels[0]["source_panel_id"] == "FE-0001-01"
        assert rels[0]["target_panel_id"] == "FE-0002-01"

    def test_path_based_dhash_candidates_map_to_panels(self):
        dhash = {
            "candidates": [
                {
                    "source_panel_id": "FE-0001-01",
                    "target_panel_id": "FE-0002-01",
                    "distance": 2,
                    "max_distance": 8,
                }
            ]
        }

        rels = build_relationships(dhash_candidates=dhash)

        assert len(rels) == 1
        assert rels[0]["source_type"] == "dhash_similar"
        assert rels[0]["score"] == 0.75


# ---------------------------------------------------------------------------
# build_visual_findings tests
# ---------------------------------------------------------------------------


class TestBuildVisualFindings:
    """Tests for build_visual_findings function."""

    def _make_relationship(
        self,
        score: float = 0.8,
        source_type: str = "copy_move_single",
        src: str = "PE-0001-01",
        tgt: str = "PE-0001-02",
    ) -> dict:
        return {
            "relationship_id": "IR-0001",
            "source_type": source_type,
            "source_panel_id": src,
            "target_panel_id": tgt,
            "score": score,
            "match_method": "orb_ransac",
            "inlier_count": 30,
            "homography": None,
            "overlay_path": None,
            "metadata": {},
        }

    def test_risk_level_mapping(self):
        """Score thresholds map to correct risk levels."""
        cases = [
            (0.9, "critical"),
            (0.7, "critical"),
            (0.69, "high"),
            (0.4, "high"),
            (0.39, "medium"),
            (0.25, "medium"),
            (0.24, "low"),
        ]
        for score, expected_risk in cases:
            rel = self._make_relationship(score=score)
            findings = build_visual_findings(
                [rel],
                high_score_threshold=0.0,
            )
            assert len(findings) == 1
            assert findings[0]["risk_level"] == expected_risk, (
                f"score={score} -> expected {expected_risk}, "
                f"got {findings[0]['risk_level']}"
            )

    def test_below_threshold_excluded(self):
        """Relationships below threshold produce no findings."""
        rel = self._make_relationship(score=0.3)
        findings = build_visual_findings([rel], high_score_threshold=0.4)
        assert findings == []

    def test_custom_threshold(self):
        """Custom threshold filters correctly."""
        rels = [
            self._make_relationship(score=0.5, src="A", tgt="B"),
            self._make_relationship(score=0.2, src="C", tgt="D"),
        ]
        findings = build_visual_findings(rels, high_score_threshold=0.3)
        assert len(findings) == 1
        assert findings[0]["source_panel_id"] == "A"

    def test_benign_explanations_populated(self):
        """Each finding gets benign explanations from template."""
        rel = self._make_relationship(source_type="copy_move_single")
        findings = build_visual_findings([rel])
        assert len(findings) == 1
        assert len(findings[0]["benign_explanations"]) > 0
        assert all(isinstance(e, str) for e in findings[0]["benign_explanations"])

    def test_manual_review_questions_populated(self):
        """Each finding gets manual review questions from template."""
        rel = self._make_relationship(source_type="exact_duplicate")
        findings = build_visual_findings([rel])
        assert len(findings) == 1
        assert len(findings[0]["manual_review_questions"]) > 0
        assert all(isinstance(q, str) for q in findings[0]["manual_review_questions"])

    def test_language_compliance(self):
        """All text fields pass FORBIDDEN_PHRASES check."""
        rels = [
            self._make_relationship(
                score=0.8,
                source_type=st,
                src=f"PE-{i}-01",
                tgt=f"PE-{i}-02",
            )
            for i, st in enumerate(
                [
                    "copy_move_single",
                    "copy_move_cross",
                    "exact_duplicate",
                    "dhash_similar",
                ],
            )
        ]
        findings = build_visual_findings(rels, high_score_threshold=0.0)
        for f in findings:
            for text in (
                [f["summary"]] + f["benign_explanations"] + f["manual_review_questions"]
            ):
                violations = check_language_compliance(text)
                assert violations == [], (
                    f"Forbidden phrases in {f['finding_id']}: {violations}"
                )

    def test_output_matches_visual_finding_schema(self):
        """Output dicts can be loaded into VisualFinding and validate."""
        rel = self._make_relationship(score=0.85)
        findings = build_visual_findings([rel])
        assert len(findings) == 1

        vf = VisualFinding.from_dict(findings[0])
        errors = vf.validate()
        assert errors == [], f"Validation errors: {errors}"

    def test_unknown_source_type_skipped(self):
        """Relationships with source_type not in templates are skipped."""
        rel = self._make_relationship(source_type="cbir_similar")
        findings = build_visual_findings([rel], high_score_threshold=0.0)
        assert findings == []

    def test_panel_evidence_enriches_metadata(self):
        """Panel evidence metadata is included in finding metadata."""
        rel = self._make_relationship()
        panel_ev = [
            {
                "panel_id": "PE-0001-01",
                "parent_figure_id": "FE-0001",
                "label": "a",
                "bbox": [0, 0, 100, 100],
                "crop_path": "crops/a.png",
                "width": 100,
                "height": 100,
                "extraction_confidence": 0.9,
                "extraction_method": "contour",
                "metadata": {"parent_label": "Figure 1"},
            },
        ]
        findings = build_visual_findings([rel], panel_evidence=panel_ev)
        assert len(findings) == 1
        meta = findings[0]["metadata"]
        assert meta["source_panel_metadata"] == {"parent_label": "Figure 1"}
        assert meta["source_parent_figure_id"] == "FE-0001"
        assert meta["panel_extraction_quality"] == "panel_level"

    def test_whole_figure_fallback_caps_displayed_risk_and_score(self):
        rel = self._make_relationship(score=0.92)
        panel_ev = [
            {
                "panel_id": "PE-0001-01",
                "parent_figure_id": "FE-0001",
                "extraction_method": "whole_figure_fallback",
                "metadata": {},
            },
            {
                "panel_id": "PE-0001-02",
                "parent_figure_id": "FE-0001",
                "extraction_method": "contour_edge_detection",
                "metadata": {},
            },
        ]

        findings = build_visual_findings([rel], panel_evidence=panel_ev)

        assert len(findings) == 1
        assert findings[0]["risk_level"] == "medium"
        assert findings[0]["score"] == 0.39
        assert findings[0]["metadata"]["raw_score"] == 0.92
        assert (
            findings[0]["metadata"]["panel_extraction_quality"]
            == "whole_figure_fallback"
        )

    def test_graph_parent_id_relationship_is_resolved_and_not_critical(self):
        rel = self._make_relationship(
            score=0.9,
            source_type="copy_move_cross",
            src="figure-content-0042",
            tgt="figure-content-0043",
        )
        rel["match_method"] = "rootsift_magsac"
        panel_ev = [
            {
                "panel_id": "figure-content-0042-01",
                "parent_figure_id": "figure-content-0042",
                "panel_type": "Graphs",
                "extraction_method": "yolov5_panel_extractor",
                "metadata": {},
            },
            {
                "panel_id": "figure-content-0043-01",
                "parent_figure_id": "figure-content-0043",
                "panel_type": "Graphs",
                "extraction_method": "yolov5_panel_extractor",
                "metadata": {},
            },
        ]

        findings = build_visual_findings(
            [rel],
            high_score_threshold=0.4,
            panel_evidence=panel_ev,
        )

        assert len(findings) == 1
        assert findings[0]["risk_level"] in {"low", "medium"}
        metadata = findings[0]["metadata"]
        assert metadata["source_parent_figure_id"] == "figure-content-0042"
        assert metadata["target_parent_figure_id"] == "figure-content-0043"
        assert metadata["panel_type"] == "Graphs"
        assert "axes, text, legends" in metadata["confidence_adjustment"]

    def test_trufor_non_blot_microscopy_is_capped_at_medium(self):
        panel_ev = [
            {
                "panel_id": "figure-content-0005-01",
                "parent_figure_id": "figure-content-0005",
                "panel_type": "Body Imaging",
                "extraction_method": "yolov5_panel_extractor",
                "metadata": {},
            },
        ]

        findings = build_visual_findings(
            [],
            panel_evidence=panel_ev,
            forged_region_evidence=[
                {
                    "figure_id": "figure-content-0005",
                    "is_suspicious": True,
                    "integrity_score": 0.97,
                    "localization_map_path": "tru_for/pred.png",
                }
            ],
        )

        assert len(findings) == 1
        assert findings[0]["risk_level"] == "medium"
        assert findings[0]["overlay_path"] == "tru_for/pred.png"
        assert findings[0]["metadata"]["panel_type"] == "Body Imaging"
        assert findings[0]["metadata"]["risk_cap_reason"]

    def test_visual_finding_score_is_normalized_for_display(self):
        rel = self._make_relationship(score=13.0)

        findings = build_visual_findings([rel], high_score_threshold=0.4)

        assert len(findings) == 1
        assert findings[0]["score"] == 1.0
        assert findings[0]["risk_level"] == "critical"
        assert findings[0]["metadata"]["raw_score"] == 13.0
        assert findings[0]["metadata"]["normalized_score"] == 1.0
        assert "normalized" in findings[0]["metadata"]["confidence_adjustment"]

    def test_multiple_findings_get_unique_ids(self):
        """Each finding gets a unique sequential finding_id."""
        rels = [
            self._make_relationship(score=0.8, src=f"A{i}", tgt=f"B{i}")
            for i in range(3)
        ]
        findings = build_visual_findings(rels)
        ids = [f["finding_id"] for f in findings]
        assert len(set(ids)) == 3
        assert ids == ["VF-0001", "VF-0002", "VF-0003"]

    def test_summary_is_chinese(self):
        """Summary text is in Chinese as required."""
        rel = self._make_relationship(source_type="copy_move_single")
        findings = build_visual_findings([rel])
        assert "panel" in findings[0]["summary"] or "检测" in findings[0]["summary"]


def test_visual_finding_clusters_and_review_queue_group_connected_figures() -> None:
    findings = [
        {
            "finding_id": f"VF-{idx:04d}",
            "category": "copy_move_cross",
            "risk_level": "high",
            "summary": "跨图 copy-move 检测发现 panel 存在相似区域",
            "source_panel_id": f"FE-0001-0{idx}",
            "target_panel_id": f"FE-0002-0{idx}",
            "relationship_id": f"IR-{idx:04d}",
            "score": 0.82,
            "benign_explanations": ["共享对照可能解释相似性"],
            "manual_review_questions": ["检查图注是否描述不同实验"],
            "metadata": {
                "match_method": "orb_ransac",
                "panel_extraction_quality": "panel_level",
                "source_parent_figure_id": "FE-0001",
                "target_parent_figure_id": "FE-0002",
            },
        }
        for idx in range(1, 4)
    ]
    findings.append(
        {
            "finding_id": "VF-0004",
            "category": "copy_move_cross",
            "risk_level": "high",
            "summary": "跨图 copy-move 检测发现 panel 存在相似区域",
            "source_panel_id": "FE-0002-04",
            "target_panel_id": "FE-0003-01",
            "relationship_id": "IR-0004",
            "score": 0.8,
            "benign_explanations": ["共享对照可能解释相似性"],
            "manual_review_questions": ["检查图注是否描述不同实验"],
            "metadata": {
                "match_method": "orb_ransac",
                "panel_extraction_quality": "panel_level",
                "source_parent_figure_id": "FE-0002",
                "target_parent_figure_id": "FE-0003",
            },
        }
    )

    clusters = build_visual_finding_clusters(findings)
    queue = visual_review_queue(clusters)

    assert len(clusters) == 1
    assert clusters[0]["finding_count"] == 4
    assert clusters[0]["relationship_count"] == 4
    assert clusters[0]["figure_ids"] == ["FE-0001", "FE-0002", "FE-0003"]
    assert clusters[0]["component_figure_count"] == 3
    assert clusters[0]["panel_extraction_quality"] == "panel_level"
    assert len(queue) == 1
    assert queue[0]["task_id"] == "VRT-001"
    assert queue[0]["cluster_id"] == clusters[0]["cluster_id"]
