"""Tests for AgentStepRunner — Stream B of Agent Function Runtime P0."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

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
def test_permission_rejected_error_category(mock_run: MagicMock, tmp_path: Path) -> None:
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
def test_metadata_includes_model_and_runtime(mock_run: MagicMock, tmp_path: Path) -> None:
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
def test_log_artifact_redacts_long_prompt(mock_run: MagicMock, tmp_path: Path) -> None:
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
    assert long_prompt not in content
    assert "<prompt chars=5000 sha256=" in content


@patch("engine.investigation.agent_step_runner.extract_json")
@patch("engine.investigation.agent_step_runner.subprocess.run")
def test_runner_loads_project_dotenv_for_subprocess(
    mock_run: MagicMock,
    mock_extract: MagicMock,
    tmp_path: Path,
) -> None:
    (tmp_path / ".env").write_text("DASHSCOPE_API_KEY=dotenv-secret\n", encoding="utf-8")
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
