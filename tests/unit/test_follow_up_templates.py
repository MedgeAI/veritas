from __future__ import annotations

from engine.follow_up.templates import generate_fallback_questions


def test_duplicate_numeric_columns_template_uses_real_metadata_fields() -> None:
    questions = generate_fallback_questions(
        {
            "finding_id": "SRC-1",
            "category": "duplicate_numeric_columns",
            "summary": "duplicate columns",
            "metadata": {
                "workbook": "source.xlsx",
                "sheet": "Fig2",
                "column_labels": ["E", "G"],
                "equal_rows": 18,
                "overlap_rows": 18,
            },
        }
    )

    assert questions == [
        "source.xlsx / Fig2 中列 E, G 在 18/18 行数据内完全相同，"
        "这是同一实验的重复测量，还是数据录入时的复制？"
    ]


def test_pair_forensics_template_uses_row_offset_and_support() -> None:
    questions = generate_fallback_questions(
        {
            "category": "paired_ratio_reuse",
            "summary": "paired ratio reuse",
            "metadata": {
                "workbook": "source.xlsx",
                "sheet": "Sheet1",
                "column_pair": ["B", "C"],
                "matched_pairs": 20,
                "overlap_pairs": 20,
                "row_offset": 10,
                "ratio_places": 4,
            },
        }
    )

    assert "source.xlsx / Sheet1" in questions[0]
    assert "B, C" in questions[0]
    assert "20/20 对" in questions[0]
    assert "row_offset=10" in questions[0]
    assert "ratio_places=4" in questions[0]


def test_copy_move_template_merges_nested_metadata() -> None:
    questions = generate_fallback_questions(
        {
            "category": "copy_move_cross",
            "summary": "copy move",
            "metadata": {
                "source_panel_id": "panel-A",
                "target_panel_id": "panel-B",
                "score": 0.87,
                "overlay_path": "visual/overlap/pair.png",
                "metadata": {"match_method": "rootsift_magsac"},
            },
        }
    )

    assert "panel-A, panel-B" in questions[0]
    assert "score=0.870" in questions[0]
    assert "method=rootsift_magsac" in questions[0]
    assert "overlay=visual/overlap/pair.png" in questions[0]
