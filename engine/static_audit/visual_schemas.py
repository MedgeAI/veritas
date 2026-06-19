"""Visual evidence schemas for panel-level forensics.

This module defines the canonical data structures for visual evidence in Veritas:
- FigureEvidence: canonical figure-level image evidence from PDF parsing
- PanelEvidence: detected panel crop with bbox, label, parent figure
- VisualFinding: candidate issue from copy-move, duplicate, or review
- ImageRelationship: relationship between two panels with score and method

All schemas follow the Evidence First principle: no visual finding may appear
in the report without evidence refs and a manual review note.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

VISUAL_SCHEMA_VERSION = "1.0"


@dataclass
class ForgedRegionEvidence:
    """TruFor deep-learning forgery detection result for a figure or panel."""
    forged_region_evidence_id: str
    figure_id: str
    status: Literal["completed", "skipped", "failed"]
    skip_reason: str | None = None
    integrity_score: float | None = None
    is_suspicious: bool = False
    localization_map_path: str | None = None
    confidence_map_path: str | None = None
    image_width: int = 0
    image_height: int = 0
    inference_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForgedRegionEvidence:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def validate(self) -> list[str]:
        errors = []
        if not self.forged_region_evidence_id:
            errors.append("forged_region_evidence_id is required")
        if not self.figure_id:
            errors.append("figure_id is required")
        if self.integrity_score is not None and not 0.0 <= self.integrity_score <= 1.0:
            errors.append(f"integrity_score must be in [0, 1], got {self.integrity_score}")
        return errors


# Forbidden phrases that must never appear in reports or findings
# Software-level constraint; final judgment always requires human review
FORBIDDEN_PHRASES = [
    "proves fraud",
    "proves manipulation",
    "confirms fabrication",
    "definitive evidence of",
    "conclusive proof of",
    "guilty of",
    "committed fraud",
    "intentionally manipulated",
    "deliberately forged",
    "scientific misconduct confirmed",
    "确认造假",
    "学术不端成立",
    "数据伪造",
    "故意篡改",
]


def check_language_compliance(text: str) -> list[str]:
    """Check text for forbidden phrases.

    Returns list of violated phrases found in text (empty if compliant).
    """
    violations = []
    lower = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in lower:
            violations.append(phrase)
    return violations


@dataclass
class FigureEvidence:
    """Canonical figure-level image evidence from PDF parsing or extraction.

    Attributes:
        figure_id: Stable identifier, e.g. "FE-0001"
        source_image_path: Relative path to image file in workdir, e.g. "images/Figure1.png"
        label: Figure label from caption, e.g. "Figure 1"
        caption: Extracted caption text
        page_number: Page number in PDF (1-indexed), or None if unknown
        bbox: Bounding box in page coordinates [x, y, w, h], or None
        width: Image width in pixels
        height: Image height in pixels
        panel_count: Number of detected panels in this figure
        metadata: Additional provenance or extraction metadata
    """
    figure_id: str
    source_image_path: str
    label: str
    caption: str
    page_number: int | None
    bbox: list[int] | None
    width: int
    height: int
    panel_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FigureEvidence:
        """Deserialize from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def validate(self) -> list[str]:
        """Validate figure evidence invariants.

        Returns list of validation errors (empty if valid).
        """
        errors = []
        if not self.figure_id:
            errors.append("figure_id is required")
        if not self.source_image_path:
            errors.append("source_image_path is required")
        if self.width <= 0:
            errors.append(f"width must be positive, got {self.width}")
        if self.height <= 0:
            errors.append(f"height must be positive, got {self.height}")
        if self.panel_count < 0:
            errors.append(f"panel_count must be non-negative, got {self.panel_count}")
        if self.bbox is not None:
            if len(self.bbox) != 4:
                errors.append(f"bbox must have 4 elements [x, y, w, h], got {len(self.bbox)}")
            elif any(v < 0 for v in self.bbox):
                errors.append("bbox coordinates must be non-negative")
        return errors


