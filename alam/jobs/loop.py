"""Always-on worker loop.

For local development and for any host that can run a process. Production
under ADR-0007 uses the HTTP trigger instead — this module and that endpoint
call exactly the same ``drain``, which is what keeps the hosting decision
reversible.

    python -m alam.jobs.loop
"""

from __future__ import annotations

import signal
import sys
import time
from typing import TYPE_CHECKING

from alam.config.logging import configure_logging, get_logger
from alam.config.settings import get_settings
from alam.jobs.handlers import registered_types
from alam.jobs.runner import drain
from alam.persistence.session import get_session_factory

if TYPE_CHECKING:
    from types import FrameType

log = get_logger(__name__)

_shutdown = False


def _request_shutdown(signum: int, frame: FrameType | None) -> None:
    """Finish the drain in flight, then stop.

    Killing a worker mid-job is safe — the lease expires and another worker
    picks it up — but finishing cleanly avoids waiting out that lease for no
    reason.
    """
    global _shutdown
    _shutdown = True
    log.info("worker.shutdown_requested", signal=signum)


def run_forever() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    log.info(
        "worker.started",
        poll_interval=settings.worker_poll_interval_seconds,
        handlers=registered_types(),
    )

    session_factory = get_session_factory()

    while not _shutdown:
        try:
            result = drain(
                session_factory,
                max_jobs=settings.drain_max_jobs,
                budget_seconds=settings.drain_budget_seconds,
                lease_seconds=settings.job_lease_seconds,
            )
            if not result.idle:
                log.info(
                    "worker.drained",
                    claimed=result.claimed,
                    succeeded=result.succeeded,
                    failed=result.failed,
                    budget_exhausted=result.budget_exhausted,
                )
        except Exception:
            # A drain that blows up must not kill the worker — the next tick
            # may well succeed, and a crashed worker processes nothing at all.
            log.exception("worker.drain_error")

        time.sleep(settings.worker_poll_interval_seconds)

    log.info("worker.stopped")


if __name__ == "__main__":
    run_forever()
    sys.exit(0)
