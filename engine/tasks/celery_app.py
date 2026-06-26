"""Celery application for Veritas async audit tasks.

Broker and result backend both use PostgreSQL via the sqlalchemy transport
(no Redis required).  Configuration is driven by environment variables so
the same module works in Docker, local dev and CI.

Import this module as ``engine.tasks.celery_app`` to get the shared
``celery_app`` instance.  Celery workers are started with::

    celery -A engine.tasks.celery_app worker --loglevel=info
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from celery import Celery

# ---------------------------------------------------------------------------
# Load project .env into os.environ BEFORE reading any config variables.
#
# ``load_project_env`` returns a merged dict (shell env + .env file, shell
# wins) but does NOT mutate ``os.environ``.  We inject via ``setdefault``
# so that ``get_env()`` — and any downstream ``os.environ.get()`` — sees
# .env values.  Shell exports still take priority (setdefault won't
# overwrite).
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
from engine.env import get_env, load_project_env  # noqa: E402

for _k, _v in load_project_env(_PROJECT_ROOT).items():
    os.environ.setdefault(_k, _v)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Broker / backend URLs
# ---------------------------------------------------------------------------

BROKER_URL: str = get_env(
    "CELERY_BROKER_URL", required=False,
    default="sqlalchemy+postgresql://veritas_dev:veritas_dev_pass@localhost:5433/veritas_dev",
)
RESULT_BACKEND: str = get_env(
    "CELERY_RESULT_BACKEND", required=False,
    default="db+postgresql://veritas_dev:veritas_dev_pass@localhost:5433/veritas_dev",
)

# ---------------------------------------------------------------------------
# Concurrency and timeout knobs
# ---------------------------------------------------------------------------

_MAX_CONCURRENT = int(get_env("AUDIT_MAX_CONCURRENT_JOBS", required=False, default="2"))
_TASK_TIME_LIMIT = int(get_env("AUDIT_TASK_TIMEOUT_SECONDS", required=False, default="3600"))
_TASK_SOFT_TIME_LIMIT = max(_TASK_TIME_LIMIT - 100, 60)

# ---------------------------------------------------------------------------
# Celery app
# ---------------------------------------------------------------------------

celery_app = Celery(
    "veritas",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["engine.tasks.audit_task"],
)

celery_app.conf.update(
    # Serialisation — JSON only; never pickle untrusted payloads.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Timezone.
    timezone="UTC",
    enable_utc=True,

    # Worker concurrency (prefork pool).
    worker_concurrency=_MAX_CONCURRENT,

    # Hard and soft time limits per task.
    task_time_limit=_TASK_TIME_LIMIT,
    task_soft_time_limit=_TASK_SOFT_TIME_LIMIT,

    # Result expiry — 24 h is plenty for audit result retrieval.
    result_expires=86400,

    # Task result backend — use the db+ scheme for PostgreSQL.
    result_backend=RESULT_BACKEND,

    # Do not send events by default (reduces broker load).
    worker_send_task_events=False,
    task_send_events=False,

    # Late ack: message is acknowledged only after the task returns, so a
    # worker crash mid-task causes redelivery.
    task_acks_late=True,

    # Reject-on-worker-lost: if a worker is killed (SIGKILL), the broker
    # re-queues the message instead of losing it.
    task_reject_on_worker_lost=True,
)

logger.info(
    "Celery app configured: broker=%s concurrency=%d time_limit=%d",
    BROKER_URL,
    _MAX_CONCURRENT,
    _TASK_TIME_LIMIT,
)