@dataclass
class PanelEvidence:
    """Detected panel crop with bbox, label, parent figure, and crop path.

    Attributes:
        panel_id: Stable identifier, e.g. "PE-0001-01" (parent figure + index)
        parent_figure_id: Reference to parent FigureEvidence.figure_id
        label: Panel label, e.g. "a", "b", "c"
        bbox: Bounding box in figure coordinates [x, y, w, h]
        crop_path: Relative path to cropped panel image
        width: Panel width in pixels
        height: Panel height in pixels
        extraction_confidence: Confidence score 0.0-1.0 from extraction algorithm
        extraction_method: Method used, e.g. "yolov5_panel_extractor"
        panel_type: Semantic panel type from YOLOv5 classifier (e.g. "Blots", "Graphs")
        metadata: Additional provenance or extraction metadata
    """
    PANEL_TYPES = ("Blots", "Graphs", "Microscopy", "Body Imaging", "Flow Cytometry")

    panel_id: str
    parent_figure_id: str
    label: str
    bbox: list[int]
    crop_path: str
    width: int
    height: int
    extraction_confidence: float
    extraction_method: str
    panel_type: str | None = None
    paper_figure_label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PanelEvidence:
        """Deserialize from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def validate(self) -> list[str]:
        """Validate panel evidence invariants.

        Returns list of validation errors (empty if valid).
        """
        errors = []
        if not self.panel_id:
            errors.append("panel_id is required")
        if not self.parent_figure_id:
            errors.append("parent_figure_id is required")
        if not self.label:
            errors.append("label is required")
        if len(self.bbox) != 4:
            errors.append(f"bbox must have 4 elements [x, y, w, h], got {len(self.bbox)}")
        elif any(v < 0 for v in self.bbox):
            errors.append("bbox coordinates must be non-negative")
        if not self.crop_path:
            errors.append("crop_path is required")
        if self.width <= 0:
            errors.append(f"width must be positive, got {self.width}")
        if self.height <= 0:
            errors.append(f"height must be positive, got {self.height}")
        if not 0.0 <= self.extraction_confidence <= 1.0:
            errors.append(
                f"extraction_confidence must be in [0.0, 1.0], got {self.extraction_confidence}"
            )
        if self.panel_type is not None and self.panel_type not in self.PANEL_TYPES:
            errors.append(
                f"panel_type must be one of {self.PANEL_TYPES}, got {self.panel_type!r}"
            )
        return errors


@dataclass
class VisualFinding:
    """Candidate issue produced by copy-move, duplicate, TruFor, or manual review.

    Attributes:
        finding_id: Stable identifier, e.g. "VF-0001"
        category: Finding category, e.g. "copy_move_single", "copy_move_cross",
            "forged_region_suspicious"
        risk_level: Risk level from RiskLevel literal
        summary: Human-readable summary of the finding
        source_panel_id: Reference to source PanelEvidence.panel_id
            (empty for forged_region_suspicious findings)
        target_panel_id: Reference to target PanelEvidence.panel_id
            (empty for forged_region_suspicious findings)
        relationship_id: Reference to ImageRelationship.relationship_id
            (empty for forged_region_suspicious findings)
        score: Confidence score 0.0-1.0
        benign_explanations: List of benign explanations to consider
        manual_review_questions: List of questions for manual review
        overlay_path: Relative path to overlay visualization, or None
        metadata: Additional provenance or analysis metadata
    """
    finding_id: str
    category: Literal[
        "copy_move_single",
        "copy_move_cross",
        "exact_duplicate",
        "dhash_similar",
        "local_reuse",
        "forged_region_suspicious",
        "overlap_reuse_cross_panel",
    ]
    risk_level: Literal["info", "low", "medium", "high", "critical"]
    summary: str
    source_panel_id: str = ""
    target_panel_id: str = ""
    relationship_id: str = ""
    score: float = 0.0
    benign_explanations: list[str] = field(default_factory=list)
    manual_review_questions: list[str] = field(default_factory=list)
    overlay_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VisualFinding:
        """Deserialize from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def validate(self) -> list[str]:
        """Validate visual finding invariants.

        Returns list of validation errors (empty if valid).
        """
        errors = []
        if not self.finding_id:
            errors.append("finding_id is required")
        if not self.category:
            errors.append("category is required")
        if self.risk_level not in {"info", "low", "medium", "high", "critical"}:
            errors.append(f"invalid risk_level: {self.risk_level}")
        if not self.summary:
            errors.append("summary is required")
        if self.category != "forged_region_suspicious":
            if not self.source_panel_id:
                errors.append("source_panel_id is required")
            if not self.target_panel_id:
                errors.append("target_panel_id is required")
            if not self.relationship_id:
                errors.append("relationship_id is required")
        if not 0.0 <= self.score <= 1.0:
            errors.append(f"score must be in [0.0, 1.0], got {self.score}")
        # Check language compliance
        violations = check_language_compliance(self.summary)
        if violations:
            errors.append(f"summary contains forbidden phrases: {violations}")
        for explanation in self.benign_explanations:
            violations = check_language_compliance(explanation)
            if violations:
                errors.append(f"benign_explanation contains forbidden phrases: {violations}")
        for question in self.manual_review_questions:
            violations = check_language_compliance(question)
            if violations:
                errors.append(f"manual_review_question contains forbidden phrases: {violations}")
        return errors


