"""Phase 5 — Anti-overfitting enforcement.

Five mandatory rules that every new detection capability must pass
before being registered in the capability catalog.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AntiOverfitReport:
    """Result of anti-overfit checks on a new capability."""

    capability_id: str
    passed: bool
    violations: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "passed": self.passed,
            "violations": self.violations,
            "warnings": self.warnings,
        }


_HARDCODED_PATTERNS = [
    re.compile(r"(?i)fig(?:ure)?\.?\s*\d+[a-z]?"),
    re.compile(r"(?i)MOESM\d+"),
    re.compile(r"(?i)sheet\s*['\"]?\s*\d+"),
    re.compile(r"(?i)row\s*\d+"),
    re.compile(r"(?i)pair\s*\d+"),
]


class AntiOverfitChecker:
    """Five-rule anti-overfitting enforcement."""

    def check_all(
        self,
        capability_id: str,
        code: str,
        impl_path: Path | None = None,
        test_path: Path | None = None,
        validation_papers: list[str] | None = None,
        distribution_path: Path | None = None,
    ) -> AntiOverfitReport:
        """Run all five checks and return a consolidated report."""
        violations: list[str] = []
        warnings: list[str] = []

        v1 = self.check_generic_interface(code)
        violations.extend(v1)

        v2 = self.check_no_hardcoding(code)
        violations.extend(v2)

        v3_pass, v3_msg = self.check_cross_paper_validation(validation_papers or [])
        if not v3_pass:
            violations.append(v3_msg)

        v4_pass, v4_msg = self.check_threshold_distribution(distribution_path)
        if not v4_pass:
            warnings.append(v4_msg)

        v5_pass, v5_msg = self.check_test_first(test_path, impl_path)
        if not v5_pass:
            warnings.append(v5_msg)

        return AntiOverfitReport(
            capability_id=capability_id,
            passed=len(violations) == 0,
            violations=violations,
            warnings=warnings,
        )

    def check_generic_interface(self, code: str) -> list[str]:
        """Rule 1: No paper-specific parameters in function signatures.

        Checks for parameters that look paper-specific (e.g. paper_dir,
        specific figure IDs). Allows generic parameters (workdir, path).
        """
        violations: list[str] = []
        sig_pattern = re.compile(r"def\s+\w+\s*\(([^)]*)\)")
        for match in sig_pattern.finditer(code):
            params = match.group(1)
            if re.search(r"(?i)(fig(?:ure)?_id|sheet_name|specific_paper)", params):
                violations.append(
                    f"Rule 1 (通用接口): function signature contains paper-specific "
                    f"parameter in: def {match.group(0)[:60]}..."
                )
        return violations

    def check_no_hardcoding(self, code: str) -> list[str]:
        """Rule 2: No hardcoded figure numbers, sheet names, row offsets."""
        violations: list[str] = []
        for line_no, line in enumerate(code.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            for pattern in _HARDCODED_PATTERNS:
                if pattern.search(line):
                    match_text = pattern.search(line).group(0)
                    violations.append(
                        f"Rule 2 (无硬编码): line {line_no} contains hardcoded "
                        f"value '{match_text}'"
                    )
                    break
        return violations

    def check_cross_paper_validation(
        self, validation_papers: list[str]
    ) -> tuple[bool, str]:
        """Rule 3: At least 3 papers validated (1 ground truth + 2 control)."""
        if len(validation_papers) < 3:
            return (
                False,
                f"Rule 3 (跨论文验证): only {len(validation_papers)} validation paper(s) "
                f"provided; need at least 3 (1 ground truth + 2 control)",
            )
        return (True, "")

    def check_threshold_distribution(
        self, distribution_path: Path | None
    ) -> tuple[bool, str]:
        """Rule 4: Threshold derived from statistical distribution."""
        if distribution_path is None or not distribution_path.exists():
            return (
                False,
                "Rule 4 (阈值分布): distribution_analysis.md not found; "
                "threshold should be derived from statistical analysis",
            )
        return (True, "")

    def check_test_first(
        self, test_path: Path | None, impl_path: Path | None
    ) -> tuple[bool, str]:
        """Rule 5: Test file created before implementation file."""
        if test_path is None or impl_path is None:
            return (True, "")
        if not test_path.exists() or not impl_path.exists():
            return (True, "")
        test_mtime = test_path.stat().st_mtime
        impl_mtime = impl_path.stat().st_mtime
        if test_mtime > impl_mtime:
            return (
                False,
                f"Rule 5 (测试先行): test file ({test_path.name}) created after "
                f"implementation ({impl_path.name}); consider test-first workflow",
            )
        return (True, "")
