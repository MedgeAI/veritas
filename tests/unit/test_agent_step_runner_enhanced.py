"""Enhanced tests for AgentStepRunner — additional edge cases and error paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine.investigation.agent_step_runner import AgentStepRunner


def _make_completed(
    *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> MagicMock:
    completed = MagicMock()
    completed.returncode = returncode
    completed.stdout = stdout
    completed.stderr = stderr
    return completed


def _identity_validator(data: dict) -> dict:
    return data


# -----------------------------------------------------------------------
# Error classification edge cases
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_os_error_classified_as_non_zero_exit(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.side_effect = OSError("opencode binary not found")

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        max_retries=0,
    )
    assert result.status == "failed"
    assert result.error_category == "non_zero_exit"


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_permission_rejected_via_auto_reject(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(
        returncode=1,
        stderr="Error: tool 'bash' was auto-rejected by policy",
    )
    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        max_retries=0,
    )
    assert result.error_category == "permission_rejected"


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_generic_error_in_stderr_is_model_failure(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(
        returncode=1,
        stderr="something error happened",
    )
    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        max_retries=0,
    )
    assert result.error_category == "model_failure"


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_non_error_non_zero_exit_is_non_zero_exit(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(
        returncode=1,
        stderr="unexpected condition occurred",
    )
    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        max_retries=0,
    )
    # "occurred" doesn't match "error" or "failed" — so it's non_zero_exit
    assert result.error_category == "non_zero_exit"


# -----------------------------------------------------------------------
# opencode error event extraction
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_opencode_error_event_extracted(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    error_json = json.dumps(
        {
            "type": "error",
            "error": {
                "name": "RateLimitError",
                "data": {"message": "Too many requests", "statusCode": 429},
            },
        }
    )
    mock_run.return_value = _make_completed(returncode=0, stdout=error_json)

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        max_retries=0,
    )
    assert result.status == "failed"
    assert result.error_category == "model_failure"
    assert "RateLimitError" in result.metadata["last_detail"]
    assert "429" in result.metadata["last_detail"]


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_opencode_error_without_status_code(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    error_json = json.dumps(
        {
            "type": "error",
            "error": {
                "name": "UnknownError",
                "data": {"message": "Something went wrong"},
            },
        }
    )
    mock_run.return_value = _make_completed(returncode=0, stdout=error_json)

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        max_retries=0,
    )
    assert result.error_category == "model_failure"
    assert "UnknownError" in result.metadata["last_detail"]


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_opencode_error_without_error_dict(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    error_json = json.dumps({"type": "error", "error": "string error"})
    mock_run.return_value = _make_completed(returncode=0, stdout=error_json)

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        max_retries=0,
    )
    assert result.error_category == "model_failure"
    assert "unknown opencode error" in result.metadata["last_detail"]


# -----------------------------------------------------------------------
# Retry behavior
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_retry_exhausted_returns_failed(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(returncode=0, stdout="garbage")
    mock_extract.side_effect = ValueError("no JSON")

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        max_retries=2,
    )
    assert result.status == "failed"
    assert result.error_category == "schema_validation"
    assert result.metadata["attempts"] == 3


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_retry_prompt_includes_previous_error(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.side_effect = [
        _make_completed(returncode=1, stderr="something error happened"),
        _make_completed(stdout='{"valid": true}'),
    ]

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="original prompt",
        output_validator=_identity_validator,
        max_retries=1,
    )
    assert result.status == "success"
    # Second call should include previous error in prompt
    second_call_prompt = mock_run.call_args_list[1][0][0][2]
    assert "Previous attempt failed" in second_call_prompt
    assert "original prompt" in second_call_prompt


# -----------------------------------------------------------------------
# Validator rejection
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_validator_rejection_triggers_retry(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    mock_run.side_effect = [
        _make_completed(stdout='{"key": "value"}'),
        _make_completed(stdout='{"key": "valid"}'),
    ]
    mock_extract.return_value = {"key": "value"}

    def strict_validator(data: dict) -> dict:
        if data.get("key") == "value":
            raise ValueError("missing required field: schema_version")
        return data

    mock_extract.side_effect = [
        {"key": "value"},
        {"key": "valid", "schema_version": "1.0"},
    ]

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=strict_validator,
        max_retries=1,
    )
    assert result.status == "success"
    assert result.metadata["attempts"] == 2


# -----------------------------------------------------------------------
# Files and context_pack
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_files_added_to_command(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(stdout='{"ok": true}')
    mock_extract.return_value = {"ok": True}

    existing_file = tmp_path / "context.json"
    existing_file.write_text("{}")

    runner = AgentStepRunner(project_root=tmp_path)
    runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        files=[existing_file],
        max_retries=0,
    )
    command = mock_run.call_args[0][0]
    assert "--file" in command
    assert str(existing_file) in command


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_context_pack_added_to_command(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(stdout='{"ok": true}')
    mock_extract.return_value = {"ok": True}

    context_pack = tmp_path / "context_pack.json"
    context_pack.write_text("{}")

    runner = AgentStepRunner(project_root=tmp_path)
    runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        context_pack_path=context_pack,
        max_retries=0,
    )
    command = mock_run.call_args[0][0]
    assert str(context_pack) in command


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_nonexistent_file_not_added(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(stdout='{"ok": true}')
    mock_extract.return_value = {"ok": True}

    runner = AgentStepRunner(project_root=tmp_path)
    runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        files=[tmp_path / "nonexistent.json"],
        max_retries=0,
    )
    command = mock_run.call_args[0][0]
    assert "--file" not in command


# -----------------------------------------------------------------------
# Success log artifact
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_success_log_artifact_written(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(stdout='{"ok": true}')
    mock_extract.return_value = {"ok": True}

    log_dir = tmp_path / "logs"
    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
        log_dir=log_dir,
    )
    assert result.status == "success"
    assert result.log_ref is not None
    log_files = list(log_dir.glob("test_role_*.log"))
    assert len(log_files) == 1


# -----------------------------------------------------------------------
# Multiple opencode errors in stdout
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_multiple_opencode_errors_limits_to_three(
    mock_run: MagicMock, mock_extract: MagicMock, tmp_path: Path
) -> None:
    errors = "\n".join(
        json.dumps(
            {
                "type": "error",
                "error": {"name": f"Error{i}", "data": {"message": f"msg{i}"}},
            }
        )
        for i in range(5)
    )
    mock_run.return_value = _make_completed(returncode=0, stdout=errors)

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test",
        output_validator=_identity_validator,
        max_retries=0,
    )
    assert result.error_category == "model_failure"
    detail = result.metadata["last_detail"]
    assert "Error0" in detail
    assert "Error2" in detail
    # Should limit to 3 errors
    assert "Error3" not in detail
