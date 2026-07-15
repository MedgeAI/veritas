"""Build deterministic B1-B5 x case x repeat execution plans."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from engine.reproduction.benchmark.experiment_contract import (
    ExperimentContractError,
    ExperimentSpec,
    build_run_manifest,
    canonical_digest,
    load_experiment_spec,
)


def build_experiment_plan(
    *,
    spec: ExperimentSpec,
    case_input_hashes: Mapping[str, Mapping[str, str]],
    tool_registry_digest: str,
    model_id: str,
    seed: int,
    temperature: float,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """Build repeat identities without executing any audit stage.

    ``allow_partial`` is reserved for a pilot subset. The generated plan
    records both the subset and full experiment cardinality.
    """

    case_ids = sorted(case_input_hashes)
    is_partial = len(case_ids) != spec.expected_cases
    if is_partial and (
        not allow_partial or not 0 < len(case_ids) < spec.expected_cases
    ):
        raise ExperimentContractError(
            f"Expected {spec.expected_cases} paper cases, got {len(case_ids)}"
        )
    if len(set(case_ids)) != len(case_ids):
        raise ExperimentContractError("Case IDs must be unique")

    runs: list[dict[str, Any]] = []
    for case_id in case_ids:
        input_hashes = case_input_hashes[case_id]
        if not input_hashes:
            raise ExperimentContractError(f"Case {case_id!r} has no input hashes")
        for repeat_index in range(1, spec.consistency_repeats + 1):
            for tier in spec.tiers:
                runs.append(
                    build_run_manifest(
                        spec=spec,
                        tier_id=tier.tier_id,
                        case_id=case_id,
                        repeat_index=repeat_index,
                        input_hashes=input_hashes,
                        tool_registry_digest=tool_registry_digest,
                        model_id=model_id,
                        seed=seed,
                        temperature=temperature,
                    )
                )

    payload: dict[str, Any] = {
        "schema_version": 1,
        "experiment_id": spec.experiment_id,
        "config_digest": spec.config_digest,
        "expected_primary_runs": spec.expected_primary_runs,
        "expected_repeat_runs": spec.expected_repeat_runs,
        "planned_cases": len(case_ids),
        "planned_primary_runs": len(case_ids) * len(spec.tiers),
        "planned_repeat_runs": len(runs),
        "partial": is_partial,
        "runs": runs,
    }
    payload["plan_digest"] = canonical_digest(payload)
    return payload


def write_experiment_plan(path: Path | str, plan: Mapping[str, Any]) -> None:
    """Write a plan with stable formatting for review and later execution."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "case_input_hashes",
        type=Path,
        help="JSON mapping of case_id to {artifact_name: sha256}.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tool-registry-digest", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Allow a non-empty pilot subset; never use for final results.",
    )
    args = parser.parse_args()

    spec = load_experiment_spec(args.config)
    case_input_hashes = json.loads(args.case_input_hashes.read_text(encoding="utf-8"))
    plan = build_experiment_plan(
        spec=spec,
        case_input_hashes=case_input_hashes,
        tool_registry_digest=args.tool_registry_digest,
        model_id=args.model_id,
        seed=args.seed,
        temperature=args.temperature,
        allow_partial=args.allow_partial,
    )
    write_experiment_plan(args.output, plan)
    print(json.dumps({"output": str(args.output), "plan_digest": plan["plan_digest"]}))


if __name__ == "__main__":
    _main()
