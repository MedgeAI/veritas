"""HTML escaping utilities for safe embedding of user-controlled data.
# All f-string interpolations MUST use h() or h_attr() for XSS protection.
"""

from __future__ import annotations

import html
from typing import Any


def h(text: Any) -> str:
    """HTML-escape text for safe embedding in HTML attributes and content.

    Converts *text* to ``str`` (``None`` becomes ``""``) and escapes
    ``& < > "`` so the result is safe inside element content **and**
    double-quoted attribute values.
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=True)


def h_attr(text: Any) -> str:
    """HTML-escape for attribute values (double-quoted).

    Functionally identical to :func:`h` — both call ``html.escape`` with
    ``quote=True``.  The separate name documents intent at call sites
    where the value is placed inside an HTML attribute.
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=True)
