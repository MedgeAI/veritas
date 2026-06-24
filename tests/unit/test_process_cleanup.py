"""Tests for engine.tasks.process_cleanup.

Validates best-effort cleanup of MinerU processes, Docker containers,
and temp files. All operations must be resilient to failures and missing
optional dependencies (psutil, docker, torch).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.tasks.process_cleanup import (
    _clean_temp_files,
    _clear_gpu_cache,
    _kill_mineru_processes,
    _stop_docker_containers,
    cleanup_audit_processes,
)


class TestKillMineruProcesses:
    """Tests for _kill_mineru_processes."""

    def test_kill_mineru_processes_matches_case_id(self):
        """Verify that only MinerU processes matching case_id are killed."""
        mock_proc1 = MagicMock()
        mock_proc1.info = {"pid": 1234, "cmdline": ["mineru", "process", "case-abc"], "name": "mineru"}
        mock_proc1.kill = MagicMock()

        mock_proc2 = MagicMock()
        mock_proc2.info = {"pid": 5678, "cmdline": ["mineru", "process", "case-xyz"], "name": "mineru"}
        mock_proc2.kill = MagicMock()

        mock_proc3 = MagicMock()
        mock_proc3.info = {"pid": 9999, "cmdline": ["python", "other_script"], "name": "python"}
        mock_proc3.kill = MagicMock()

        mock_psutil = MagicMock()
        mock_psutil.process_iter.return_value = [mock_proc1, mock_proc2, mock_proc3]

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            killed, errors = _kill_mineru_processes("case-abc")

        assert killed == [1234]
        assert errors == []
        mock_proc1.kill.assert_called_once()
        mock_proc2.kill.assert_not_called()
        mock_proc3.kill.assert_not_called()

    def test_kill_mineru_processes_no_matching_processes(self):
        """Verify empty result when no MinerU processes match case_id."""
        mock_proc = MagicMock()
        mock_proc.info = {"pid": 1111, "cmdline": ["mineru", "case-other"], "name": "mineru"}
        mock_proc.kill = MagicMock()

        mock_psutil = MagicMock()
        mock_psutil.process_iter.return_value = [mock_proc]

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            killed, errors = _kill_mineru_processes("case-xyz")

        assert killed == []
        assert errors == []
        mock_proc.kill.assert_not_called()

    def test_kill_mineru_processes_handles_kill_failure(self):
        """Verify that kill failures are collected but don't raise."""
        mock_proc = MagicMock()
        mock_proc.info = {"pid": 2222, "cmdline": ["mineru", "case-fail"], "name": "mineru"}
        mock_proc.kill.side_effect = PermissionError("Access denied")

        mock_psutil = MagicMock()
        mock_psutil.process_iter.return_value = [mock_proc]

        with patch.dict("sys.modules", {"psutil": mock_psutil}):
            killed, errors = _kill_mineru_processes("case-fail")

        assert killed == []
        assert len(errors) == 1
        assert "pid=2222" in errors[0]
        assert "Access denied" in errors[0]

    def test_kill_mineru_processes_missing_psutil(self):
        """Verify graceful handling when psutil is not installed."""
        import sys

        # Temporarily hide psutil from sys.modules
        psutil_module = sys.modules.pop("psutil", None)
        try:
            with patch.dict("sys.modules", {"psutil": None}):
                killed, errors = _kill_mineru_processes("any-case")

            assert killed == []
            assert errors == []
        finally:
            if psutil_module is not None:
                sys.modules["psutil"] = psutil_module


