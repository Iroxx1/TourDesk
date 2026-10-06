"""Crawler worker: claims jobs from the PostgreSQL queue and executes them.

Runs as its own process (``tourdesk-worker``) – completely decoupled from the web app.
Several worker threads run in parallel; per-domain politeness is enforced by the HTTP
client across threads and processes.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import threading
import time

from sqlalchemy.dialects.postgresql import insert as pg_insert

from tourdesk.core.db import get_session_factory
from tourdesk.core.logging import setup_logging
from tourdesk.core.timeutil import utcnow
from tourdesk.models import SystemHeartbeat
from tourdesk.services.app_settings import crawler_settings
from tourdesk.services.jobs import claim_next_job, heartbeat
from tourdesk_crawler.jobs.runner import execute_job

log = logging.getLogger("tourdesk.crawler")

POLL_SECONDS = 3.0
HEARTBEAT_SECONDS = 30.0


class Worker:
    def __init__(self, threads: int | None = None) -> None:
        self.sf = get_session_factory()
        with self.sf() as db:
            configured = int(crawler_settings(db).get("worker_threads", 3))
        self.thread_count = threads or configured
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.stop = threading.Event()
        self.running: dict[int, int] = {}  # thread index -> job id
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ heartbeats
    def _beat(self) -> None:
        with self._lock:
            running = list(self.running.values())
        with self.sf() as db:
            stmt = pg_insert(SystemHeartbeat).values(
                component=f"worker:{self.worker_id}", kind="worker", started_at=utcnow(), last_seen_at=utcnow(),
                info={"threads": self.thread_count, "running_jobs": running, "pid": os.getpid()},
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["component"], set_={"last_seen_at": utcnow(), "info": stmt.excluded.info}
            )
            db.execute(stmt)
            db.commit()
            for job_id in running:
                heartbeat(db, job_id)

    def _heartbeat_loop(self) -> None:
        while not self.stop.is_set():
            try:
                self._beat()
            except Exception:  # pragma: no cover - db outage
                log.warning("heartbeat failed", exc_info=True)
            self.stop.wait(HEARTBEAT_SECONDS)

    # ------------------------------------------------------------------ job loop
    def _loop(self, index: int) -> None:
        while not self.stop.is_set():
            try:
                with self.sf() as db:
                    job = claim_next_job(db, f"{self.worker_id}/{index}")
                    job_id = job.id if job else None
                    job_type = job.job_type if job else None
            except Exception:
                log.warning("could not claim job (database unavailable?)", exc_info=True)
                self.stop.wait(10)
                continue
            if job_id is None:
                self.stop.wait(POLL_SECONDS + index * 0.3)
                continue
            with self._lock:
                self.running[index] = job_id
            started = time.perf_counter()
            log.info("job %s (%s) gestartet", job_id, job_type, extra={"event": "crawler.job_start", "job_id": job_id, "job_type": job_type})
            status, _result = execute_job(job_id, self.sf)
            log.info(
                "job %s (%s) beendet: %s", job_id, job_type, status,
                extra={"event": "crawler.job_done", "job_id": job_id, "job_type": job_type, "status": status,
                       "duration_ms": int((time.perf_counter() - started) * 1000)},
            )
            with self._lock:
                self.running.pop(index, None)

    def run(self) -> int:
        log.info("Worker %s startet mit %d Threads", self.worker_id, self.thread_count, extra={"event": "worker.start"})
        threads = [threading.Thread(target=self._heartbeat_loop, name="heartbeat", daemon=True)]
        threads += [threading.Thread(target=self._loop, args=(i,), name=f"crawl-{i}", daemon=True) for i in range(self.thread_count)]
        for t in threads:
            t.start()
        try:
            while not self.stop.is_set():
                self.stop.wait(1)
        except KeyboardInterrupt:  # pragma: no cover
            self.stop.set()
        log.info("Worker wird beendet – laufende Jobs werden abgeschlossen …", extra={"event": "worker.stopping"})
        deadline = time.monotonic() + 90
        for t in threads[1:]:
            t.join(timeout=max(0.1, deadline - time.monotonic()))
        log.info("Worker beendet", extra={"event": "worker.stop"})
        return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging("worker")
    worker = Worker()

    def _shutdown(signum: int, _frame: object) -> None:
        worker.stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    return worker.run()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
