from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def run_script(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = "."
    return subprocess.run(
        args,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_source_data_profile_wrapper_outputs_stable_empty_summary(tmp_path) -> None:
    source_root = tmp_path / "Source Data"
    source_root.mkdir()
    output = tmp_path / "source_data_profile.json"

    result = run_script(
        ["python3", "scripts/source_data_profile.py", str(source_root), "--output", str(output)]
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["workbook_count"] == 0
    assert data["summary"]["sheet_count"] == 0


def test_source_data_findings_wrapper_outputs_stable_empty_summary(tmp_path) -> None:
    source_root = tmp_path / "Source Data"
    source_root.mkdir()
    profile = tmp_path / "source_data_profile.json"
    profile.write_text(
        json.dumps({"summary": {"workbook_count": 0, "sheet_count": 0}, "workbooks": []}),
        encoding="utf-8",
    )
    output = tmp_path / "source_data_findings.json"

    result = run_script(
        [
            "python3",
            "scripts/source_data_findings.py",
            str(source_root),
            "--profile",
            str(profile),
            "--output",
            str(output),
        ]
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["workbook_count"] == 0
    assert data["summary"]["priority_findings"] == 0


def test_source_data_pair_forensics_wrapper_outputs_stable_empty_summary(tmp_path) -> None:
    source_root = tmp_path / "Source Data"
    source_root.mkdir()
    output = tmp_path / "source_data_pair_forensics.json"

    result = run_script(
        ["python3", "scripts/source_data_pair_forensics.py", str(source_root), "--output", str(output)]
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["summary"]["workbook_count"] == 0
    assert data["summary"]["priority_findings"] == 0