class TestStopDockerContainers:
    """Tests for _stop_docker_containers."""

    def test_stop_docker_containers_stops_matching_containers(self):
        """Verify containers with matching label are stopped."""
        mock_container1 = MagicMock()
        mock_container1.id = "container-abc"
        mock_container1.stop = MagicMock()

        mock_container2 = MagicMock()
        mock_container2.id = "container-xyz"
        mock_container2.stop = MagicMock()

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container1, mock_container2]

        mock_docker = MagicMock()
        mock_docker.from_env.return_value = mock_client

        with patch.dict("sys.modules", {"docker": mock_docker}):
            stopped, errors = _stop_docker_containers("run-123")

        assert stopped == ["container-abc", "container-xyz"]
        assert errors == []
        mock_client.containers.list.assert_called_once_with(
            filters={"label": "veritas_run_id=run-123"}
        )
        mock_container1.stop.assert_called_once_with(timeout=10)
        mock_container2.stop.assert_called_once_with(timeout=10)

    def test_stop_docker_containers_no_matching_containers(self):
        """Verify empty result when no containers match run_id."""
        mock_client = MagicMock()
        mock_client.containers.list.return_value = []

        mock_docker = MagicMock()
        mock_docker.from_env.return_value = mock_client

        with patch.dict("sys.modules", {"docker": mock_docker}):
            stopped, errors = _stop_docker_containers("run-456")

        assert stopped == []
        assert errors == []

    def test_stop_docker_containers_handles_stop_failure(self):
        """Verify that container stop failures are collected but don't raise."""
        mock_container = MagicMock()
        mock_container.id = "container-fail"
        mock_container.stop.side_effect = RuntimeError("Container not responding")

        mock_client = MagicMock()
        mock_client.containers.list.return_value = [mock_container]

        mock_docker = MagicMock()
        mock_docker.from_env.return_value = mock_client

        with patch.dict("sys.modules", {"docker": mock_docker}):
            stopped, errors = _stop_docker_containers("run-789")

        assert stopped == []
        assert len(errors) == 1
        assert "container-fail" in errors[0]
        assert "Container not responding" in errors[0]

    def test_stop_docker_containers_handles_docker_connection_failure(self):
        """Verify graceful handling when Docker daemon is unavailable."""
        mock_docker = MagicMock()
        mock_docker.from_env.side_effect = RuntimeError("Cannot connect to Docker")

        with patch.dict("sys.modules", {"docker": mock_docker}):
            stopped, errors = _stop_docker_containers("run-999")

        assert stopped == []
        assert len(errors) == 1
        assert "Failed to connect to Docker" in errors[0]

    def test_stop_docker_containers_missing_docker_sdk(self):
        """Verify graceful handling when docker SDK is not installed."""
        import sys

        docker_module = sys.modules.pop("docker", None)
        try:
            with patch.dict("sys.modules", {"docker": None}):
                stopped, errors = _stop_docker_containers("any-run")

            assert stopped == []
            assert errors == []
        finally:
            if docker_module is not None:
                sys.modules["docker"] = docker_module


class TestCleanTempFiles:
    """Tests for _clean_temp_files."""

    def test_clean_temp_files_removes_directory(self):
        """Verify temp directory is removed when it exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = "test-run-abc"
            temp_dir = Path(tmpdir) / "veritas" / run_id
            temp_dir.mkdir(parents=True)
            (temp_dir / "file1.txt").write_text("test")
            (temp_dir / "subdir").mkdir()
            (temp_dir / "subdir" / "file2.txt").write_text("test2")

            # Patch the base path to use our temp directory
            with patch("engine.tasks.process_cleanup.Path") as mock_path_class:
                mock_path = MagicMock()
                mock_path.__truediv__.return_value = temp_dir
                mock_path_class.return_value = mock_path

                cleaned, errors = _clean_temp_files(run_id)

            assert cleaned == [str(temp_dir)]
            assert errors == []
            assert not temp_dir.exists()

    def test_clean_temp_files_no_directory(self):
        """Verify empty result when temp directory doesn't exist."""
        run_id = "nonexistent-run"
        temp_dir = Path(f"/tmp/veritas/{run_id}")

        # Ensure it doesn't exist
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

        cleaned, errors = _clean_temp_files(run_id)

        assert cleaned == []
        assert errors == []

    def test_clean_temp_files_handles_persistent_directory(self):
        """Verify error is reported when directory still exists after rmtree."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_id = "test-run-persist"
            fake_veritas_root = Path(tmpdir)
            target_dir = fake_veritas_root / "veritas" / run_id
            target_dir.mkdir(parents=True)
            (target_dir / "somefile.txt").write_text("data")

            original_path = Path
            def fake_path_constructor(arg, *args, **kwargs):
                if arg == "/tmp/veritas":
                    return fake_veritas_root / "veritas"
                return original_path(arg, *args, **kwargs)

            # Mock shutil.rmtree to do nothing so the directory persists
            with patch("engine.tasks.process_cleanup.Path", side_effect=fake_path_constructor):
                with patch("engine.tasks.process_cleanup.shutil.rmtree"):
                    cleaned, errors = _clean_temp_files(run_id)

            assert cleaned == []
            assert len(errors) == 1
            assert "still exists after rmtree" in errors[0]


class TestClearGpuCache:
    """Tests for _clear_gpu_cache."""

    def test_clear_gpu_cache_calls_torch_cuda(self):
        """Verify torch.cuda.empty_cache() is called when CUDA is available."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.empty_cache = MagicMock()

        with patch.dict("sys.modules", {"torch": mock_torch}):
            success, errors = _clear_gpu_cache()

        assert success is True
        assert errors == []
        mock_torch.cuda.empty_cache.assert_called_once()

    def test_clear_gpu_cache_no_cuda(self):
        """Verify no-op when CUDA is not available."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {"torch": mock_torch}):
            success, errors = _clear_gpu_cache()

        assert success is False
        assert errors == []

    def test_clear_gpu_cache_handles_failure(self):
        """Verify graceful handling when CUDA cache clear fails."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.empty_cache.side_effect = RuntimeError("CUDA error")

        with patch.dict("sys.modules", {"torch": mock_torch}):
            success, errors = _clear_gpu_cache()

        assert success is False
        assert len(errors) == 1
        assert "Failed to clear CUDA cache" in errors[0]

    def test_clear_gpu_cache_missing_torch(self):
        """Verify graceful handling when torch is not installed."""
        import sys

        torch_module = sys.modules.pop("torch", None)
        try:
            with patch.dict("sys.modules", {"torch": None}):
                success, errors = _clear_gpu_cache()

            assert success is False
            assert errors == []
        finally:
            if torch_module is not None:
                sys.modules["torch"] = torch_module


