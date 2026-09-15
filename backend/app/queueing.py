"""Job queue abstraction.

Primary transport is Redis + RQ (set REDIS_URL); when Redis is not configured the
API falls back to an in-process thread pool so the app still runs on a single
machine with zero extra services.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from . import store
from .config import settings

log = logging.getLogger(__name__)

QUEUE_NAME = "separation"


class ThreadQueue:
    """Minimal in-process fallback used when Redis is not configured."""

    def __init__(self, max_workers: int) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sep")

    def enqueue(self, func: Callable[[str], None], job_id: str) -> None:
        self._pool.submit(func, job_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


_thread_queue: ThreadQueue | None = None
_thread_queue_lock = threading.Lock()


def _get_thread_queue() -> ThreadQueue:
    global _thread_queue
    with _thread_queue_lock:
        if _thread_queue is None:
            _thread_queue = ThreadQueue(settings.max_concurrent_jobs)
        return _thread_queue


def enqueue_job(job_id: str) -> None:
    """Push a separation job onto the configured queue."""
    from . import jobs as jobs_mod  # lazy import avoids a circular dependency

    if settings.redis_url:
        import redis as redis_lib
        from rq import Queue

        conn = redis_lib.from_url(settings.redis_url)
        Queue(QUEUE_NAME, connection=conn).enqueue(jobs_mod.run_job, job_id, job_timeout="4h")
        log.info("job %s enqueued on Redis queue '%s'", job_id, QUEUE_NAME)
    else:
        _get_thread_queue().enqueue(jobs_mod.run_job, job_id)
        log.info("job %s enqueued on in-process thread queue", job_id)


def recover_stale_jobs() -> int:
    """Thread-queue mode only: in-memory jobs are lost on restart; mark them failed."""
    n = 0
    for job in store.list_jobs():
        if job.get("status") in (store.STATUS_QUEUED, store.STATUS_PROCESSING):
            store.update_job(
                job["id"],
                status=store.STATUS_FAILED,
                error="Interrupted by a server restart. Please submit again.",
            )
            n += 1
    return n


def shutdown_thread_queue() -> None:
    global _thread_queue
    if _thread_queue is not None:
        _thread_queue.shutdown()
        _thread_queue = None


def queue_backend_name() -> str:
    return "redis" if settings.redis_url else "thread"
