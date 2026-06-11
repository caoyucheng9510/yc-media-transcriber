from __future__ import annotations

import queue
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from app.config import Settings
from app.errors import AppError, normalize_error
from app.jobs.processor import JobProcessor


class TaskQueue:
    def __init__(self, settings: Settings, processor: JobProcessor):
        self.settings = settings
        self.processor = processor
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._executor = ThreadPoolExecutor(max_workers=settings.task_queue_max_concurrency)
        self._stop = threading.Event()
        self._active_lock = threading.RLock()
        self._active_job_ids: set[str] = set()

    def start(self) -> None:
        if self.settings.app_process_jobs_inline:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="job-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=5)
        self._executor.shutdown(wait=True, cancel_futures=False)

    def enqueue(self, job_id: str) -> None:
        if self.settings.app_process_jobs_inline:
            self._run_job(job_id)
            return
        self._queue.put(job_id)

    def active_job_count(self) -> int:
        with self._active_lock:
            return len(self._active_job_ids)

    def queue_size(self) -> int:
        return self._queue.qsize()

    def _run(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if job_id is None:
                self._queue.task_done()
                break
            future = self._executor.submit(self._run_job, job_id)
            future.add_done_callback(lambda done, current_job_id=job_id: self._on_done(current_job_id, done))
            self._queue.task_done()

    def _run_job(self, job_id: str) -> None:
        self._mark_active(job_id)
        try:
            self.processor.process(job_id)
        finally:
            self._mark_inactive(job_id)

    def _mark_active(self, job_id: str) -> None:
        with self._active_lock:
            self._active_job_ids.add(job_id)

    def _mark_inactive(self, job_id: str) -> None:
        with self._active_lock:
            self._active_job_ids.discard(job_id)

    def _on_done(self, job_id: str, future: Future) -> None:
        try:
            future.result()
        except BaseException as exc:
            stage = exc.stage if isinstance(exc, AppError) else "processing"
            self.processor.store.update_job(
                job_id,
                status="failed",
                progress=100,
                error=normalize_error(exc, stage),
            )
