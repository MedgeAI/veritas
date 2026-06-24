"""Cleanup leftover processes, containers, temp files and GPU cache after audit runs.

All operations are best-effort: failures are logged and collected into the
returned error list but never raised. The caller (typically an async audit
task runner) must be able to continue even if every single cleanup step fails.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def cleanup_audit_processes(run_id: str, case_id: str) -> dict:
    """Kill orphaned processes and clean up resources for an audit run.

    Args:
        run_id: The audit run identifier (used for container labels and temp dirs).
        case_id: The case identifier (used to match MinerU process cmdline).

    Returns:
        dict with keys:
            killed_processes: list of PIDs killed
            stopped_containers: list of container IDs stopped
            cleaned_dirs: list of directory paths removed
            errors: list of error message strings
    """
    killed_processes, errors = _kill_mineru_processes(case_id)
    stopped_containers, docker_errors = _stop_docker_containers(run_id)
    errors.extend(docker_errors)

    cleaned_dirs, clean_errors = _clean_temp_files(run_id)
    errors.extend(clean_errors)

    _, gpu_errors = _clear_gpu_cache()
    errors.extend(gpu_errors)

    return {
        "killed_processes": killed_processes,
        "stopped_containers": stopped_containers,
        "cleaned_dirs": cleaned_dirs,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _kill_mineru_processes(case_id: str) -> tuple[list[int], list[str]]:
    """Terminate any MinerU subprocess whose command line references *case_id*.

    Returns (killed_pids, error_messages).
    """
    killed: list[int] = []
    errors: list[str] = []

    try:
        import psutil
    except ImportError:
        logger.debug("psutil not installed; skipping MinerU process cleanup")
        return killed, errors

    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            if not any(case_id in arg for arg in cmdline):
                continue
            # Only kill processes that look like MinerU
            proc_name = (proc.info.get("name") or "").lower()
            if "mineru" not in proc_name and not any(
                "mineru" in arg.lower() for arg in cmdline
            ):
                continue
            pid = proc.info["pid"]
            proc.kill()
            killed.append(pid)
            logger.info("Killed MinerU process pid=%s for case_id=%s", pid, case_id)
        except Exception as exc:
            msg = f"Failed to kill MinerU process (pid={proc.info.get('pid')}): {exc}"
            logger.warning(msg)
            errors.append(msg)

    return killed, errors


def _stop_docker_containers(run_id: str) -> tuple[list[str], list[str]]:
    """Stop Docker containers labelled with veritas_run_id=<run_id>.

    Returns (stopped_container_ids, error_messages).
    """
    stopped: list[str] = []
    errors: list[str] = []

    try:
        import docker
    except ImportError:
        logger.debug("docker SDK not installed; skipping container cleanup")
        return stopped, errors

    try:
        client = docker.from_env()
    except Exception as exc:
        msg = f"Failed to connect to Docker daemon: {exc}"
        logger.warning(msg)
        errors.append(msg)
        return stopped, errors

    try:
        containers = client.containers.list(
            filters={"label": f"veritas_run_id={run_id}"},
        )
    except Exception as exc:
        msg = f"Failed to list containers for run_id={run_id}: {exc}"
        logger.warning(msg)
        errors.append(msg)
        return stopped, errors

    for container in containers:
        try:
            cid = container.id or ""
            container.stop(timeout=10)
            if cid:
                stopped.append(cid)
            logger.info("Stopped container %s for run_id=%s", cid, run_id)
        except Exception as exc:
            msg = f"Failed to stop container {container.id}: {exc}"
            logger.warning(msg)
            errors.append(msg)

    return stopped, errors


def _clean_temp_files(run_id: str) -> tuple[list[str], list[str]]:
    """Remove temporary directory /tmp/veritas/<run_id>/.

    Returns (removed_dir_paths, error_messages).
    """
    cleaned: list[str] = []
    errors: list[str] = []

    tmp_dir = Path("/tmp/veritas") / run_id
    if not tmp_dir.is_dir():
        return cleaned, errors

    try:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        # ignore_errors=True suppresses exceptions, but if the dir still
        # exists after the call, something went wrong.
        if not tmp_dir.is_dir():
            cleaned.append(str(tmp_dir))
            logger.info("Removed temp dir %s", tmp_dir)
        else:
            msg = f"Temp dir {tmp_dir} still exists after rmtree"
            logger.warning(msg)
            errors.append(msg)
    except Exception as exc:
        msg = f"Failed to remove temp dir {tmp_dir}: {exc}"
        logger.warning(msg)
        errors.append(msg)

    return cleaned, errors


def _clear_gpu_cache() -> tuple[bool, list[str]]:
    """Call torch.cuda.empty_cache() to release unreferenced GPU memory.

    Returns (success, error_messages).
    """
    errors: list[str] = []

    try:
        import torch
    except ImportError:
        logger.debug("torch not installed; skipping GPU cache cleanup")
        return False, errors

    if not torch.cuda.is_available():
        return False, errors

    try:
        torch.cuda.empty_cache()
        logger.debug("Cleared CUDA cache")
        return True, errors
    except Exception as exc:
        msg = f"Failed to clear CUDA cache: {exc}"
        logger.warning(msg)
        errors.append(msg)
        return False, errors
