"""Auditable experiment ledger for VeritasBench.

This module owns the experiment lifecycle around a tier backend.  It does not
decide how a tier produces predictions.  That separation keeps the stable
parts of the paper experiment (dataset freeze, run identity, resume, and
consistency accounting) independent from the static-audit pipeline adapter.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from engine.reproduction.benchmark.case_loader import BenchmarkCaseLoader
from engine.reproduction.benchmark.dataset_validator import ValidationReport, validate_dataset
from engine.reproduction.benchmark.experiment_contract import (
    ExperimentContractError,
    ExperimentSpec,
    TierSpec,
    canonical_digest,
    load_experiment_spec,
)
from engine.reproduction.benchmark.experiment_plan import build_experiment_plan
from engine.reproduction.models import BenchmarkCase


class ExperimentExecutionError(RuntimeError):
    """Raised when preparation or execution cannot produce a valid ledger."""


class TierBackend(Protocol):
    """Adapter implemented by a concrete B1-B5 execution backend."""

    backend_id: str

    def run_case(
        self,
        case: BenchmarkCase,
        tier: TierSpec,
        repeat_index: int,
    ) -> Mapping[str, Any]:
        """Run one case under one tier and return JSON-compatible results."""


@dataclass(frozen=True)
class PreparedExperiment:
    """Inputs frozen before any tier execution starts."""

    spec: ExperimentSpec
    cases: tuple[BenchmarkCase, ...]
    plan: dict[str, Any]
    output_dir: Path
    preflight: ValidationReport
    tool_registry_digest: str


def sha256_file(path: Path | str) -> str:
    """Return the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ExperimentLedger:
    """Prepare and execute a reproducible case × tier × repeat matrix."""

    def __init__(
        self,
        config_path: Path | str,
        *,
        base_path: Path | str | None = None,
        output_dir: Path | str = "outputs/experiments/veritasbench",
        tool_registry_path: Path | str = "engine/tools/registry.py",
        model_id: str = "veritas-auditor",
        seed: int = 0,
        temperature: float = 0.0,
        allow_partial: bool = False,
    ) -> None:
        self.config_path = Path(config_path)
        self.spec = load_experiment_spec(self.config_path)
        self.base_path = Path(base_path or "benchmarks/veritasbench")
        self.output_dir = Path(output_dir)
        self.tool_registry_path = Path(tool_registry_path)
        self.model_id = model_id
        self.seed = seed
        self.temperature = temperature
        self.allow_partial = allow_partial

    def prepare(self, *, allow_partial: bool | None = None) -> PreparedExperiment:
        """Validate the frozen dataset and write the deterministic run plan."""

        partial = self.allow_partial if allow_partial is None else allow_partial
        preflight = validate_dataset(
            self.base_path,
            suite_name=self.spec.dataset_suite,
            expected_cases=self.spec.expected_cases,
            allow_partial=partial,
        )
        if not preflight.ok:
            details = "; ".join(preflight.errors)
            raise ExperimentExecutionError(f"Dataset preflight failed: {details}")

        loader = BenchmarkCaseLoader(self.base_path)
        cases = tuple(loader.load_suite(self.spec.dataset_suite))
        if len(cases) != self.spec.expected_cases and not (
            partial and 0 < len(cases) < self.spec.expected_cases
        ):
            raise ExperimentExecutionError(
                f"Suite loaded {len(cases)} cases, expected {self.spec.expected_cases}"
            )

        case_input_hashes = {
            case.case_id: _case_input_hashes(case) for case in cases
        }
        registry_digest = sha256_file(self.tool_registry_path)
        plan = build_experiment_plan(
            spec=self.spec,
            case_input_hashes=case_input_hashes,
            tool_registry_digest=registry_digest,
            model_id=self.model_id,
            seed=self.seed,
            temperature=self.temperature,
            allow_partial=partial,
        )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(self.output_dir / "preflight.json", preflight.as_dict())
        _write_json(self.output_dir / "plan.json", plan)
        _write_json(
            self.output_dir / "experiment.json",
            {
                "schema_version": 1,
                "experiment_id": self.spec.experiment_id,
                "config_digest": self.spec.config_digest,
                "plan_digest": plan["plan_digest"],
                "dataset_suite": self.spec.dataset_suite,
                "expected_cases": self.spec.expected_cases,
                "expected_repeat_runs": self.spec.expected_repeat_runs,
                "planned_cases": plan["planned_cases"],
                "planned_repeat_runs": plan["planned_repeat_runs"],
                "partial": plan["partial"],
                "tool_registry_digest": registry_digest,
                "model_id": self.model_id,
                "seed": self.seed,
                "temperature": self.temperature,
            },
        )
        return PreparedExperiment(
            spec=self.spec,
            cases=cases,
            plan=plan,
            output_dir=self.output_dir,
            preflight=preflight,
            tool_registry_digest=registry_digest,
        )

    def execute(
        self,
        backend: TierBackend,
        *,
        prepared: PreparedExperiment | None = None,
        resume: bool = True,
        max_runs: int | None = None,
    ) -> dict[str, Any]:
        """Execute the plan through *backend* and write a resumable summary.

        A backend failure is recorded as a failed run and stops the matrix by
        default.  This prevents a partial result from being mistaken for a
        complete paper table while preserving enough state for diagnosis.
        """

        prepared = prepared or self.prepare()
        cases = {case.case_id: case for case in prepared.cases}
        runs_dir = prepared.output_dir / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_records: list[dict[str, Any]] = []
        failed_error: str | None = None

        for index, run_manifest in enumerate(prepared.plan["runs"]):
            if max_runs is not None and index >= max_runs:
                break
            run_path = runs_dir / f"{run_manifest['identity_digest']}.json"
            if resume and run_path.is_file():
                cached = _read_json(run_path)
                if cached.get("run_manifest") == run_manifest and cached.get("status") == "succeeded":
                    run_records.append(cached)
                    continue

            case_id = run_manifest["case_id"]
            case = cases.get(case_id)
            if case is None:
                failed_error = f"Plan references case not loaded: {case_id}"
                record = _failed_record(run_manifest, backend.backend_id, failed_error)
                _write_json(run_path, record)
                run_records.append(record)
                break

            tier = prepared.spec.tier(run_manifest["tier_id"])
            started_at = _now()
            started = time.monotonic()
            try:
                result = dict(backend.run_case(case, tier, run_manifest["repeat_index"]))
                record = {
                    "schema_version": 1,
                    "run_manifest": run_manifest,
                    "backend_id": backend.backend_id,
                    "status": "succeeded",
                    "started_at": started_at,
                    "finished_at": _now(),
                    "duration_seconds": round(time.monotonic() - started, 6),
                    "result_digest": result_digest(result),
                    "result": result,
                }
            except Exception as exc:  # noqa: BLE001 - persisted for diagnosis
                failed_error = f"{type(exc).__name__}: {exc}"
                record = _failed_record(run_manifest, backend.backend_id, failed_error)
            _write_json(run_path, record)
            run_records.append(record)
            if record["status"] == "failed":
                break

        summary = build_summary(prepared, run_records, backend.backend_id)
        _write_json(prepared.output_dir / "summary.json", summary)
        if failed_error is not None:
            raise ExperimentExecutionError(f"Experiment stopped after failed run: {failed_error}")
        return summary


