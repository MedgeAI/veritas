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

from celery import Celery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Broker / backend URLs
# ---------------------------------------------------------------------------

_DEFAULT_BROKER = (
    "sqlalchemy+postgresql://veritas_dev:veritas_dev_pass@localhost:5433/veritas_dev"
)
_DEFAULT_BACKEND = (
    "db+postgresql://veritas_dev:veritas_dev_pass@localhost:5433/veritas_dev"
)

BROKER_URL: str = os.environ.get("CELERY_BROKER_URL", _DEFAULT_BROKER)
RESULT_BACKEND: str = os.environ.get("CELERY_RESULT_BACKEND", _DEFAULT_BACKEND)

# ---------------------------------------------------------------------------
# Concurrency and timeout knobs
# ---------------------------------------------------------------------------

_MAX_CONCURRENT = int(os.environ.get("AUDIT_MAX_CONCURRENT_JOBS", "2"))
_TASK_TIME_LIMIT = int(os.environ.get("AUDIT_TASK_TIMEOUT_SECONDS", "3600"))
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
