"""Tests for per-user data isolation in CaseStore.

Verifies that:
- list_cases only returns cases owned by the requesting user.
- get_case raises PermissionError when the caller is not the owner.
- create_case records the correct owner.
- update_case is restricted to the owner.
- delete_case is restricted to the owner.
"""
from __future__ import annotations

import pytest

from web.backend.veritas_web.case_store import CaseStore
from web.backend.veritas_web.models import CaseRecord


@pytest.fixture
def store(tmp_path):
    return CaseStore(root=tmp_path)


# -- create_case sets owner correctly ------------------------------------------


def test_create_case_sets_owner(store):
    case = store.create_case(user_id="alice", paper_title="Paper A")
    assert case.owner == "alice"
    # Reloading from disk should preserve owner.
    reloaded = store.get_case(case.case_id, user_id="alice")
    assert reloaded.owner == "alice"


def test_create_case_with_record_sets_owner(store):
    record = CaseRecord(case_id="custom-case-1", paper_title="Custom")
    case = store.create_case(case=record, user_id="bob")
    assert case.owner == "bob"
    assert case.case_id == "custom-case-1"


def test_create_case_default_owner_is_operator(store):
    case = store.create_case()
    assert case.owner == "operator"


# -- list_cases filters by owner -----------------------------------------------


def test_list_cases_filters_by_owner(store):
    store.create_case(user_id="alice", paper_title="A1", case_id="a-one")
    store.create_case(user_id="alice", paper_title="A2", case_id="a-two")
    store.create_case(user_id="bob", paper_title="B1", case_id="b-one")

    alice_cases = store.list_cases(user_id="alice")
    assert {c.case_id for c in alice_cases} == {"a-one", "a-two"}

    bob_cases = store.list_cases(user_id="bob")
    assert {c.case_id for c in bob_cases} == {"b-one"}


def test_list_cases_no_user_returns_all(store):
    store.create_case(user_id="alice", case_id="a-one")
    store.create_case(user_id="bob", case_id="b-one")
    # Internal callers (user_id=None) should see everything.
    all_cases = store.list_cases()
    assert {c.case_id for c in all_cases} == {"a-one", "b-one"}


# -- get_case enforces ownership -----------------------------------------------


def test_get_case_owner_can_read(store):
    case = store.create_case(user_id="alice", case_id="shared-case")
    loaded = store.get_case("shared-case", user_id="alice")
    assert loaded.case_id == case.case_id


def test_get_case_non_owner_is_denied(store):
    store.create_case(user_id="alice", case_id="alice-case")
    with pytest.raises(PermissionError):
        store.get_case("alice-case", user_id="bob")


def test_get_case_no_user_bypasses_check(store):
    """Internal callers (user_id=None) are not restricted."""
    store.create_case(user_id="alice", case_id="alice-case")
    loaded = store.get_case("alice-case")  # no user_id -> internal bypass
    assert loaded.owner == "alice"


# -- update_case enforces ownership --------------------------------------------


def test_update_case_owner_can_update(store):
    store.create_case(user_id="alice", case_id="updatable")
    updated = store.update_case("updatable", {"paper_title": "New Title"}, user_id="alice")
    assert updated.paper_title == "New Title"


def test_update_case_non_owner_is_denied(store):
    store.create_case(user_id="alice", case_id="protected")
    with pytest.raises(PermissionError):
        store.update_case("protected", {"paper_title": "Hacked"}, user_id="bob")
    # Original should be unchanged.
    original = store.get_case("protected", user_id="alice")
    assert original.paper_title != "Hacked"


def test_update_case_immutable_case_id(store):
    """case_id cannot be overwritten via update_case."""
    store.create_case(user_id="alice", case_id="original-id")
    updated = store.update_case("original-id", {"case_id": "new-id"}, user_id="alice")
    assert updated.case_id == "original-id"


# -- delete_case enforces ownership --------------------------------------------


def test_delete_case_owner_can_delete(store):
    store.create_case(user_id="alice", case_id="deletable")
    result = store.delete_case("deletable", user_id="alice")
    assert result is True
    # Subsequent access raises FileNotFoundError.
    with pytest.raises(FileNotFoundError):
        store.get_case("deletable", user_id="alice")


def test_delete_case_non_owner_is_denied(store):
    store.create_case(user_id="alice", case_id="protected")
    with pytest.raises(PermissionError):
        store.delete_case("protected", user_id="bob")
    # Case must still exist.
    assert store.get_case("protected", user_id="alice").case_id == "protected"
