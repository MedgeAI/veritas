#!/usr/bin/env python3
"""Smoke test: create a minimal paper directory and run --tier bare.

Usage::

    uv run python scripts/smoke_test_benchmark.py

This creates:
    /tmp/smoke_paper/
    ├── paper.pdf          (minimal valid PDF)
    └── source_data/
        └── table1.xlsx    (minimal xlsx with openpyxl)

Then runs:
    uv run python -m cli.main audit-paper /tmp/smoke_paper --tier bare

Purpose: verify stage filtering, role filtering, and output structure.
NOT for testing MinerU PDF parsing quality.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


def create_minimal_pdf(path: Path) -> None:
    """Create the smallest valid PDF file (one blank page)."""
    # Minimal PDF 1.4 structure
    pdf = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj

2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj

3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj

4 0 obj
<< /Length 44 >>
stream
BT /F1 12 Tf 100 700 Td (Smoke Test Paper) Tj ET
endstream
endobj

5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj

xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000360 00000 n

trailer
<< /Size 6 /Root 1 0 R >>
startxref
441
%%EOF
"""
    path.write_bytes(pdf)


def create_minimal_xlsx(path: Path) -> None:
    """Create a minimal xlsx file."""
    try:
        import openpyxl
    except ImportError:
        print("openpyxl not available, skipping xlsx creation", file=sys.stderr)
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Table 1"
    ws.append(["Sample", "Value", "Error"])
    ws.append(["A", 1.23, 0.05])
    ws.append(["B", 2.34, 0.08])
    ws.append(["C", 3.45, 0.12])
    wb.save(str(path))


def main() -> int:
    paper_dir = Path(tempfile.mkdtemp(prefix="smoke_paper_"))
    print(f"Creating smoke test paper in: {paper_dir}")

    # Create paper structure
    create_minimal_pdf(paper_dir / "paper.pdf")
    sd_dir = paper_dir / "source_data"
    sd_dir.mkdir()
    create_minimal_xlsx(sd_dir / "table1.xlsx")

    print(f"\nPaper directory contents:")
    for f in sorted(paper_dir.rglob("*")):
        if f.is_file():
            print(f"  {f.relative_to(paper_dir)} ({f.stat().st_size} bytes)")

    print(f"\n{'='*60}")
    print(f"Running: audit-paper --tier bare {paper_dir}")
    print(f"{'='*60}\n")

    result = subprocess.run(
        [
            sys.executable, "-m", "cli.main",
            "audit-paper",
            str(paper_dir),
            "--tier", "bare",
            "--output-root", "/tmp/smoke_benchmark_outputs",
            "--force",
            "--skip-unavailable-tools",
        ],
        cwd=Path(__file__).resolve().parents[1],
    )

    print(f"\n{'='*60}")
    print(f"Exit code: {result.returncode}")
    print(f"{'='*60}")

    # Show output structure
    output_root = Path("/tmp/smoke_benchmark_outputs")
    if output_root.exists():
        print(f"\nOutput directory:")
        for f in sorted(output_root.rglob("*")):
            if f.is_file():
                print(f"  {f.relative_to(output_root)}")

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
