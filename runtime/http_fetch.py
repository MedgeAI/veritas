"""Runtime-level HTTP fetch utility.

This is the ONLY module in the Veritas codebase permitted to perform HTTP I/O
directly.  All engine-level code that needs to download files or fetch web
pages MUST go through this module, never ``urllib``, ``requests`` or ``httpx``
directly.

Uses only the Python stdlib (``urllib.request``) so that no additional
dependency is introduced at the runtime layer.
"""
from __future__ import annotations

import hashlib
import logging
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30
_DEFAULT_USER_AGENT = "Veritas-SourceAcquisition/1.0"


@dataclass(frozen=True)
class FetchResult:
    """Outcome of a single HTTP request.

    Exactly one of ``dest_path`` or ``error`` is set.
    """

    url: str
    status_code: int | None
    content_type: str | None
    sha256: str | None = None
    size_bytes: int | None = None
    dest_path: Path | None = None
    error: str | None = None
    # For text responses (fetch_text), the decoded body.
    text_body: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and 200 <= self.status_code < 300


def fetch_bytes(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    user_agent: str = _DEFAULT_USER_AGENT,
) -> FetchResult:
    """Download *url* into memory and return raw bytes with metadata.

    Does NOT write to disk.  Use :func:`fetch_to_file` for large downloads.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            body = resp.read()
    except urllib.error.HTTPError as exc:
        return FetchResult(
            url=url,
            status_code=exc.code,
            content_type=None,
            error=f"HTTP {exc.code}: {exc.reason}",
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return FetchResult(
            url=url, status_code=None, content_type=None, error=str(exc)
        )

    digest = hashlib.sha256(body).hexdigest()
    return FetchResult(
        url=url,
        status_code=status,
        content_type=content_type,
        sha256=digest,
        size_bytes=len(body),
        text_body=None,
    )


def fetch_text(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    user_agent: str = _DEFAULT_USER_AGENT,
    encoding: str = "utf-8",
) -> FetchResult:
    """Download *url* and return the decoded text body."""
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        return FetchResult(
            url=url,
            status_code=exc.code,
            content_type=None,
            error=f"HTTP {exc.code}: {exc.reason}",
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return FetchResult(
            url=url, status_code=None, content_type=None, error=str(exc)
        )

    text = raw.decode(encoding, errors="replace")
    digest = hashlib.sha256(raw).hexdigest()
    return FetchResult(
        url=url,
        status_code=status,
        content_type=content_type,
        sha256=digest,
        size_bytes=len(raw),
        text_body=text,
    )


def fetch_to_file(
    url: str,
    dest: Path,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    user_agent: str = _DEFAULT_USER_AGENT,
    max_size_bytes: int = 500 * 1024 * 1024,  # 500 MB safety limit
) -> FetchResult:
    """Download *url* to *dest* on disk with sha256 verification.

    Writes to a temporary file first, then atomically moves to *dest* on
    success.  On any failure the temp file is cleaned up and *dest* is not
    created / left untouched.
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            content_type = resp.headers.get("Content-Type", "")
            hasher = hashlib.sha256()
            total = 0
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path_str = tempfile.mkstemp(
                dir=str(dest.parent), suffix=".partial"
            )
            tmp_path = Path(tmp_path_str)
            try:
                with open(tmp_fd, "wb") as fout:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_size_bytes:
                            return FetchResult(
                                url=url,
                                status_code=status,
                                content_type=content_type,
                                error=f"response exceeds max_size_bytes ({max_size_bytes})",
                            )
                        hasher.update(chunk)
                        fout.write(chunk)
            except BaseException:
                tmp_path.unlink(missing_ok=True)
                raise

            final_dest = dest
            tmp_path.rename(final_dest)
            return FetchResult(
                url=url,
                status_code=status,
                content_type=content_type,
                sha256=hasher.hexdigest(),
                size_bytes=total,
                dest_path=final_dest,
            )
    except urllib.error.HTTPError as exc:
        return FetchResult(
            url=url,
            status_code=exc.code,
            content_type=None,
            error=f"HTTP {exc.code}: {exc.reason}",
        )
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return FetchResult(url=url, status_code=None, content_type=None, error=str(exc))


def fetch_json(
    url: str,
    *,
    timeout: int = _DEFAULT_TIMEOUT,
    user_agent: str = _DEFAULT_USER_AGENT,
) -> FetchResult:
    """Download *url* expecting a JSON body.  Returns ``text_body`` for parsing."""
    return fetch_text(url, timeout=timeout, user_agent=user_agent)
