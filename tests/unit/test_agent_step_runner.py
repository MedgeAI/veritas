"""Tests for engine.investigation.agent_step_runner module.

Merged from: test_agent_step_runner.py + test_agent_step_runner_enhanced.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import json
import subprocess

from engine.investigation.agent_step_runner import AgentStepRunner


# ===========================================================================
# test_agent_step_runner.py
# ===========================================================================


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


# -----------------------------------------------------------------------
# 1. success_returns_validated_output
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_success_returns_validated_output(mock_run: MagicMock, tmp_path: Path) -> None:
    valid_json = '{"schema_version": "1.0", "claim": "test"}'
    mock_run.return_value = _make_completed(stdout=valid_json)

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
    )

    assert result.status == "success"
    assert result.role == "test_role"
    assert result.output == {"schema_version": "1.0", "claim": "test"}
    assert result.error_category is None


# -----------------------------------------------------------------------
# 2. timeout_error_category
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_timeout_error_category(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="opencode", timeout=10)

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
        timeout_seconds=10,
    )

    assert result.status == "failed"
    assert result.error_category == "timeout"


# -----------------------------------------------------------------------
# 3. schema_validation_error_category (invalid JSON)
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_schema_validation_error_category(
    mock_run: MagicMock,
    mock_extract: MagicMock,
    tmp_path: Path,
) -> None:
    mock_run.return_value = _make_completed(stdout="not json at all")
    mock_extract.side_effect = ValueError("no JSON object found")

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "schema_validation"


# -----------------------------------------------------------------------
# 4. permission_rejected_error_category
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_permission_rejected_error_category(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    mock_run.return_value = _make_completed(
        returncode=1,
        stderr="Error: permission auto-reject for tool bash",
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "permission_rejected"


# -----------------------------------------------------------------------
# 5. model_failure_error_category
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_model_failure_error_category(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = _make_completed(
        returncode=1,
        stderr="upstream model error: rate limit exceeded",
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "model_failure"


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_opencode_error_event_is_model_failure(
    mock_run: MagicMock,
    mock_extract: MagicMock,
    tmp_path: Path,
) -> None:
    mock_run.return_value = _make_completed(
        returncode=0,
        stdout=(
            '{"type":"error","error":{"name":"APIError",'
            '"data":{"message":"You did not provide an API key.","statusCode":401}}}'
        ),
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "model_failure"
    assert "APIError status=401" in result.metadata["last_detail"]
    mock_extract.assert_not_called()


# -----------------------------------------------------------------------
# 6. non_zero_exit_error_category
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_non_zero_exit_error_category(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = _make_completed(
        returncode=2,
        stderr="unexpected condition encountered",
    )

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "failed"
    assert result.error_category == "non_zero_exit"


# -----------------------------------------------------------------------
# 7. retry_on_validation_failure
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_retry_on_validation_failure(
    mock_run: MagicMock,
    mock_extract: MagicMock,
    tmp_path: Path,
) -> None:
    invalid_json = "garbage output"
    valid_json = '{"schema_version": "1.0", "result": "ok"}'

    mock_run.side_effect = [
        _make_completed(stdout=invalid_json),
        _make_completed(stdout=valid_json),
    ]
    mock_extract.side_effect = [
        ValueError("no JSON object found"),
        {"schema_version": "1.0", "result": "ok"},
    ]

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=1,
    )

    assert result.status == "success"
    assert result.output == {"schema_version": "1.0", "result": "ok"}
    assert result.metadata["attempts"] == 2
    assert mock_run.call_count == 2


# -----------------------------------------------------------------------
# 8. log_artifact_written_on_failure
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_log_artifact_written_on_failure(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = _make_completed(
        returncode=1,
        stdout="partial output",
        stderr="something went wrong",
    )

    log_dir = tmp_path / "logs"
    runner = AgentStepRunner(project_root=tmp_path)
    runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
        log_dir=log_dir,
    )

    log_files = list(log_dir.glob("test_role_*.log"))
    assert len(log_files) == 1

    content = log_files[0].read_text()
    assert "partial output" in content
    assert "something went wrong" in content
    assert "test_role" in content


# -----------------------------------------------------------------------
# 9. log_ref_in_failed_result
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_log_ref_in_failed_result(mock_run: MagicMock, tmp_path: Path) -> None:
    mock_run.return_value = _make_completed(
        returncode=1,
        stderr="fatal error occurred",
    )

    log_dir = tmp_path / "logs"
    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="my_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
        log_dir=log_dir,
    )

    assert result.status == "failed"
    assert result.log_ref is not None
    assert "my_role" in result.log_ref
    assert result.log_ref.endswith(".log")


# -----------------------------------------------------------------------
# 10. metadata_includes_model_and_runtime
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_metadata_includes_model_and_runtime(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    valid_json = '{"schema_version": "1.0"}'
    mock_run.return_value = _make_completed(stdout=valid_json)

    runner = AgentStepRunner(
        project_root=tmp_path,
        model="dashscope/qwen3.7-max",
    )
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
    )

    assert result.status == "success"
    assert result.metadata["model"] == "dashscope/qwen3.7-max"
    assert "runtime_seconds" in result.metadata
    assert "attempts" in result.metadata
    assert result.metadata["attempts"] == 1
    assert isinstance(result.metadata["runtime_seconds"], float)


# -----------------------------------------------------------------------
# 11. extract_json_reused
# -----------------------------------------------------------------------


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_extract_json_reused(
    mock_run: MagicMock,
    mock_extract: MagicMock,
    tmp_path: Path,
) -> None:
    mock_run.return_value = _make_completed(stdout='{"key": "value"}')
    mock_extract.return_value = {"key": "value"}

    runner = AgentStepRunner(project_root=tmp_path)
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "success"
    mock_extract.assert_called_once_with('{"key": "value"}')


@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_log_artifact_includes_prompt_preview_and_trace(
    mock_run: MagicMock, tmp_path: Path
) -> None:
    """P0/P1: log includes prompt preview (first 500 chars) and trace JSON.

    Full prompt is NOT embedded — only a 500-char preview — so that
    hallucination debugging is possible without bloating the log.
    A structured trace JSON is written alongside the log.
    """
    mock_run.return_value = _make_completed(
        returncode=1,
        stderr="fatal error occurred",
    )

    long_prompt = "P" * 5000
    log_dir = tmp_path / "logs"
    runner = AgentStepRunner(project_root=tmp_path)
    runner.run(
        role="my_role",
        prompt=long_prompt,
        output_validator=_identity_validator,
        max_retries=0,
        log_dir=log_dir,
    )

    log_file = next(log_dir.glob("my_role_*.log"))
    content = log_file.read_text()
    # Full prompt should NOT appear
    assert long_prompt not in content
    # Prompt preview (first 500 chars) should appear
    assert "Prompt Summary" in content
    assert "P" * 500 in content
    # Structured trace JSON should exist alongside the log
    trace_files = list(log_dir.glob("step_trace_my_role_*.json"))
    assert len(trace_files) == 1
    import json

    trace = json.loads(trace_files[0].read_text())
    assert trace["role"] == "my_role"
    assert trace["input"]["prompt_chars"] == 5000
    assert "prompt_sha256" in trace["input"]


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_runner_loads_project_dotenv_for_subprocess(
    mock_run: MagicMock,
    mock_extract: MagicMock,
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text(
        "DASHSCOPE_API_KEY=dotenv-secret\n", encoding="utf-8"
    )
    mock_run.return_value = _make_completed(stdout='{"schema_version": "1.0"}')
    mock_extract.return_value = {"schema_version": "1.0"}

    runner = AgentStepRunner(project_root=tmp_path, env={})
    result = runner.run(
        role="test_role",
        prompt="test prompt",
        output_validator=_identity_validator,
        max_retries=0,
    )

    assert result.status == "success"
    assert mock_run.call_args.kwargs["env"]["DASHSCOPE_API_KEY"] == "dotenv-secret"


# ===========================================================================
# test_agent_step_runner_enhanced.py
# ===========================================================================


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
