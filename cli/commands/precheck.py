from __future__ import annotations

from pathlib import Path

from engine.workflows.precheck import run_precheck


def handle(manifest: str, output_dir: str | None = None) -> int:
    result = run_precheck(manifest)
    print(f"Project: {result['project_name']}")
    print(f"Verification Level Preview: {result['verification_level_preview']}")
    print(f"Environment Ready: {result['environment_ready']}")
    print(f"Entrypoint Ready: {result['entrypoint_ready']}")
    print(f"Results Ready: {result['results_ready']}")
    print(f"Checks: {result['checks_passed']} passed / {result['checks_total']} total")

    if output_dir:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "precheck.json").write_text(result["json"], encoding="utf-8")
        print(f"Precheck JSON: {out / 'precheck.json'}")
    return 0
