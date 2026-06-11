from __future__ import annotations

import threading
import time
from pathlib import Path

from app.config import Settings
from app.jobs.queue import TaskQueue


class FakeProcessor:
    def __init__(self) -> None:
        self.started: list[float] = []
        self.lock = threading.Lock()
        self.two_started = threading.Event()

    def process(self, job_id: str) -> None:
        with self.lock:
            self.started.append(time.monotonic())
            if len(self.started) == 2:
                self.two_started.set()
        time.sleep(0.2)


def test_task_queue_respects_max_workers(tmp_path: Path) -> None:
    settings = Settings(
        app_data_dir=tmp_path,
        terms_path=tmp_path / "terms.json",
        task_queue_max_concurrency=2,
        app_process_jobs_inline=False,
    )
    processor = FakeProcessor()
    task_queue = TaskQueue(settings, processor)  # type: ignore[arg-type]
    task_queue.start()
    try:
        task_queue.enqueue("job_1")
        task_queue.enqueue("job_2")
        assert processor.two_started.wait(timeout=1.0)
    finally:
        task_queue.stop()

    assert len(processor.started) == 2
    assert max(processor.started) - min(processor.started) < 0.15
