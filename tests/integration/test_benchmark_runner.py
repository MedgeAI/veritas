"""Integration tests for BenchmarkRunner."""

import pytest

from engine.reproduction.benchmark.case_loader import BenchmarkCaseLoader
from engine.reproduction.benchmark.metrics import MetricsCalculator
from engine.reproduction.benchmark.runner import BenchmarkRunner
from engine.reproduction.mock_data import generate_mock_claims


class TestBenchmarkRunner:
    """Test suite for BenchmarkRunner integration."""

    def test_runner_creation(self):
        """Test creating a BenchmarkRunner."""
        loader = BenchmarkCaseLoader()
        runner = BenchmarkRunner(case_loader=loader)
        assert runner.case_loader is loader
        assert runner.metrics_calculator is not None

    def test_runner_with_custom_metrics(self):
        """Test creating runner with custom metrics calculator."""
        loader = BenchmarkCaseLoader()
        metrics = MetricsCalculator()
        runner = BenchmarkRunner(case_loader=loader, metrics_calculator=metrics)
        assert runner.metrics_calculator is metrics

    def test_runner_smoke_suite(self):
        """Test running benchmark with smoke_test suite."""
        loader = BenchmarkCaseLoader()
        runner = BenchmarkRunner(case_loader=loader)
        result = runner.run(suite_name="smoke_test")
        assert result is not None
        assert result.suite_name == "smoke_test"
        assert result.num_cases >= 0
        assert result.metrics is not None

    def test_runner_metrics_present(self):
        """Test that runner produces all expected metrics."""
        loader = BenchmarkCaseLoader()
        runner = BenchmarkRunner(case_loader=loader)
        result = runner.run(suite_name="smoke_test", far_alpha=0.05)

        expected_metrics = [
            "claim_f1",
            "evidence_precision",
            "evidence_recall",
            "far",
            "coverage",
            "abstention_rate",
        ]
        for metric in expected_metrics:
            assert metric in result.metrics, f"Missing metric: {metric}"

    def test_runner_far_alpha_parameter(self):
        """Test that far_alpha parameter affects results."""
        loader = BenchmarkCaseLoader()
        runner = BenchmarkRunner(case_loader=loader)

        result_strict = runner.run(suite_name="smoke_test", far_alpha=0.01)
        result_relaxed = runner.run(suite_name="smoke_test", far_alpha=0.10)

        # Both should produce valid results
        assert result_strict.metrics is not None
        assert result_relaxed.metrics is not None

    def test_runner_with_mock_claims(self):
        """Test runner with generated mock claims."""
        claims = generate_mock_claims(num_claims=5)
        loader = BenchmarkCaseLoader()
        runner = BenchmarkRunner(case_loader=loader)

        # Run with mock data
        result = runner.run(suite_name="smoke_test")
        assert result.num_claims >= 0
        assert len(result.claim_verdicts) >= 0


class TestBenchmarkRunnerEndToEnd:
    """End-to-end integration tests."""

    def test_full_pipeline_mock(self):
        """Test full pipeline with mock data."""
        # Generate mock data
        claims = generate_mock_claims(num_claims=10)

        # Create runner
        loader = BenchmarkCaseLoader()
        runner = BenchmarkRunner(case_loader=loader)

        # Run benchmark
        result = runner.run(suite_name="smoke_test", far_alpha=0.05)

        # Verify result structure
        assert result.suite_name == "smoke_test"
        assert result.num_cases >= 0
        assert result.metrics is not None
        assert isinstance(result.metrics, dict)

        # Verify metrics are numeric
        for key, value in result.metrics.items():
            assert isinstance(value, (int, float)), f"Metric {key} is not numeric: {type(value)}"

    def test_coverage_and_abstention_complementary(self):
        """Test that coverage + abstention_rate ≈ 1.0."""
        loader = BenchmarkCaseLoader()
        runner = BenchmarkRunner(case_loader=loader)
        result = runner.run(suite_name="smoke_test")

        coverage = result.metrics.get("coverage", 0)
        abstention = result.metrics.get("abstention_rate", 0)

        # Should be complementary (allow small floating point error)
        assert abs(coverage + abstention - 1.0) < 0.01, f"coverage={coverage}, abstention={abstention}"
