"""HTML report sections for PRD numeric forensics artifacts (WP2/WP3/WP7/WP8/WP10).

Renders:
- Numeric Forensics Summary (canonical signals overview)
- PaperConan Coverage Summary (detector coverage)
- Prefilter Ledger Summary (deterministic FP control)
- Review Dossiers (high-priority signal review)
- Red-Team Refute Status (adversarial review)
"""

from __future__ import annotations

from html import escape
from typing import Any


def _section_header(title: str, anchor: str) -> str:
    return (
        f'<h2 id="{anchor}" class="section-title">{escape(title)}</h2>\n'
    )


def _kv_row(key: str, value: Any) -> str:
    return (
        f'<tr><th class="kv-key">{escape(str(key))}</th>'
        f'<td class="kv-val">{escape(str(value))}</td></tr>\n'
    )


def _risk_badge(risk: str) -> str:
    color = {
        "critical": "#dc2626",
        "high": "#ea580c",
        "medium": "#ca8a04",
        "low": "#16a34a",
        "info": "#6b7280",
    }.get(risk, "#6b7280")
    return f'<span class="risk-badge" style="background:{color};color:white;padding:2px 6px;border-radius:4px;font-size:0.85em;">{escape(risk)}</span>'


# ── Numeric Forensics Summary ─────────────────────────────────────

def numeric_forensics_summary(artifacts: dict[str, Any]) -> str:
    """Render the canonical NumericSignal overview."""
    signals_data = artifacts.get("paperconan_signals", {})
    if not signals_data:
        return ""

    signals = signals_data.get("signals", [])
    if not signals:
        return ""

    total = signals_data.get("total_signals", len(signals))
    by_family = signals_data.get("counts_by_family", {})
    by_risk = signals_data.get("counts_by_risk", {})

    rows = []
    for sig in signals[:50]:  # Cap at 50 for readability
        risk = sig.get("risk_level_raw", "low")
        profile_action = sig.get("profile_action", "kept")
        impact = sig.get("impact_scope", "unknown")
        claim_refs = sig.get("claim_refs", [])

        rows.append(
            f'<tr>'
            f'<td><code>{escape(sig.get("signal_id", ""))}</code></td>'
            f'<td>{escape(sig.get("detector_family", ""))}</td>'
            f'<td>{escape(sig.get("raw_kind", ""))}</td>'
            f'<td>{_risk_badge(risk)}</td>'
            f'<td>{escape(profile_action)}</td>'
            f'<td>{escape(impact)}</td>'
            f'<td>{len(claim_refs)}</td>'
            f'</tr>\n'
        )

    family_chips = " ".join(
        f'<span class="chip">{escape(k)}: {v}</span>'
        for k, v in by_family.items()
    )

    return (
        _section_header("Numeric Forensics Summary", "numeric-forensics")
        + f'<p class="section-summary">Total canonical signals: <strong>{total}</strong></p>\n'
        + f'<div class="chip-row">{family_chips}</div>\n'
        + '<table class="findings-table">\n'
        + '<thead><tr>'
        + '<th>Signal ID</th><th>Family</th><th>Kind</th>'
        + '<th>Risk</th><th>Profile</th><th>Impact</th><th>Claims</th>'
        + '</tr></thead>\n'
        + "<tbody>\n"
        + "".join(rows)
        + "</tbody></table>\n"
    )


# ── Prefilter Ledger Summary ──────────────────────────────────────

def prefilter_ledger_summary(artifacts: dict[str, Any]) -> str:
    """Render the deterministic prefilter ledger summary."""
    ledger_data = artifacts.get("numeric_prefilter_ledger", {})
    if not ledger_data:
        return ""

    entries = ledger_data.get("entries", [])
    profile = ledger_data.get("profile", "review")
    summary = ledger_data.get("summary", {})

    if not entries and not summary:
        return ""

    kept = summary.get("kept", 0)
    demoted = summary.get("demoted", 0)
    hidden = summary.get("hidden", 0)

    # Surface entries that were downgraded/hidden
    action_rows = []
    for entry in entries:
        action = entry.get("prefilter_action", "keep")
        profile_action = entry.get("profile_action", "kept")
        if action == "keep" and profile_action == "kept":
            continue
        reason = entry.get("prefilter_reason", "no reason given")
        fp_ctx = entry.get("false_positive_context", [])
        action_rows.append(
            f'<tr>'
            f'<td><code>{escape(entry.get("signal_id", ""))}</code></td>'
            f'<td>{escape(action)}</td>'
            f'<td>{escape(profile_action)}</td>'
            f'<td>{escape(reason)}</td>'
            f'<td>{escape(", ".join(fp_ctx))}</td>'
            f'</tr>\n'
        )

    return (
        _section_header("Deterministic Prefilter Ledger", "prefilter-ledger")
        + f'<p class="section-summary">Profile: <strong>{escape(profile)}</strong> '
        + f'| Kept: {kept} | Demoted: {demoted} | Hidden: {hidden}</p>\n'
        + (
            '<table class="findings-table">\n'
            + '<thead><tr>'
            + '<th>Signal</th><th>Prefilter Action</th><th>Profile Action</th>'
            + '<th>Reason</th><th>FP Context</th>'
            + '</tr></thead>\n'
            + "<tbody>\n"
            + "".join(action_rows[:100])
            + "</tbody></table>\n"
        )
        if action_rows
        else "<p>No signals were downgraded or hidden by the prefilter.</p>\n"
    )


# ── Review Dossier Summary ────────────────────────────────────────

def review_dossier_summary(artifacts: dict[str, Any]) -> str:
    """Render review dossier overview (high-priority signals with review status)."""
    enriched = artifacts.get("enriched_signals", {})
    signals = enriched.get("signals", []) if enriched else []
    if not signals:
        return ""

    high_priority = [
        s for s in signals
        if s.get("risk_level_raw") in ("critical", "high")
    ]
    if not high_priority:
        return ""

    rows = []
    for sig in high_priority[:30]:
        claim_refs = sig.get("claim_refs", [])
        impact = sig.get("impact_scope", "unknown")
        needs = sig.get("needs_author_data", "")
        rows.append(
            f'<tr>'
            f'<td><code>{escape(sig.get("signal_id", ""))}</code></td>'
            f'<td>{_risk_badge(sig.get("risk_level_raw", "low"))}</td>'
            f'<td>{escape(impact)}</td>'
            f'<td>{len(claim_refs)}</td>'
            f'<td>{escape(needs[:100])}</td>'
            f'</tr>\n'
        )

    return (
        _section_header("High-Priority Review Dossiers", "review-dossiers")
        + f'<p class="section-summary">{len(high_priority)} signal(s) require review dossier.</p>\n'
        + '<table class="findings-table">\n'
        + '<thead><tr>'
        + '<th>Signal</th><th>Risk</th><th>Impact</th><th>Claims</th><th>Needs Author Data</th>'
        + '</tr></thead>\n'
        + "<tbody>\n"
        + "".join(rows)
        + "</tbody></table>\n"
    )


# ── Render all PRD sections ───────────────────────────────────────

def render_numeric_forensics_sections(artifacts: dict[str, Any]) -> str:
    """Render all PRD numeric forensics HTML sections."""
    parts = [
        numeric_forensics_summary(artifacts),
        prefilter_ledger_summary(artifacts),
        review_dossier_summary(artifacts),
    ]
    return "\n".join(p for p in parts if p)
