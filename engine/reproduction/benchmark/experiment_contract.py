"""Validated experiment contracts and stable run identities for VeritasBench."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

EXPECTED_TIER_IDS = ("B1", "B2", "B3", "B4", "B5")
PIPELINE_TIERS = {"bare", "structured", "artifact", "provenance", "dual-layer"}
AGGREGATION_POLICIES = {"flat", "graph_aware"}


class ExperimentContractError(ValueError):
    """Raised when an experiment config is unsafe or incomplete."""


@dataclass(frozen=True)
class TierSpec:
    """One controlled condition in the benchmark matrix."""

    tier_id: str
    pipeline_tier: str
    audit_profile: str
    aggregation_policy: str
    roles: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.tier_id,
            "pipeline_tier": self.pipeline_tier,
            "audit_profile": self.audit_profile,
            "aggregation_policy": self.aggregation_policy,
            "roles": list(self.roles),
        }


@dataclass(frozen=True)
class ExperimentSpec:
    """Validated source of truth for one paper experiment."""

    schema_version: int
    experiment_id: str
    dataset_manifest: str
    dataset_suite: str
    expected_cases: int
    split_unit: str
    tiers: tuple[TierSpec, ...]
    consistency_repeats: int
    canonical_fields: tuple[str, ...]
    digest_excluded_fields: tuple[str, ...]
    metrics: tuple[str, ...]
    config_digest: str

    @property
    def expected_primary_runs(self) -> int:
        return self.expected_cases * len(self.tiers)

    @property
    def expected_repeat_runs(self) -> int:
        return self.expected_primary_runs * self.consistency_repeats

    def tier(self, tier_id: str) -> TierSpec:
        for tier in self.tiers:
            if tier.tier_id == tier_id:
                return tier
        raise KeyError(tier_id)


def canonical_digest(value: Any) -> str:
    """Return a stable SHA-256 digest for JSON-compatible data."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_run_manifest(
    *,
    spec: ExperimentSpec,
    tier_id: str,
    case_id: str,
    repeat_index: int,
    input_hashes: Mapping[str, str],
    tool_registry_digest: str,
    model_id: str,
    seed: int,
    temperature: float,
) -> dict[str, Any]:
    """Build a timestamp-free identity manifest for one repeatable run."""

    tier = spec.tier(tier_id)
    if repeat_index < 1 or repeat_index > spec.consistency_repeats:
        raise ExperimentContractError(
            f"repeat_index must be in [1, {spec.consistency_repeats}], got {repeat_index}"
        )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "experiment_id": spec.experiment_id,
        "config_digest": spec.config_digest,
        "tier_id": tier.tier_id,
        "pipeline_tier": tier.pipeline_tier,
        "audit_profile": tier.audit_profile,
        "aggregation_policy": tier.aggregation_policy,
        "case_id": case_id,
        "repeat_index": repeat_index,
        "input_hashes": dict(sorted(input_hashes.items())),
        "tool_registry_digest": tool_registry_digest,
        "model_id": model_id,
        "seed": seed,
        "temperature": temperature,
    }
    return {**payload, "identity_digest": canonical_digest(payload)}


def load_experiment_spec(path: Path | str) -> ExperimentSpec:
    """Load and fail loudly on an invalid experiment configuration."""

    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Experiment config not found: {config_path}")
    with config_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ExperimentContractError("Experiment config root must be a mapping")
    return _parse_spec(raw)


