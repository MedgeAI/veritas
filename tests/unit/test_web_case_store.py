from __future__ import annotations

import pytest

from web.backend.veritas_web.case_store import CaseStore
from web.backend.veritas_web.models import normalize_case_status, normalize_run_status


def test_case_store_creates_case_and_input(tmp_path) -> None:
    store = CaseStore(tmp_path / "web_data")

    case = store.create_case(paper_title="Demo paper", user_id="operator", case_id="demo-case")
    input_path = store.write_input(case.case_id, "paper.pdf", b"%PDF-1.4\n")
    loaded = store.get_case(case.case_id)

    assert case.case_id == "demo-case"
    assert input_path.name == "paper.pdf"
    assert loaded.status == "Uploaded"
    assert loaded.input_count == 1


def test_case_store_records_run_events(tmp_path) -> None:
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    run = store.create_run(case.case_id)

    store.append_event(case.case_id, run.run_id, {"event": "audit_start", "case_id": case.case_id})
    store.append_event(case.case_id, run.run_id, {"event": "audit_end", "status": "completed"})

    assert [event["event"] for event in store.list_events(case.case_id, run.run_id)] == ["audit_start", "audit_end"]


def test_case_store_lists_runs(tmp_path) -> None:
    store = CaseStore(tmp_path / "web_data")
    case = store.create_case(case_id="demo-case")
    first = store.create_run(case.case_id)
    second = store.create_run(case.case_id)

    assert {run.run_id for run in store.list_runs(case.case_id)} == {first.run_id, second.run_id}
    assert {run.run_id for run in store.list_all_runs()} == {first.run_id, second.run_id}


def test_status_normalizers_reject_invalid_values() -> None:
    assert normalize_case_status("Draft") == "Draft"
    assert normalize_run_status("queued") == "queued"

    with pytest.raises(ValueError, match="invalid case status"):
        normalize_case_status("completed_typo")

    with pytest.raises(ValueError, match="invalid run status"):
        normalize_run_status("running_typo")