class TestCleanupAuditProcesses:
    """Tests for the main cleanup_audit_processes entry point."""

    def test_cleanup_aggregates_all_results(self):
        """Verify all cleanup results are aggregated correctly."""
        with patch("engine.tasks.process_cleanup._kill_mineru_processes") as mock_kill:
            with patch("engine.tasks.process_cleanup._stop_docker_containers") as mock_docker:
                with patch("engine.tasks.process_cleanup._clean_temp_files") as mock_clean:
                    with patch("engine.tasks.process_cleanup._clear_gpu_cache") as mock_gpu:
                        mock_kill.return_value = ([123], [])
                        mock_docker.return_value = (["container-1"], [])
                        mock_clean.return_value = (["/tmp/veritas/run-1"], [])
                        mock_gpu.return_value = (True, [])

                        result = cleanup_audit_processes("run-1", "case-1")

        assert result["killed_processes"] == [123]
        assert result["stopped_containers"] == ["container-1"]
        assert result["cleaned_dirs"] == ["/tmp/veritas/run-1"]
        assert result["errors"] == []

    def test_cleanup_collects_errors_from_all_steps(self):
        """Verify errors from all cleanup steps are collected."""
        with patch("engine.tasks.process_cleanup._kill_mineru_processes") as mock_kill:
            with patch("engine.tasks.process_cleanup._stop_docker_containers") as mock_docker:
                with patch("engine.tasks.process_cleanup._clean_temp_files") as mock_clean:
                    with patch("engine.tasks.process_cleanup._clear_gpu_cache") as mock_gpu:
                        mock_kill.return_value = ([], ["kill error"])
                        mock_docker.return_value = ([], ["docker error"])
                        mock_clean.return_value = ([], ["clean error"])
                        mock_gpu.return_value = (False, ["gpu error"])

                        result = cleanup_audit_processes("run-2", "case-2")

        assert result["killed_processes"] == []
        assert result["stopped_containers"] == []
        assert result["cleaned_dirs"] == []
        assert len(result["errors"]) == 4
        assert "kill error" in result["errors"]
        assert "docker error" in result["errors"]
        assert "clean error" in result["errors"]
        assert "gpu error" in result["errors"]

    def test_cleanup_propagates_unexpected_exceptions(self):
        """Verify cleanup_audit_processes propagates truly unexpected exceptions.

        The individual helpers catch their own exceptions internally, but if
        a helper itself raises unexpectedly, the caller (audit_task) should
        catch it. The cleanup function does not wrap helper calls in try/except.
        """
        with patch("engine.tasks.process_cleanup._kill_mineru_processes") as mock_kill:
            mock_kill.side_effect = RuntimeError("Unexpected kill failure")

            with pytest.raises(RuntimeError, match="Unexpected kill failure"):
                cleanup_audit_processes("run-3", "case-3")

    def test_cleanup_with_mixed_success_and_errors(self):
        """Verify cleanup works correctly with partial failures."""
        with patch("engine.tasks.process_cleanup._kill_mineru_processes") as mock_kill:
            with patch("engine.tasks.process_cleanup._stop_docker_containers") as mock_docker:
                with patch("engine.tasks.process_cleanup._clean_temp_files") as mock_clean:
                    with patch("engine.tasks.process_cleanup._clear_gpu_cache") as mock_gpu:
                        mock_kill.return_value = ([123, 456], ["kill error for pid 789"])
                        mock_docker.return_value = (["container-1"], [])
                        mock_clean.return_value = ([], ["clean error"])
                        mock_gpu.return_value = (False, [])

                        result = cleanup_audit_processes("run-4", "case-4")

        assert result["killed_processes"] == [123, 456]
        assert result["stopped_containers"] == ["container-1"]
        assert result["cleaned_dirs"] == []
        assert len(result["errors"]) == 2
        assert "kill error for pid 789" in result["errors"]
        assert "clean error" in result["errors"]
