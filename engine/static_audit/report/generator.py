"""Top-level report generation and static audit bundle assembly.

Public entry points:

* ``generate_report`` -- produces ``final_audit_report.md`` from workdir artifacts.
* ``build_static_audit_bundle`` -- produces the ``StaticAuditBundle`` dataclass.
* ``collect_claims_and_findings`` -- orchestrates claim/finding collection from
  all artifact sources.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.static_audit.models import (
    Claim,
    ClaimMapping,
    EvidenceItem,
    ExecutionStatus,
    Finding,
    StaticAuditBundle,
    ToolRun,
)
from engine.static_audit.investigation import (
    read_investigation_records,
)
from engine.static_audit.tools.paperfraud_rules import (
    paperfraud_findings_from_matches,
)
from engine.static_audit._shared import (
    STEP_TOOL_IDS,
    StepResult,
    resolve_artifact_path,
    read_json,
)

from engine.static_audit.report.evidence import collect_evidence_items
from engine.static_audit.report.claims import (
    collect_agent_refined_claim_mappings,
    collect_deterministic_claim_mappings,
)
from engine.static_audit.report.findings import find_missing_source_data_findings
from engine.static_audit.report.sections import (
    ReportData,
    header_section,
    scope_section,
    pipeline_section,
    artifact_manifest_section,
    material_section,
    investigation_section,
    agent_plan_section,
    judge_section,
    agent_review_section,
    claim_mapping_section,
    ledger_section,
    numeric_section,
    profile_section,
    findings_section,
    pair_forensics_section,
    duplicates_section,
    similarity_section,
    bundle_section,
    vlm_section,
    limitations_section,
    collect_visual_findings,
    group_similar_findings,
    merge_deterministic_mappings,
)


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


def generate_report(
    *,
    paper_dir: Path,
    paper_pdf: Path,
    source_data_dir: Path | None,
    workdir: Path,
    case_id: str,
    agent_mode: str,
    steps: list[StepResult],
) -> Path:
    """Render ``final_audit_report.md`` from all workdir artifacts."""
    data = ReportData(
        workdir=workdir,
        case_id=case_id,
        paper_dir=paper_dir,
        paper_pdf=paper_pdf,
        source_data_dir=source_data_dir,
        agent_mode=agent_mode,
        steps=steps,
        mineru_manifest=read_json(
            resolve_artifact_path(workdir, "mineru_manifest.json")
        ),
        material_inventory=read_json(
            resolve_artifact_path(workdir, "material_inventory.json")
        ),
        material_plan=read_json(
            resolve_artifact_path(workdir, "agent_material_plan.json")
        ),
        ledger=read_json(resolve_artifact_path(workdir, "evidence_ledger.json")),
        numeric=read_json(resolve_artifact_path(workdir, "numeric_forensics.json")),
        profile=read_json(resolve_artifact_path(workdir, "source_data_profile.json")),
        findings=read_json(resolve_artifact_path(workdir, "source_data_findings.json")),
        pair_forensics=read_json(
            resolve_artifact_path(workdir, "source_data_pair_forensics.json")
        ),
        duplicates=read_json(
            resolve_artifact_path(workdir, "exact_image_duplicates.json")
        ),
        similarity=read_json(
            resolve_artifact_path(workdir, "image_similarity_candidates.json")
        ),
        investigation_records=read_investigation_records(workdir),
        static_bundle=read_json(
            resolve_artifact_path(workdir, "static_audit_bundle.json")
        ),
        vlm=read_json(resolve_artifact_path(workdir, "vlm_triage_selected.json")),
        agent_plan=read_json(resolve_artifact_path(workdir, "agent_audit_plan.json"))
        if agent_mode in {"plan", "full"}
        else None,
        agent_review=read_json(resolve_artifact_path(workdir, "agent_review.json"))
        if agent_mode in {"review", "full"}
        else None,
        agent_judge=read_json(resolve_artifact_path(workdir, "agent_judge.json"))
        if agent_mode in {"review", "full"}
        else None,
        agent_source_data_auditor=read_json(
            resolve_artifact_path(workdir, "agent_source_data_auditor.json")
        )
        if agent_mode in {"review", "full"}
        else None,
    )
    lines: list[str] = []
    for section_fn in [
        header_section,
        scope_section,
        pipeline_section,
        artifact_manifest_section,
        material_section,
        investigation_section,
        agent_plan_section,
        judge_section,
        agent_review_section,
        claim_mapping_section,
        ledger_section,
        numeric_section,
        profile_section,
        findings_section,
        pair_forensics_section,
        duplicates_section,
        similarity_section,
        bundle_section,
        vlm_section,
        limitations_section,
    ]:
        lines.extend(section_fn(data))
    report_path = resolve_artifact_path(workdir, "final_audit_report.md")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# build_static_audit_bundle
# ---------------------------------------------------------------------------


def build_static_audit_bundle(
    *,
    paper_dir: Path,
    paper_pdf: Path,
    source_data_dir: Path | None,
    workdir: Path,
    case_id: str,
    steps: list[StepResult],
    agent_manifest: dict[str, Any],
) -> StaticAuditBundle:
    """Assemble the ``StaticAuditBundle`` from all workdir artifacts."""
    evidence_items = collect_evidence_items(workdir)
    claims, claim_mappings, findings = collect_claims_and_findings(
        workdir, evidence_items
    )
    from engine.static_audit.investigation_dispatch import collect_agent_traces

    traces = collect_agent_traces(workdir, agent_manifest)

    material_plan = (
        read_json(resolve_artifact_path(workdir, "agent_material_plan.json")) or {}
    )
    if material_plan.get("missing_materials"):
        findings.append(
            Finding(
                finding_id="COMP-MAT-001",
                category="material_missing",
                risk_level="medium",
                summary=f"提交材料缺少: {', '.join(material_plan['missing_materials'])}",
                issue_category="completeness",
                metadata={
                    "missing_items": material_plan["missing_materials"],
                    "material_plan_status": material_plan.get("status"),
                },
            )
        )

    execution_status = ExecutionStatus(status="not_provided")
    if execution_status.status in {"not_provided", "not_run", "missing_material"}:
        findings.append(
            Finding(
                finding_id="COMP-EXEC-001",
                category="execution_status_not_available",
                risk_level="low",
                summary=f"代码执行审查未连接: execution_status={execution_status.status}",
                issue_category="completeness",
                metadata={
                    "execution_status": execution_status.status,
                    "runtime_backend": execution_status.runtime_backend,
                },
            )
        )

    findings.extend(find_missing_source_data_findings(workdir))

    return StaticAuditBundle(
        case_id=case_id,
        inputs={
            "paper_dir": str(paper_dir),
            "paper_pdf": str(paper_pdf),
            "source_data_dir": str(source_data_dir) if source_data_dir else None,
            "material_inventory": str(
                resolve_artifact_path(workdir, "material_inventory.json")
            ),
            "agent_material_plan": str(
                resolve_artifact_path(workdir, "agent_material_plan.json")
            ),
            "optional_lanes": agent_manifest.get("optional_lanes", []),
            "workdir": str(workdir),
        },
        tool_runs=[
            ToolRun(
                tool_id=STEP_TOOL_IDS.get(step.key, step.key),
                step_key=step.key,
                status=step.status,  # type: ignore[arg-type]
                title=step.title,
                command=step.command,
                outputs=[],
                detail=step.detail,
            )
            for step in steps
        ],
        evidence_items=evidence_items,
        claims=claims,
        findings=findings,
        claim_mappings=claim_mappings,
        agent_traces=traces,
        limitations=[
            "Static audit bundle v1 is generated from deterministic artifacts and current Agent review output.",
            "Code execution audit is not connected in this static-audit run.",
        ],
        execution_status=execution_status,
        metadata={
            "agent": agent_manifest,
            "investigation_records": read_investigation_records(workdir),
            "material_plan": read_json(
                resolve_artifact_path(workdir, "agent_material_plan.json")
            )
            or {},
            "claim_mapping_policy": {
                "canonical_preference": "agent_refined",
                "fallback": "deterministic_scaffolding",
                "deterministic_scaffolding_artifact": str(
                    resolve_artifact_path(workdir, "source_data_findings.json")
                ),
                "agent_claim_artifact": str(
                    resolve_artifact_path(workdir, "agent_claim_extractor.json")
                ),
                "agent_source_data_artifact": str(
                    resolve_artifact_path(workdir, "agent_source_data_auditor.json")
                ),
            },
            "deterministic_claim_mappings": (
                (
                    read_json(
                        resolve_artifact_path(workdir, "source_data_findings.json")
                    )
                    or {}
                ).get("claim_to_source_data")
                or []
            ),
        },
    )


# ---------------------------------------------------------------------------
# collect_claims_and_findings
# ---------------------------------------------------------------------------


def _load_claim_artifacts(workdir: Path) -> dict[str, Any]:
    """Read all JSON artifacts needed for claim and finding collection."""
    return {
        "source_findings": read_json(
            resolve_artifact_path(workdir, "source_data_findings.json")
        )
        or {},
        "pair_forensics": read_json(
            resolve_artifact_path(workdir, "source_data_pair_forensics.json")
        )
        or {},
        "agent_claims": read_json(
            resolve_artifact_path(workdir, "agent_claim_extractor.json")
        )
        or {},
        "agent_source": read_json(
            resolve_artifact_path(workdir, "agent_source_data_auditor.json")
        )
        or {},
        "paperfraud_matches": read_json(
            resolve_artifact_path(workdir, "paperfraud_rule_matches.json")
        )
        or {},
        "visual_findings": read_json(
            resolve_artifact_path(workdir, "visual_findings.json")
        )
        or {},
    }


def _build_evidence_indices(
    evidence_items: list[EvidenceItem],
) -> tuple[dict[Any, str], dict[Any, str], dict[Any, str]]:
    """Build evidence lookup maps by finding_id, panel_id, and artifact_name."""
    evidence_by_finding = {
        item.metadata.get("finding_id"): item.evidence_id
        for item in evidence_items
        if item.metadata.get("finding_id")
    }
    evidence_by_panel = {
        item.metadata.get("panel_id"): item.evidence_id
        for item in evidence_items
        if item.metadata.get("panel_id")
    }
    evidence_by_artifact = {
        item.metadata.get("artifact_name"): item.evidence_id
        for item in evidence_items
        if item.metadata.get("artifact_name")
    }
    return evidence_by_finding, evidence_by_panel, evidence_by_artifact


def _collect_core_claims_and_mappings(
    artifacts: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> tuple[list[Claim], list[ClaimMapping]]:
    """Merge agent-refined and deterministic claim mappings."""
    source_findings = artifacts["source_findings"]
    agent_claims = artifacts["agent_claims"]
    agent_source = artifacts["agent_source"]
    deterministic_mappings = source_findings.get("claim_to_source_data") or []

    claims, mappings = collect_agent_refined_claim_mappings(
        agent_claims=agent_claims,
        agent_source=agent_source,
        deterministic_mappings=deterministic_mappings,
    )
    if not claims and not mappings:
        return collect_deterministic_claim_mappings(
            source_findings=source_findings,
            evidence_by_finding=evidence_by_finding,
        )

    # Merge: supplement agent-refined results with any deterministic
    # mappings not already covered.
    extra_claims, extra_mappings = merge_deterministic_mappings(
        agent_claims=claims,
        agent_mappings=mappings,
        source_findings=source_findings,
        evidence_by_finding=evidence_by_finding,
    )
    claims.extend(extra_claims)
    mappings.extend(extra_mappings)
    return claims, mappings


def _collect_paperfraud_findings(
    artifacts: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> list[Finding]:
    """Convert PaperFraud rule matches to canonical findings."""
    return paperfraud_findings_from_matches(artifacts["paperfraud_matches"])


def _collect_source_data_findings(
    artifacts: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> list[Finding]:
    """Build findings from source_data priority_findings."""
    source_findings = artifacts["source_findings"]
    findings: list[Finding] = []
    for item in source_findings.get("priority_findings") or []:
        finding_id = str(item.get("finding_id"))
        findings.append(
            Finding(
                finding_id=finding_id,
                category=str(item.get("category", "")),
                risk_level=str(item.get("risk_level", "medium")),  # type: ignore[arg-type]
                summary=f"{item.get('category')} in {item.get('workbook')} / {item.get('sheet')}",
                evidence_refs=[evidence_by_finding[finding_id]]
                if finding_id in evidence_by_finding
                else [],
                benign_explanations=[
                    str(value) for value in (item.get("benign_explanations") or [])
                ],
                pressure_test_result=str(item.get("pressure_test_result", "")),
                manual_review_note=str(item.get("manual_review_note", "")),
                metadata=item,
            )
        )
    return findings


def _collect_pair_forensics_findings(
    artifacts: dict[str, Any],
    evidence_by_finding: dict[Any, str],
) -> list[Finding]:
    """Build findings from pair_forensics priority_findings."""
    pair_forensics = artifacts["pair_forensics"]
    findings: list[Finding] = []
    for item in pair_forensics.get("priority_findings") or []:
        finding_id = str(item.get("finding_id"))
        evidence_id = evidence_by_finding.get(finding_id)
        findings.append(
            Finding(
                finding_id=finding_id,
                category=str(item.get("category", "")),
                risk_level=str(item.get("risk_level", "medium")),  # type: ignore[arg-type]
                summary=(
                    f"{item.get('category')} in {item.get('workbook')} / {item.get('sheet')} "
                    f"offset={item.get('row_offset', '-')}"
                ),
                evidence_refs=[evidence_id] if evidence_id else [],
                benign_explanations=[
                    str(value) for value in (item.get("benign_explanations") or [])
                ],
                pressure_test_result=str(item.get("pressure_test_result", "")),
                manual_review_note="Pair/row-offset Source Data pattern requires sample-independence review.",
                metadata={**item, "source_artifact": "source_data_pair_forensics.json"},
            )
        )
    return findings


def _deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    """Remove duplicate findings by finding_id, keeping first occurrence."""
    seen: set[str] = set()
    unique: list[Finding] = []
    for finding in findings:
        if finding.finding_id not in seen:
            seen.add(finding.finding_id)
            unique.append(finding)
    return unique


def collect_claims_and_findings(
    workdir: Path,
    evidence_items: list[EvidenceItem],
) -> tuple[list[Claim], list[ClaimMapping], list[Finding]]:
    """Collect claims from multiple sources and build findings from all evidence types.

    Coordinates artifact loading, evidence indexing, claim/mapping collection,
    and finding construction from PaperFraud rules, source data, pair forensics,
    and visual findings.
    """
    artifacts = _load_claim_artifacts(workdir)
    evidence_by_finding, evidence_by_panel, evidence_by_artifact = (
        _build_evidence_indices(evidence_items)
    )
    claims, mappings = _collect_core_claims_and_mappings(artifacts, evidence_by_finding)

    findings: list[Finding] = []
    findings.extend(_collect_paperfraud_findings(artifacts, evidence_by_finding))
    findings.extend(_collect_source_data_findings(artifacts, evidence_by_finding))
    findings.extend(_collect_pair_forensics_findings(artifacts, evidence_by_finding))
    findings.extend(
        collect_visual_findings(artifacts, evidence_by_panel, evidence_by_artifact)
    )
    findings = _deduplicate_findings(findings)
    findings = group_similar_findings(findings)

    return claims, mappings, findings
