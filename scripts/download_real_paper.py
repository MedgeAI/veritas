"""Download a real paper's Springer supplementary xlsx into the SHARED store, keyed by DOI.

Populates `case_data_dir(doi)` (= engine.env.real_papers_root() / <sanitized-doi> / source_data)
so any window pointed at the same root (VERITAS_REAL_PAPERS_ROOT) shares one copy. A server
window with the /srv mount runs this to fill the canonical location; a local window overrides the
root to a reachable path.

Usage (from repo root):
    PYTHONPATH=. python3 scripts/download_real_paper.py 10.1038/s41588-025-02253-8
    PYTHONPATH=. python3 scripts/download_real_paper.py <doi> --max-moesm 30

Downloads every MOESM index in range that exists as .xlsx; verifies each is a valid zip.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from engine.benchmark.real_paper import case_data_dir, springer_moesm_url


def _fetch(url: str, timeout: float = 60.0) -> bytes | None:
    try:
        with urlopen(url, timeout=timeout) as resp:  # noqa: S310 (trusted publisher host)
            if resp.status != 200:
                return None
            return resp.read()
    except (HTTPError, URLError, TimeoutError):
        return None


def download(doi: str, *, max_moesm: int = 25) -> dict:
    dest = case_data_dir(doi)
    dest.mkdir(parents=True, exist_ok=True)
    prefix = springer_moesm_url(doi, 1).rsplit("_MOESM", 1)[0].rsplit("/", 1)[1]
    got, bad = [], []
    for k in range(1, max_moesm + 1):
        url = springer_moesm_url(doi, k)
        data = _fetch(url)
        if data is None:
            continue
        out = dest / f"{prefix}_MOESM{k}_ESM.xlsx"
        out.write_bytes(data)
        if zipfile.is_zipfile(out):
            got.append(out.name)
        else:
            out.unlink(missing_ok=True)
            bad.append(f"MOESM{k}(not-xlsx)")
    return {"doi": doi, "dest": str(dest), "downloaded": got, "skipped_or_bad": bad}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doi", help="e.g. 10.1038/s41588-025-02253-8")
    ap.add_argument("--max-moesm", type=int, default=25)
    args = ap.parse_args()
    result = download(args.doi, max_moesm=args.max_moesm)
    print(f"dest={result['dest']}")
    print(f"downloaded {len(result['downloaded'])} xlsx: {result['downloaded']}")
    if result["skipped_or_bad"]:
        print(f"skipped/bad: {result['skipped_or_bad']}", file=sys.stderr)
    return 0 if result["downloaded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