def result_digest(result: Mapping[str, Any]) -> str:
    """Hash only deterministic backend output, excluding runtime metadata."""

    excluded = {"started_at", "finished_at", "duration_seconds", "status", "error"}
    canonical = {key: value for key, value in result.items() if key not in excluded}
    return canonical_digest(canonical)


def build_summary(
    prepared: PreparedExperiment,
    run_records: list[Mapping[str, Any]],
    backend_id: str,
) -> dict[str, Any]:
    """Aggregate run status, per-tier metrics, and repeat consistency."""

    successful = [record for record in run_records if record.get("status") == "succeeded"]
    failed = [record for record in run_records if record.get("status") == "failed"]
    metric_values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for record in successful:
        tier_id = record["run_manifest"]["tier_id"]
        metrics = record.get("result", {}).get("metrics", {})
        if isinstance(metrics, Mapping):
            for name, value in metrics.items():
                if isinstance(value, (int, float)):
                    metric_values[tier_id][name].append(float(value))

    by_tier: dict[str, Any] = {}
    for tier in prepared.spec.tiers:
        values = metric_values.get(tier.tier_id, {})
        by_tier[tier.tier_id] = {
            "runs": len(values[next(iter(values))]) if values else 0,
            "metrics_mean": {
                name: sum(items) / len(items) for name, items in sorted(values.items()) if items
            },
        }

    repeat_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for record in successful:
        manifest = record["run_manifest"]
        repeat_groups[(manifest["case_id"], manifest["tier_id"])].append(
            record["result_digest"]
        )
    comparable_groups = [digests for digests in repeat_groups.values() if len(digests) > 1]
    mismatch_groups = sum(1 for digests in comparable_groups if len(set(digests)) > 1)

    expected_runs = len(prepared.plan["runs"])
    return {
        "schema_version": 1,
        "experiment_id": prepared.spec.experiment_id,
        "backend_id": backend_id,
        "plan_digest": prepared.plan["plan_digest"],
        "expected_runs": expected_runs,
        "observed_runs": len(run_records),
        "successful_runs": len(successful),
        "failed_runs": len(failed),
        "complete": len(successful) == expected_runs,
        "partial": bool(prepared.plan.get("partial", False)),
        "by_tier": by_tier,
        "consistency": {
            "groups": len(comparable_groups),
            "mismatch_groups": mismatch_groups,
            "digest_mismatch_rate": (
                mismatch_groups / len(comparable_groups) if comparable_groups else 0.0
            ),
        },
        "failed_run_ids": [
            record["run_manifest"]["identity_digest"] for record in failed
        ],
    }


def _case_input_hashes(case: BenchmarkCase) -> dict[str, str]:
    """Extract immutable artifact hashes without consulting ground truth labels."""

    hashes: dict[str, str] = {}
    for artifact_id, metadata in case.artifacts.items():
        if not isinstance(metadata, Mapping):
            raise ExperimentContractError(f"Artifact {artifact_id!r} must be an object")
        digest = metadata.get("sha256")
        path = metadata.get("path")
        if not isinstance(path, str) or not path:
            raise ExperimentContractError(f"Artifact {artifact_id!r} is missing path")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ExperimentContractError(f"Artifact {artifact_id!r} has an invalid sha256")
        hashes[f"{artifact_id}:{path}"] = digest.lower()
    if not hashes:
        raise ExperimentContractError(f"Case {case.case_id!r} has no artifacts")
    return hashes


def _failed_record(run_manifest: Mapping[str, Any], backend_id: str, error: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_manifest": dict(run_manifest),
        "backend_id": backend_id,
        "status": "failed",
        "started_at": _now(),
        "finished_at": _now(),
        "duration_seconds": 0.0,
        "error": error,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ExperimentExecutionError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
