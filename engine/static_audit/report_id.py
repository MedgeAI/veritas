"""Report ID generation and validation for public verification.

Format: VRT-YYYYMM-XXXXXX (6 hex chars)
Example: VRT-202606-A3F9B2
"""

from __future__ import annotations

import re
from datetime import UTC, datetime


def generate_report_id() -> str:
    """Generate a unique report ID with timestamp and random hex suffix.

    Returns
    -------
    str
        Report ID in format "VRT-YYYYMM-XXXXXX" where XXXXXX is 6 hex chars.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m")
    # Generate 6 random hex chars (24 bits of entropy)
    import secrets
    random_part = secrets.token_hex(3).upper()
    return f"VRT-{timestamp}-{random_part}"


def validate_report_id(report_id: str) -> bool:
    """Validate report ID format.

    Parameters
    ----------
    report_id : str
        The report ID to validate.

    Returns
    -------
    bool
        True if valid format, False otherwise.
    """
    pattern = r"^VRT-\d{6}-[0-9A-Fa-f]{6}$"
    return bool(re.match(pattern, report_id))
