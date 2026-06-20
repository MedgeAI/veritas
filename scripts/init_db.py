"""Initialise the Veritas PostgreSQL database.

Usage::

    make db-init
    # or directly:
    python -m scripts.init_db
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path for ``web.backend`` imports.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> int:
    from web.backend.veritas_web.database import (
        check_connection,
        create_db_engine,
        init_db,
    )

    engine = create_db_engine()
    if not check_connection(engine):
        print(
            "ERROR: cannot connect to PostgreSQL. Run `make db-up` first.",
            file=sys.stderr,
        )
        return 1

    init_db(engine)
    print("Database tables created successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
