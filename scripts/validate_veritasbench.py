"""Official VeritasBench data-delivery preflight (data-collection guide v2.0, §6).

Validates that a `benchmarks/veritasbench/` tree is a well-formed, self-consistent benchmark
delivery BEFORE any B1-B5 run. This is the source-of-truth gate the guide's "格式试交" and the
final 50-case delivery must pass — it checks structure, hashes and cross-references, NOT scientific
correctness of the human verdicts.

The nine checks (guide §6):
  1. manifest and suite each list exactly `--expected-cases` unique case IDs, and the two lists
     are identical (as sets).
  2. every case.json exists and its `case_id` matches the directory name.
  3. every artifact file exists, its SHA-256 matches the recorded digest, and kind is a known kind.
  4. every observation has value / source_artifact / source_artifact_hash / source_span.
  5. every observation hash equals the referenced artifact's hash.
  6. claim fields, relation/verdict enums, evidence span (for consistent|inconsistent) and
     annotator fields are present; is_clean_claim=true requires verdict=consistent; annotation_id
     is unique across the delivery.
  7. every claim source_artifact / target_artifact is an observation key.
  8. every case has at least one clean claim.
  9. metadata.paper_split and metadata.primary_failure_mode are present (and a known mode).

`--allow-empty` checks directory readability only (guide §6: NOT valid for real delivery).

Usage:
  uv run python scripts/validate_veritasbench.py \
      --base-path benchmarks/veritasbench --suite veritasbench_trial5 --expected-cases 5 [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

RELATION_TYPES = {"L1", "L2", "L3", "L4"}
VERDICTS = {"consistent", "inconsistent", "insufficient"}
FAILURE_MODES = {"grounding", "verifier_conflict", "false_positive_trap", "mixed_boundary"}
# guide §4.1 artifact kinds; closed set so the official gate is a strict superset of wuguandu's
# mirror validator (the one place the mirror was stricter — see scripts/_mirror_validate_reference.py).
ARTIFACT_KINDS = {"paper_pdf", "source_data", "code", "code_output", "table", "figure", "supplement"}
REQUIRED_CLAIM_FIELDS = (
    "annotation_id", "claim_id", "claim_atom", "relation_type", "verdict",
    "source_artifact", "target_artifact", "is_clean_claim",
    "annotator_id", "annotation_timestamp",
)
REQUIRED_OBS_FIELDS = ("value", "source_artifact", "source_artifact_hash", "source_span")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing file: {path}")
    except json.JSONDecodeError as e:
        errors.append(f"invalid JSON in {path}: {e}")
    return None


def _validate_case(case_dir: Path, seen_annotation_ids: set[str]) -> tuple[bool, dict[str, Any]]:
    errors: list[str] = []
    case = _load_json(case_dir / "case.json", errors)
    if case is None:
        return False, {"ok": False, "errors": errors}

    cid = case.get("case_id")
    if cid != case_dir.name:
        errors.append(f"case_id '{cid}' != directory name '{case_dir.name}'")

    # ---- artifacts: exist + hash + kind (checks 3) ----
    artifacts = case.get("artifacts") or {}
    art_hash: dict[str, str] = {}          # relative path -> recorded sha256
    for name, art in artifacts.items():
        rel = art.get("path")
        digest = art.get("sha256")
        if art.get("kind") not in ARTIFACT_KINDS:
            errors.append(f"artifact '{name}' bad kind {art.get('kind')!r} (not in {sorted(ARTIFACT_KINDS)})")
        if not rel or not digest:
            errors.append(f"artifact '{name}' missing path/sha256")
            continue
        fpath = case_dir / rel
        if not fpath.is_file():
            errors.append(f"artifact file not found: {rel}")
            continue
        actual = _sha256(fpath)
        if actual != digest:
            errors.append(f"sha256 mismatch for {rel}: recorded {digest[:12]}… actual {actual[:12]}…")
        art_hash[rel] = digest

    # ---- observations: fields + hash consistency (checks 4,5) ----
    observations = case.get("observations") or {}
    for okey, obs in observations.items():
        for field in REQUIRED_OBS_FIELDS:
            if field == "value":
                if "value" not in obs:
                    errors.append(f"observation '{okey}' missing value")
            elif not obs.get(field):
                errors.append(f"observation '{okey}' missing {field}")
        src = obs.get("source_artifact")
        if src and src not in art_hash:
            errors.append(f"observation '{okey}' source_artifact '{src}' not in artifacts")
        elif src and obs.get("source_artifact_hash") != art_hash[src]:
            errors.append(f"observation '{okey}' hash != artifact '{src}' hash")

    # ---- claims: fields, enums, refs, clean rule (checks 6,7) ----
    claims = case.get("claims") or []
    n_clean = 0
    for cl in claims:
        ann = cl.get("annotation_id", "<no-id>")
        for field in REQUIRED_CLAIM_FIELDS:
            if field not in cl:
                errors.append(f"claim {ann} missing field '{field}'")
        if cl.get("relation_type") not in RELATION_TYPES:
            errors.append(f"claim {ann} bad relation_type {cl.get('relation_type')!r}")
        verdict = cl.get("verdict")
        if verdict not in VERDICTS:
            errors.append(f"claim {ann} bad verdict {verdict!r}")
        if verdict in ("consistent", "inconsistent") and not cl.get("evidence_span"):
            errors.append(f"claim {ann} verdict={verdict} needs evidence_span")
        if cl.get("is_clean_claim") is True:
            n_clean += 1
            if verdict != "consistent":
                errors.append(f"claim {ann} is_clean_claim=true but verdict={verdict!r} (must be consistent)")
        for role in ("source_artifact", "target_artifact"):
            ref = cl.get(role)
            if ref and ref not in observations:
                errors.append(f"claim {ann} {role} '{ref}' is not an observation key")
        if ann in seen_annotation_ids:
            errors.append(f"duplicate annotation_id across delivery: {ann}")
        seen_annotation_ids.add(ann)

    # ---- at least one clean claim (check 8) ----
    if n_clean == 0:
        errors.append("no clean claim (need >= 1 with is_clean_claim=true & verdict=consistent)")

    # ---- metadata (check 9) ----
    meta = case.get("metadata") or {}
    if not meta.get("paper_split"):
        errors.append("metadata.paper_split missing")
    pfm = meta.get("primary_failure_mode")
    if pfm not in FAILURE_MODES:
        errors.append(f"metadata.primary_failure_mode {pfm!r} not a known mode")

    return not errors, {
        "ok": not errors, "n_artifacts": len(artifacts), "n_observations": len(observations),
        "n_claims": len(claims), "n_clean_claims": n_clean, "errors": errors,
    }


def validate(base_path: Path, suite: str, expected_cases: int, allow_empty: bool) -> dict[str, Any]:
    global_errors: list[str] = []
    manifest = _load_json(base_path / "manifest.json", global_errors)
    suite_doc = _load_json(base_path / "suites" / f"{suite}.json", global_errors)

    manifest_ids = list((manifest or {}).get("cases", []))
    suite_ids = list((suite_doc or {}).get("case_ids", []))

    # ---- check 1: counts + identical sets ----
    if not allow_empty:
        if len(set(manifest_ids)) != expected_cases:
            global_errors.append(f"manifest has {len(set(manifest_ids))} unique cases, expected {expected_cases}")
        if len(set(suite_ids)) != expected_cases:
            global_errors.append(f"suite has {len(set(suite_ids))} unique cases, expected {expected_cases}")
        if set(manifest_ids) != set(suite_ids):
            global_errors.append("manifest.cases and suite.case_ids differ")
    if len(manifest_ids) != len(set(manifest_ids)):
        global_errors.append("manifest.cases contains duplicate IDs")
    if len(suite_ids) != len(set(suite_ids)):
        global_errors.append("suite.case_ids contains duplicate IDs")

    per_case: dict[str, Any] = {}
    seen_annotation_ids: set[str] = set()
    case_ids = sorted(set(manifest_ids) | set(suite_ids))
    for cid in case_ids:
        case_dir = base_path / "cases" / cid
        if not case_dir.is_dir():
            per_case[cid] = {"ok": False, "errors": [f"case directory not found: cases/{cid}"]}
            continue
        if allow_empty:
            per_case[cid] = {"ok": True, "errors": [], "note": "structure-only (--allow-empty)"}
            continue
        _, report = _validate_case(case_dir, seen_annotation_ids)
        per_case[cid] = report

    actual_cases = sum(1 for r in per_case.values() if r.get("ok"))
    ok = not global_errors and all(r.get("ok") for r in per_case.values()) and (
        allow_empty or actual_cases == expected_cases
    )
    return {
        "ok": ok, "base_path": str(base_path), "suite": suite,
        "expected_cases": expected_cases, "actual_cases": actual_cases,
        "allow_empty": allow_empty, "global_errors": global_errors, "cases": per_case,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="VeritasBench data-delivery preflight (guide v2.0 §6).")
    ap.add_argument("--base-path", default="benchmarks/veritasbench", type=Path)
    ap.add_argument("--suite", required=True, help="suite name (reads suites/<suite>.json)")
    ap.add_argument("--expected-cases", type=int, required=True)
    ap.add_argument("--json", action="store_true", help="machine-readable JSON to stdout")
    ap.add_argument("--allow-empty", action="store_true", help="structure-only; NOT valid for delivery")
    args = ap.parse_args(argv)

    result = validate(args.base_path, args.suite, args.expected_cases, args.allow_empty)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"VeritasBench preflight: suite={result['suite']} "
              f"ok={result['ok']} actual_cases={result['actual_cases']}/{result['expected_cases']}")
        for cid, r in result["cases"].items():
            mark = "PASS" if r.get("ok") else "FAIL"
            extra = "" if r.get("ok") else " :: " + "; ".join(r.get("errors", []))
            print(f"  [{mark}] {cid}{extra}")
        for e in result["global_errors"]:
            print(f"  [GLOBAL] {e}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
