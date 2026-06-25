"""Comprehensive diagnostics for Veritas runtime readiness.

Called by both the /api/diag endpoint and scripts/diag.sh.
Returns structured results so the frontend can highlight exactly what's broken.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CheckResult:
    name: str
    ok: bool
    severity: str = "info"  # critical | warning | info
    detail: str = ""
    fix_hint: str = ""


@dataclass
class DiagReport:
    checks: list[CheckResult] = field(default_factory=list)

    def add(
        self,
        name: str,
        ok: bool,
        detail: str = "",
        *,
        severity: str = "info",
        fix_hint: str = "",
    ) -> None:
        self.checks.append(
            CheckResult(
                name=name,
                ok=ok,
                severity=severity,
                detail=detail,
                fix_hint=fix_hint,
            )
        )

    @property
    def all_ok(self) -> bool:
        return all(c.ok for c in self.checks if c.severity == "critical")

    @property
    def critical_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok and c.severity == "critical"]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.ok and c.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "all_ok": self.all_ok,
            "critical_count": len(self.critical_failures),
            "warning_count": len(self.warnings),
            "checks": [asdict(c) for c in self.checks],
        }


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_IN_CONTAINER = Path("/.dockerenv").exists()

# 容器内模型/数据在 /app，宿主机在 _REPO_ROOT
_APP_ROOT = Path("/app") if _IN_CONTAINER else _REPO_ROOT


def run_full_diagnostics() -> DiagReport:
    """Run all diagnostic checks and return a structured report."""
    report = DiagReport()
    _check_infrastructure(report)
    _check_opencode_wrapper(report)  # 紧跟基础设施，保持分组连贯
    _check_python_deps(report)
    _check_model_weights(report)
    _check_docker_images(report)
    _check_env_vars(report)
    _check_filesystem(report)
    return report


# ---------------------------------------------------------------------------
# Check categories
# ---------------------------------------------------------------------------


def _check_infrastructure(report: DiagReport) -> None:
    """PostgreSQL, Docker daemon, GPU."""
    # PostgreSQL
    db_url = os.environ.get("VERITAS_DATABASE_URL", "")
    if db_url:
        try:
            from sqlalchemy import create_engine, text

            engine = create_engine(db_url)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            report.add("postgres", True, "connected")
        except Exception as exc:
            report.add(
                "postgres",
                False,
                str(exc)[:200],
                severity="critical",
                fix_hint="检查 VERITAS_DATABASE_URL 和 PostgreSQL 容器（make db-up）",
            )
    else:
        report.add(
            "postgres",
            False,
            "VERITAS_DATABASE_URL 未设置",
            severity="critical",
            fix_hint="设置 VERITAS_DATABASE_URL，或运行 make db-up 启动 Docker PostgreSQL",
        )

    # Docker — 容器内无 Docker CLI，跳过
    if _IN_CONTAINER:
        report.add("docker", True, "running inside container (Docker CLI N/A)")
    else:
        docker_bin = shutil.which("docker")
        if not docker_bin:
            report.add(
                "docker",
                False,
                "docker not found on PATH",
                severity="critical",
                fix_hint="安装 Docker: https://docs.docker.com/engine/install/",
            )
        else:
            try:
                r = subprocess.run(
                    ["docker", "info", "--format", "{{.ServerVersion}}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if r.returncode == 0:
                    report.add("docker", True, f"v{r.stdout.strip()}")
                else:
                    report.add(
                        "docker",
                        False,
                        r.stderr.strip()[:200],
                        severity="critical",
                        fix_hint="Docker daemon 未运行，请启动 Docker",
                    )
            except Exception as exc:
                report.add("docker", False, str(exc)[:200], severity="critical")

    # opencode — 检查是否在 PATH 中
    oc_bin = shutil.which("opencode")
    if oc_bin:
        report.add("opencode", True, oc_bin)
    else:
        report.add(
            "opencode",
            False,
            "opencode not found",
            severity="critical",
            fix_hint="npm install -g opencode-ai",
        )

    # GPU
    try:
        import torch

        if torch.cuda.is_available():
            report.add("gpu", True, torch.cuda.get_device_name(0))
        else:
            report.add(
                "gpu",
                False,
                "CUDA not available",
                severity="warning",
                fix_hint="TruFor 需要 GPU；无 GPU 时 TruFor 会返回 failed",
            )
    except ImportError:
        report.add("gpu", False, "torch not installed", severity="warning")


def _check_python_deps(report: DiagReport) -> None:
    """Check Python packages required by tools."""
    deps = {
        "yacs": ("critical", "TruFor model code 需要 yacs.config"),
        "matplotlib": ("warning", "TruFor 可视化输出需要 matplotlib"),
        "torch": ("critical", "TruFor 推理需要 PyTorch"),
        "torchvision": ("critical", "TruFor 图像预处理需要 torchvision"),
        "PIL": ("critical", "图像处理需要 Pillow"),
        "numpy": ("critical", "数值计算需要 numpy"),
        "sqlalchemy": ("critical", "Web 后端数据层需要 SQLAlchemy"),
        "fastapi": ("critical", "Web 后端需要 FastAPI"),
    }
    for mod, (severity, hint) in deps.items():
        try:
            importlib.import_module(mod)
            report.add(f"pip:{mod}", True)
        except ImportError:
            report.add(
                f"pip:{mod}",
                False,
                f"missing: {mod}",
                severity=severity,
                fix_hint=f"uv add {mod} — {hint}",
            )


def _check_model_weights(report: DiagReport) -> None:
    """Check model weight files."""
    trufor_path = _APP_ROOT / "models" / "trufor" / "weights" / "trufor.pth.tar"

    if trufor_path.is_file():
        size_mb = trufor_path.stat().st_size / (1024 * 1024)
        report.add("model:trufor", True, f"{trufor_path.name} ({size_mb:.0f}MB)")
    else:
        report.add(
            "model:trufor",
            False,
            "weights not found",
            severity="critical",
            fix_hint="TruFor 伪造检测需要模型权重; make download-models 或手动下载",
        )


def _check_docker_images(report: DiagReport) -> None:
    """Check required Docker images. Skipped inside container (no Docker CLI)."""
    if _IN_CONTAINER:
        report.add("docker_images", True, "N/A (running inside container)")
        return
    images = [
        (
            "sila_dense",
            "veritas-sila-dense:latest",
            "warning",
            "docker build -t veritas-sila-dense:latest "
            "third_party/elis/system_modules/copy-move-detection/",
        ),
        ("pgvector", "pgvector/pgvector:pg16", "info", ""),
    ]
    for name, tag, severity, fix in images:
        try:
            r = subprocess.run(
                ["docker", "images", "-q", tag],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if r.stdout.strip():
                report.add(f"image:{name}", True, tag)
            else:
                report.add(
                    f"image:{name}",
                    False,
                    f"{tag} not found",
                    severity=severity,
                    fix_hint=fix,
                )
        except Exception:
            report.add(f"image:{name}", False, "docker unavailable", severity=severity)


def _check_env_vars(report: DiagReport) -> None:
    """Check API tokens and configuration."""
    vars_check = {
        "DASHSCOPE_API_KEY": ("warning", "Agent 模型调用需要 DashScope API key"),
        "MINERU_API_TOKEN": (
            "warning",
            "PDF 解析需要 MinerU token; 无 token 时 MinerU 步骤 skipped",
        ),
    }
    for var, (severity, hint) in vars_check.items():
        val = os.environ.get(var, "")
        if val:
            report.add(f"env:{var}", True, "set")
        else:
            report.add(f"env:{var}", False, "not set", severity=severity, fix_hint=hint)

    # OPENCODE_BIN
    oc = os.environ.get("OPENCODE_BIN", "")
    if oc:
        exists = Path(oc).exists() or shutil.which(oc)
        report.add(
            "env:OPENCODE_BIN",
            exists,
            oc if exists else f"not found: {oc}",
            severity="critical" if not exists else "info",
            fix_hint="确保 OPENCODE_BIN 指向可执行文件",
        )
    else:
        report.add("env:OPENCODE_BIN", True, "not set (will use PATH)")


def _check_filesystem(report: DiagReport) -> None:
    """Check writable directories."""
    dirs = [
        ("outputs", _APP_ROOT / "outputs"),
        ("web_data", _APP_ROOT / "web_data"),
    ]
    for name, path in dirs:
        if path.exists() and os.access(path, os.W_OK):
            report.add(f"fs:{name}", True, str(path))
        elif path.exists():
            report.add(f"fs:{name}", False, f"{path} not writable", severity="critical")
        else:
            try:
                path.mkdir(parents=True, exist_ok=True)
                report.add(f"fs:{name}", True, f"created {path}")
            except Exception as exc:
                report.add(f"fs:{name}", False, str(exc)[:200], severity="critical")


def _check_opencode_wrapper(report: DiagReport) -> None:
    """Verify the opencode Docker wrapper can actually execute.
    Skipped inside container (opencode is directly available, checked earlier)."""
    if _IN_CONTAINER:
        return
    wrapper = os.environ.get("OPENCODE_BIN", "")
    if not wrapper or not Path(wrapper).exists():
        # Not using wrapper; check if opencode is on PATH
        oc = shutil.which("opencode")
        if oc:
            report.add("opencode_exec", True, f"found on PATH: {oc}")
        else:
            report.add(
                "opencode_exec",
                False,
                "opencode not available",
                severity="critical",
                fix_hint="安装 opencode 或设置 OPENCODE_BIN 指向 wrapper 脚本",
            )
        return

    try:
        r = subprocess.run(
            [wrapper, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode == 0:
            version = r.stdout.strip() or r.stderr.strip()
            report.add("opencode_exec", True, f"v{version} via {Path(wrapper).name}")
        else:
            report.add(
                "opencode_exec",
                False,
                f"exit={r.returncode} stderr={r.stderr[:200]}",
                severity="critical",
                fix_hint="wrapper 脚本执行失败；检查 opencode 容器是否运行",
            )
    except subprocess.TimeoutExpired:
        report.add(
            "opencode_exec",
            False,
            "wrapper timed out (15s)",
            severity="critical",
            fix_hint="opencode 容器可能卡住；检查 docker logs veritas-opencode-dev",
        )
    except Exception as exc:
        report.add("opencode_exec", False, str(exc)[:200], severity="critical")