def _parse_spec(raw: Mapping[str, Any]) -> ExperimentSpec:
    schema_version = raw.get("schema_version")
    experiment_id = raw.get("experiment_id")
    if schema_version != 1 or not isinstance(experiment_id, str) or not experiment_id:
        raise ExperimentContractError("schema_version=1 and a non-empty experiment_id are required")

    dataset = raw.get("dataset")
    if not isinstance(dataset, Mapping):
        raise ExperimentContractError("dataset must be a mapping")
    manifest = dataset.get("manifest")
    suite = dataset.get("suite")
    expected_cases = dataset.get("expected_cases")
    split_unit = dataset.get("split_unit")
    if (
        not isinstance(manifest, str)
        or not isinstance(suite, str)
        or not isinstance(expected_cases, int)
        or expected_cases <= 0
        or split_unit != "paper"
    ):
        raise ExperimentContractError(
            "dataset requires manifest, suite, positive expected_cases, and split_unit=paper"
        )

    raw_tiers = raw.get("tiers")
    tier_ids = [
        item.get("id") for item in raw_tiers
        if isinstance(item, Mapping)
    ] if isinstance(raw_tiers, list) else []
    expected_prefix = list(EXPECTED_TIER_IDS[:len(tier_ids)])
    if not tier_ids or tier_ids != expected_prefix:
        raise ExperimentContractError(
            "tiers must be an ordered non-empty prefix of B1, B2, B3, B4, B5"
        )
    tiers = tuple(_parse_tier(item) for item in raw_tiers)
    if len(tiers) == len(EXPECTED_TIER_IDS):
        _validate_control_pair(tiers)

    consistency = raw.get("consistency")
    if not isinstance(consistency, Mapping):
        raise ExperimentContractError("consistency must be a mapping")
    repeats = consistency.get("repeats")
    canonical_fields = consistency.get("canonical_fields")
    excluded_fields = consistency.get("exclude_from_digest")
    if (
        not isinstance(repeats, int)
        or repeats < 3
        or not _non_empty_string_list(canonical_fields)
        or not _non_empty_string_list(excluded_fields)
    ):
        raise ExperimentContractError(
            "consistency requires repeats>=3 and non-empty canonical/excluded field lists"
        )

    metrics = raw.get("metrics")
    if not _non_empty_string_list(metrics):
        raise ExperimentContractError("metrics must be a non-empty list of strings")

    return ExperimentSpec(
        schema_version=schema_version,
        experiment_id=experiment_id,
        dataset_manifest=manifest,
        dataset_suite=suite,
        expected_cases=expected_cases,
        split_unit=split_unit,
        tiers=tiers,
        consistency_repeats=repeats,
        canonical_fields=tuple(canonical_fields),
        digest_excluded_fields=tuple(excluded_fields),
        metrics=tuple(metrics),
        config_digest=canonical_digest(raw),
    )


def _parse_tier(raw: Mapping[str, Any]) -> TierSpec:
    tier_id = raw.get("id")
    pipeline_tier = raw.get("pipeline_tier")
    audit_profile = raw.get("audit_profile")
    aggregation_policy = raw.get("aggregation_policy")
    roles = raw.get("roles")
    if (
        not isinstance(tier_id, str)
        or pipeline_tier not in PIPELINE_TIERS
        or not isinstance(audit_profile, str)
        or aggregation_policy not in AGGREGATION_POLICIES
        or not _non_empty_string_list(roles)
    ):
        raise ExperimentContractError(f"Invalid tier definition: {raw!r}")
    return TierSpec(
        tier_id=tier_id,
        pipeline_tier=pipeline_tier,
        audit_profile=audit_profile,
        aggregation_policy=aggregation_policy,
        roles=tuple(roles),
    )


def _validate_control_pair(tiers: tuple[TierSpec, ...]) -> None:
    b4, b5 = tiers[3], tiers[4]
    if (
        b4.pipeline_tier != b5.pipeline_tier
        or b4.audit_profile != b5.audit_profile
        or b4.roles != b5.roles
        or b4.aggregation_policy != "flat"
        or b5.aggregation_policy != "graph_aware"
    ):
        raise ExperimentContractError(
            "B4/B5 must match upstream conditions and differ only by flat vs graph_aware aggregation"
        )


def _non_empty_string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item for item in value)


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    spec = load_experiment_spec(args.config)
    print(
        json.dumps(
            {
                "experiment_id": spec.experiment_id,
                "config_digest": spec.config_digest,
                "expected_primary_runs": spec.expected_primary_runs,
                "expected_repeat_runs": spec.expected_repeat_runs,
                "tiers": [tier.as_dict() for tier in spec.tiers],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    _main()