@dataclass
class ImageRelationship:
    """Relationship between two panels with source type, score, and method.

    Attributes:
        relationship_id: Stable identifier, e.g. "IR-0001"
        source_type: Relationship source type
        source_panel_id: Reference to source PanelEvidence.panel_id
        target_panel_id: Reference to target PanelEvidence.panel_id
        score: Confidence score 0.0-1.0
        match_method: Method used, e.g. "rootsift_magsac_single", "rootsift_magsac_cross"
        inlier_count: Number of inlier matches from geometric verification
        homography: 3x3 homography matrix, or None
        overlay_path: Relative path to overlay visualization, or None
        flip_detected: Whether horizontal flip was detected (cross-image only)
        metadata: Additional provenance or analysis metadata
    """
    relationship_id: str
    source_type: Literal[
        "copy_move_single",
        "copy_move_cross",
        "exact_duplicate",
        "dhash_similar",
        "cbir_similar",
        "overlap_reuse_cross_panel",
    ]
    source_panel_id: str
    target_panel_id: str
    score: float
    match_method: str
    inlier_count: int
    homography: list[list[float]] | None = None
    overlay_path: str | None = None
    flip_detected: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImageRelationship:
        """Deserialize from dictionary."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def validate(self) -> list[str]:
        """Validate image relationship invariants.

        Returns list of validation errors (empty if valid).
        """
        errors = []
        if not self.relationship_id:
            errors.append("relationship_id is required")
        if not self.source_type:
            errors.append("source_type is required")
        if not self.source_panel_id:
            errors.append("source_panel_id is required")
        if not self.target_panel_id:
            errors.append("target_panel_id is required")
        if self.source_panel_id == self.target_panel_id and self.source_type != "copy_move_single":
            errors.append("source_panel_id and target_panel_id must be different (unless copy_move_single)")
        if not 0.0 <= self.score <= 1.0:
            errors.append(f"score must be in [0.0, 1.0], got {self.score}")
        if not self.match_method:
            errors.append("match_method is required")
        if self.inlier_count < 0:
            errors.append(f"inlier_count must be non-negative, got {self.inlier_count}")
        if self.homography is not None:
            if len(self.homography) != 3 or any(len(row) != 3 for row in self.homography):
                errors.append("homography must be a 3x3 matrix")
        return errors
