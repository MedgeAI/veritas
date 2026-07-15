"""Benchmark case loader for VeritasBench.

Loads benchmark suites and cases from a structured directory layout.
Mock data is available only when the caller explicitly opts in.

Expected directory layout under base_path (default: benchmarks/veritasbench/):

    suites/
        {suite_name}.json   -- {"name": "...", "description": "...", "case_ids": [...]}
    cases/
        {case_id}/
            case.json       -- serialized BenchmarkCase fields
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from engine.reproduction.models import BenchmarkCase, ClaimRelationAnnotation

logger = logging.getLogger(__name__)

_DEFAULT_BASE_PATH = Path("benchmarks/veritasbench")


class BenchmarkCaseLoader:
    """Load benchmark data, failing loudly unless mock mode is explicit."""

    def __init__(
        self,
        base_path: Path | str | None = None,
        *,
        allow_mock: bool = False,
    ) -> None:
        if base_path is None:
            self.base_path = _DEFAULT_BASE_PATH
        else:
            self.base_path = Path(base_path)
        # Explicit mock mode is independent of the filesystem. This keeps
        # regression tests isolated even when the paper scaffold exists.
        self._use_mock = allow_mock
        if self._use_mock:
            logger.warning(
                "Explicit mock mode enabled for benchmark loader at %s",
                self.base_path,
            )
        elif not self.base_path.is_dir():
            raise FileNotFoundError(
                f"Benchmark directory not found: {self.base_path}. "
                "Pass allow_mock=True only for regression tests."
            )

    @property
    def using_mock(self) -> bool:
        """Whether this loader is serving synthetic regression data."""

        return self._use_mock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_suites(self) -> list[str]:
        """Return names of available suites (without .json extension)."""
        if self._use_mock:
            return ["mock_suite"]
        suites_dir = self.base_path / "suites"
        if not suites_dir.is_dir():
            return []
        return sorted(
            p.stem for p in suites_dir.iterdir() if p.is_file() and p.suffix == ".json"
        )

    def list_cases(self) -> list[str]:
        """Return IDs of available cases."""
        if self._use_mock:
            return ["mock_case_001", "mock_case_002", "mock_case_003"]
        cases_dir = self.base_path / "cases"
        if not cases_dir.is_dir():
            return []
        return sorted(
            p.name for p in cases_dir.iterdir() if p.is_dir() and (p / "case.json").is_file()
        )

    def load_suite(self, suite_name: str) -> list[BenchmarkCase]:
        """Load all cases in a suite.

        Args:
            suite_name: Suite name (matches filename stem under suites/).

        Returns:
            List of BenchmarkCase instances in declaration order.

        Raises:
            FileNotFoundError: If the suite JSON does not exist.
        """
        if self._use_mock:
            return self._load_mock_suite(suite_name)

        suite_path = self.base_path / "suites" / f"{suite_name}.json"
        if not suite_path.is_file():
            raise FileNotFoundError(f"Suite file not found: {suite_path}")

        suite_data = self._read_json(suite_path)
        case_ids: list[str] = suite_data.get("case_ids", [])
        if len(set(case_ids)) != len(case_ids):
            raise ValueError(f"Suite {suite_name!r} contains duplicate case IDs")

        cases: list[BenchmarkCase] = []
        missing: list[str] = []
        for case_id in case_ids:
            try:
                cases.append(self.load_case(case_id))
            except FileNotFoundError:
                missing.append(case_id)
        if missing:
            raise FileNotFoundError(
                f"Suite {suite_name!r} lists cases missing on disk: {', '.join(missing)}"
            )
        return cases

    def load_case(self, case_id: str) -> BenchmarkCase:
        """Load a single benchmark case.

        Args:
            case_id: Case identifier (matches directory name under cases/).

        Returns:
            BenchmarkCase instance.

        Raises:
            FileNotFoundError: If the case directory or case.json is missing.
        """
        if self._use_mock:
            return self._load_mock_case(case_id)

        case_dir = self.base_path / "cases" / case_id
        case_file = case_dir / "case.json"
        if not case_file.is_file():
            raise FileNotFoundError(f"Case file not found: {case_file}")

        data = self._read_json(case_file)
        return self._deserialize_case(data)

    # ------------------------------------------------------------------
    # Deserialization
    # ------------------------------------------------------------------

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _deserialize_case(data: dict[str, Any]) -> BenchmarkCase:
        """Convert a raw JSON dict into a BenchmarkCase."""
        claims = [
            _deserialize_annotation(c) for c in data.get("claims", [])
        ]
        return BenchmarkCase(
            case_id=data["case_id"],
            paper_title=data.get("paper_title", ""),
            paper_authors=data.get("paper_authors", []),
            artifacts=data.get("artifacts", {}),
            claims=claims,
            observations=data.get("observations", {}),
            metadata=data.get("metadata", {}),
        )

    # ------------------------------------------------------------------
    # Mock fallback
    # ------------------------------------------------------------------

    def _load_mock_suite(self, suite_name: str) -> list[BenchmarkCase]:
        from engine.reproduction.mock_data import generate_mock_benchmark_case

        return [
            generate_mock_benchmark_case(case_id=f"mock_case_{i:03d}", num_claims=5)
            for i in range(1, 4)
        ]

    def _load_mock_case(self, case_id: str) -> BenchmarkCase:
        from engine.reproduction.mock_data import generate_mock_benchmark_case

        return generate_mock_benchmark_case(case_id=case_id, num_claims=5)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _deserialize_annotation(data: dict[str, Any]) -> ClaimRelationAnnotation:
    """Convert a raw JSON dict into a ClaimRelationAnnotation."""
    return ClaimRelationAnnotation(
        annotation_id=data.get("annotation_id", ""),
        claim_id=data.get("claim_id", ""),
        claim_atom=data.get("claim_atom", ""),
        source_artifact=data.get("source_artifact", ""),
        target_artifact=data.get("target_artifact", ""),
        relation_type=data.get("relation_type", "L1"),  # type: ignore[arg-type]
        verdict=data.get("verdict", "consistent"),  # type: ignore[arg-type]
        discrepancy_type=data.get("discrepancy_type"),
        evidence_span=data.get("evidence_span"),
        severity=data.get("severity"),
        annotator_id=data.get("annotator_id", ""),
        annotation_timestamp=data.get("annotation_timestamp", ""),
        is_clean_claim=data.get("is_clean_claim", False),
    )
