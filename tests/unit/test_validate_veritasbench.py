"""Unit tests for the official VeritasBench preflight (scripts/validate_veritasbench.py).

A gate is only meaningful if it FAILS on broken input. Each test mutates one field of an
otherwise-valid delivery and asserts the corresponding §6 check fires — so a future refactor that
silently weakens a check is caught here rather than by shipping bad benchmark data.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.validate_veritasbench import validate


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _build(tmp: Path, *, mutate=None) -> Path:
    """Write a minimal well-formed 1-case delivery; `mutate(case)` may corrupt it in place."""
    base = tmp / "bench"
    cdir = base / "cases" / "c1" / "artifacts"
    cdir.mkdir(parents=True)
    payload = b"col,val\n1,1.0\n"
    (cdir / "a.csv").write_bytes(payload)
    digest = _sha256(payload)
    obs = {
        "artifacts/a.csv#o1": {"value": 1.0, "source_artifact": "artifacts/a.csv",
                               "source_artifact_hash": digest, "source_span": "row 1"},
        "artifacts/a.csv#o2": {"value": 2.0, "source_artifact": "artifacts/a.csv",
                               "source_artifact_hash": digest, "source_span": "row 2"},
    }
    case = {
        "case_id": "c1", "paper_title": "t", "paper_authors": ["a"],
        "artifacts": {"a": {"path": "artifacts/a.csv", "sha256": digest, "kind": "source_data"}},
        "observations": obs,
        "claims": [{
            "annotation_id": "c1_ann_1", "claim_id": "c1_claim_1", "claim_atom": "x",
            "source_artifact": "artifacts/a.csv#o1", "target_artifact": "artifacts/a.csv#o2",
            "relation_type": "L1", "verdict": "consistent", "discrepancy_type": None,
            "evidence_span": "L1:o1->o2", "severity": "low",
            "annotator_id": "wuguandu", "annotation_timestamp": "2026-07-14T00:00:00Z",
            "is_clean_claim": True,
        }],
        "metadata": {"paper_split": "c1", "primary_failure_mode": "verifier_conflict"},
    }
    if mutate:
        mutate(case)
    (base / "cases" / "c1" / "case.json").write_text(json.dumps(case), encoding="utf-8")
    (base / "manifest.json").write_text(json.dumps(
        {"schema_version": 1, "benchmark_id": "veritasbench", "case_count": 1, "cases": ["c1"]}))
    (base / "suites").mkdir()
    (base / "suites" / "s.json").write_text(json.dumps(
        {"schema_version": 1, "name": "s", "case_ids": ["c1"]}))
    return base


def test_wellformed_passes(tmp_path):
    base = _build(tmp_path)
    result = validate(base, "s", expected_cases=1, allow_empty=False)
    assert result["ok"] is True
    assert result["actual_cases"] == 1
    assert result["cases"]["c1"]["n_clean_claims"] == 1


def test_hash_mismatch_fails(tmp_path):
    base = _build(tmp_path, mutate=lambda c: c["artifacts"]["a"].__setitem__("sha256", "0" * 64))
    assert validate(base, "s", 1, False)["ok"] is False


def test_clean_claim_must_be_consistent(tmp_path):
    def m(c):
        c["claims"][0]["verdict"] = "inconsistent"
    r = validate(_build(tmp_path, mutate=m), "s", 1, False)
    assert r["ok"] is False
    assert any("is_clean_claim" in e for e in r["cases"]["c1"]["errors"])


def test_dangling_observation_ref_fails(tmp_path):
    def m(c):
        c["claims"][0]["source_artifact"] = "artifacts/a.csv#missing"
    assert validate(_build(tmp_path, mutate=m), "s", 1, False)["ok"] is False


def test_observation_hash_must_match_artifact(tmp_path):
    def m(c):
        c["observations"]["artifacts/a.csv#o1"]["source_artifact_hash"] = "9" * 64
    assert validate(_build(tmp_path, mutate=m), "s", 1, False)["ok"] is False


def test_no_clean_claim_fails(tmp_path):
    def m(c):
        c["claims"][0]["is_clean_claim"] = False
    r = validate(_build(tmp_path, mutate=m), "s", 1, False)
    assert r["ok"] is False
    assert any("clean claim" in e for e in r["cases"]["c1"]["errors"])


def test_bad_verdict_enum_fails(tmp_path):
    def m(c):
        c["claims"][0]["verdict"] = "fraudulent"
    assert validate(_build(tmp_path, mutate=m), "s", 1, False)["ok"] is False


def test_bad_artifact_kind_fails(tmp_path):
    # official gate is a strict superset of the mirror: kind must be one of the 7 known kinds
    def m(c):
        c["artifacts"]["a"]["kind"] = "spreadsheet"
    r = validate(_build(tmp_path, mutate=m), "s", 1, False)
    assert r["ok"] is False
    assert any("bad kind" in e for e in r["cases"]["c1"]["errors"])


def test_missing_primary_failure_mode_fails(tmp_path):
    def m(c):
        c["metadata"].pop("primary_failure_mode")
    assert validate(_build(tmp_path, mutate=m), "s", 1, False)["ok"] is False


def test_expected_count_mismatch_fails(tmp_path):
    base = _build(tmp_path)
    assert validate(base, "s", expected_cases=2, allow_empty=False)["ok"] is False


def test_allow_empty_is_structure_only(tmp_path):
    base = _build(tmp_path)
    # even with a wrong expected count, --allow-empty only checks structure readability
    assert validate(base, "s", expected_cases=99, allow_empty=True)["ok"] is True
