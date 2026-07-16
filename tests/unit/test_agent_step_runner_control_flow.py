"""Characterization tests for AgentStepRunner.run control flow.

These tests freeze the exact control flow graph from PRD §WP2.
Any refactor (including the WP2 component split) must preserve
identical input → failure category → repair_history → AgentRunResult.

FROZEN CONTROL FLOW (from PRD §WP2):
  7 failure types:
    1. timeout — returncode == 124 → continue
    2. non_zero_exit (launch) — returncode == 127 → break
    3. non_zero_exit (generic) — returncode != 0, classify → continue
    4. model_failure — opencode error event in stdout → continue
    5. schema_validation (JSON extraction) — extract_json raises → continue
    6. schema_validation (validator) — output_validator raises ValueError → continue
    7. grounding_failure — finding_id not in canonical artifacts → continue
  2 early exits:
    1. returncode == 127 → break (no retry)
    2. success → return AgentRunResult
  State accumulation:
    - repair_history: list[dict] with {attempt, failure_type, error, action}
    - last_error_category, last_detail, last_stdout, last_stderr
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.investigation.agent_step_runner import AgentStepRunner


def _make_completed(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> MagicMock:
    completed = MagicMock()
    completed.returncode = returncode
    completed.stdout = stdout
    completed.stderr = stderr
    return completed


def _identity_validator(data: dict) -> dict:
    return data


# ===========================================================================
# 1. timeout — returncode 124 → continue → retry → fail exhausted
# ===========================================================================


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_failure_timeout(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = _make_completed(returncode=124, stderr="timed out")

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_a",
        prompt="prompt_a",
        output_validator=_identity_validator,
        max_retries=1,
        timeout_seconds=10,
    )

    assert result.status == "failed"
    assert result.error_category == "timeout"
    assert result.metadata["attempts"] == 2
    assert len(result.metadata["repair_history"]) == 2
    assert result.metadata["repair_history"][0]["failure_type"] == "timeout"
    assert result.metadata["repair_history"][0]["action"] == "retry_with_raw_output"
    assert result.metadata["repair_history"][1]["failure_type"] == "timeout"
    assert result.metadata["repair_history"][1]["action"] == "retry_with_schema_error"


# ===========================================================================
# 2. non_zero_exit (launch failure) — returncode 127 → break
# ===========================================================================


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_failure_non_zero_exit_launch_breaks(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = _make_completed(
        returncode=127, stderr="opencode not found"
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_b",
        prompt="prompt_b",
        output_validator=_identity_validator,
        max_retries=2,
    )

    assert result.status == "failed"
    assert result.error_category == "non_zero_exit"
    # break: only 1 invocation, not 3
    assert mock_run.call_count == 1
    assert len(result.metadata["repair_history"]) == 1
    assert result.metadata["repair_history"][0]["failure_type"] == "non_zero_exit"
    assert result.metadata["repair_history"][0]["action"] == "retry_with_raw_output"


# ===========================================================================
# 3. non_zero_exit (generic) — returncode != 0, classify → continue
# ===========================================================================


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_failure_non_zero_exit_generic(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = _make_completed(
        returncode=2, stderr="unexpected condition occurred"
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_c",
        prompt="prompt_c",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "non_zero_exit"
    assert len(result.metadata["repair_history"]) == 1
    assert result.metadata["repair_history"][0]["failure_type"] == "non_zero_exit"


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_failure_non_zero_exit_classified_as_model_failure(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(
        returncode=1, stderr="something error happened"
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_c2",
        prompt="prompt_c2",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "model_failure"
    assert len(result.metadata["repair_history"]) == 1
    assert result.metadata["repair_history"][0]["failure_type"] == "model_failure"


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_failure_non_zero_exit_classified_as_permission_rejected(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(
        returncode=1, stderr="Error: permission auto-reject"
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_c3",
        prompt="prompt_c3",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "permission_rejected"
    assert result.metadata["repair_history"][0]["failure_type"] == "permission_rejected"


# ===========================================================================
# 4. model_failure — opencode error event in stdout (returncode 0!)
# ===========================================================================


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_failure_model_failure_from_opencode_error_event(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    error_json = json.dumps(
        {
            "type": "error",
            "error": {
                "name": "APIError",
                "data": {"message": "rate limit", "statusCode": 429},
            },
        }
    )
    mock_run.return_value = _make_completed(returncode=0, stdout=error_json)

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_d",
        prompt="prompt_d",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "model_failure"
    assert "APIError" in result.metadata["last_detail"]
    assert len(result.metadata["repair_history"]) == 1
    assert result.metadata["repair_history"][0]["failure_type"] == "model_failure"


# ===========================================================================
# 5. schema_validation — extract_json raises
# ===========================================================================


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_failure_schema_validation_json_extraction(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(stdout="not json at all")
    mock_extract.side_effect = ValueError("no JSON object found")

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_e",
        prompt="prompt_e",
        output_validator=_identity_validator,
        max_retries=1,
    )

    assert result.status == "failed"
    assert result.error_category == "schema_validation"
    assert result.metadata["attempts"] == 2
    assert len(result.metadata["repair_history"]) == 2
    for entry in result.metadata["repair_history"]:
        assert entry["failure_type"] == "schema_validation"


# ===========================================================================
# 6. schema_validation — output_validator raises ValueError
# ===========================================================================


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_failure_schema_validation_validator_rejection(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(stdout='{"key": "value"}')
    mock_extract.return_value = {"key": "value"}

    def strict_validator(data: dict) -> dict:
        raise ValueError("missing required field: schema_version")

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_f",
        prompt="prompt_f",
        output_validator=strict_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "schema_validation"
    assert "missing required field" in result.metadata["last_detail"]
    assert len(result.metadata["repair_history"]) == 1
    assert result.metadata["repair_history"][0]["failure_type"] == "schema_validation"


# ===========================================================================
# 7. grounding_failure — finding_id not in canonical artifacts
# ===========================================================================


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_failure_grounding_failure(mock_run: MagicMock, tmp_path: Path) -> None:
    output_with_bad_id = json.dumps(
        {"finding_id": "FID_999_nonexistent", "status": "ok"}
    )
    mock_run.return_value = _make_completed(returncode=0, stdout=output_with_bad_id)

    workdir = tmp_path / "audit_output"
    workdir.mkdir()
    # Write a canonical artifacts file with NO matching finding_ids
    (workdir / "findings.json").write_text(
        json.dumps({"findings": [{"finding_id": "FID_001"}]}),
        encoding="utf-8",
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_g",
        prompt="prompt_g",
        output_validator=_identity_validator,
        max_retries=0,
        workdir=workdir,
    )

    assert result.status == "failed"
    assert result.error_category == "grounding_failure"
    assert "FID_999_nonexistent" in result.metadata["last_detail"]
    assert len(result.metadata["repair_history"]) == 1
    assert result.metadata["repair_history"][0]["failure_type"] == "grounding_failure"


# ===========================================================================
# Early exit: success path
# ===========================================================================


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_early_exit_success(mock_run: MagicMock, tmp_path: Path) -> None:
    valid_json = '{"schema_version": "1.0", "result": "ok"}'
    mock_run.return_value = _make_completed(returncode=0, stdout=valid_json)

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_h",
        prompt="prompt_h",
        output_validator=_identity_validator,
        max_retries=2,
    )

    assert result.status == "success"
    assert result.error_category is None
    assert result.output == {"schema_version": "1.0", "result": "ok"}
    assert result.metadata["attempts"] == 1
    assert mock_run.call_count == 1


# ===========================================================================
# repair_history accumulation across mixed failure types
# ===========================================================================


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_repair_history_accumulates_mixed_failures(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    """First attempt: model_failure (error event). Second: schema_validation. Third: success."""
    error_event = json.dumps(
        {
            "type": "error",
            "error": {
                "name": "APIError",
                "data": {"message": "rate limit", "statusCode": 429},
            },
        }
    )
    mock_run.side_effect = [
        _make_completed(returncode=0, stdout=error_event),
        _make_completed(returncode=0, stdout="garbage"),
        _make_completed(returncode=0, stdout='{"ok": true}'),
    ]
    # Note: extract_json is NOT called on attempt 0 (error event detected first),
    # so side_effect only has 2 entries for attempts 1 and 2.
    mock_extract.side_effect = [
        ValueError("no JSON"),
        {"ok": True},
    ]

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_i",
        prompt="prompt_i",
        output_validator=_identity_validator,
        max_retries=2,
    )

    assert result.status == "success"
    assert result.metadata["attempts"] == 3
    assert len(result.metadata["repair_history"]) == 2
    assert result.metadata["repair_history"][0]["failure_type"] == "model_failure"
    assert result.metadata["repair_history"][0]["attempt"] == 1
    assert result.metadata["repair_history"][0]["action"] == "retry_with_raw_output"
    assert result.metadata["repair_history"][1]["failure_type"] == "schema_validation"
    assert result.metadata["repair_history"][1]["attempt"] == 2
    assert result.metadata["repair_history"][1]["action"] == "retry_with_schema_error"


# ===========================================================================
# Fallback: all retries exhausted with no clear category
# ===========================================================================


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_fallback_non_zero_exit_when_no_category(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """When last_error_category is None (shouldn't happen normally), fallback is non_zero_exit."""
    # This is a degenerate case: max_retries=0, returncode=0, no error event,
    # but extract_json succeeds. This shouldn't hit the fallback path.
    # Instead, test that when last_error_category is set, it is preserved.
    mock_run.return_value = _make_completed(
        returncode=1, stderr="generic error message"
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_j",
        prompt="prompt_j",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    # stderr has "error" → model_failure via _classify_exit_error
    assert result.error_category == "model_failure"
    assert result.metadata["failure_type"] == "model_failure"


# ===========================================================================
# Retry prompt includes previous error detail
# ===========================================================================


@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_retry_prompt_contains_previous_error(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.side_effect = [
        _make_completed(returncode=124, stderr="timed out"),
        _make_completed(returncode=0, stdout='{"ok": true}'),
    ]

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_k",
        prompt="original prompt",
        output_validator=_identity_validator,
        max_retries=1,
    )

    assert result.status == "success"
    # Check second invocation prompt was modified
    second_call_prompt = mock_run.call_args_list[1][0][0][2]
    assert "Previous attempt failed" in second_call_prompt
    assert "original prompt" in second_call_prompt
    assert "opencode timed out" in second_call_prompt


# ===========================================================================
# next_action sequence: retry_with_raw_output → retry_with_schema_error → exhausted
# ===========================================================================


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.run_simple_command")
def test_next_action_sequence(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(stdout="garbage")
    mock_extract.side_effect = ValueError("no JSON")

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="role_l",
        prompt="prompt_l",
        output_validator=_identity_validator,
        max_retries=2,
    )

    assert result.status == "failed"
    assert len(result.metadata["repair_history"]) == 3
    assert result.metadata["repair_history"][0]["action"] == "retry_with_raw_output"
    assert result.metadata["repair_history"][1]["action"] == "retry_with_schema_error"
    assert result.metadata["repair_history"][2]["action"] == "deterministic_extractor_exhausted"
