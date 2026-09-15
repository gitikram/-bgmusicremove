"""RQ worker entry point: `python -m app.worker` (requires REDIS_URL to be set).

The job function lives in app.jobs.run_job; RQ serializes it by import path so
the worker process imports the same code the API enqueued.
"""

from __future__ import annotations

import logging

from .config import settings
from .queueing import QUEUE_NAME

log = logging.getLogger(__name__)


def main() -> None:
    if not settings.redis_url:
        raise SystemExit(
            "REDIS_URL is not set. The in-process thread queue needs no worker process; "
            "set REDIS_URL (e.g. redis://localhost:6379/0) to run a dedicated worker."
        )
    from redis import Redis
    from rq import Worker

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    worker = Worker([QUEUE_NAME], connection=Redis.from_url(settings.redis_url), name="clearvoice-worker")
    log.info("Worker started on queue '%s' (%s)", QUEUE_NAME, settings.redis_url)
    worker.work()


if __name__ == "__main__":
    main()
