from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from app.config import Settings
from app.storage.sqlite import utc_now


class ResourceSampler:
    def __init__(self, settings: Settings, queue: Any, cgroup_root: Path = Path("/sys/fs/cgroup")):
        self.settings = settings
        self.queue = queue
        self.cgroup_root = cgroup_root
        self._interval = max(1.0, float(settings.metrics_sample_interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._snapshot: dict[str, Any] = {
            "available": False,
            "reason": "not_sampled",
        }

    def start(self) -> None:
        if not self.settings.metrics_enabled:
            self._set_unavailable("metrics_disabled")
            return
        if not self.settings.metrics_resource_snapshot_enabled:
            self._set_unavailable("resource_snapshot_disabled")
            return
        if self._thread and self._thread.is_alive():
            return
        self._sample_once()
        self._thread = threading.Thread(target=self._run, name="resource-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def current_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._snapshot)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._sample_once()

    def _sample_once(self) -> None:
        try:
            import psutil
        except ImportError:
            self._set_unavailable("psutil_not_installed")
            return

        try:
            process = psutil.Process(os.getpid())
            children = process.children(recursive=True)
            process_cpu = _safe_float(process.cpu_percent(interval=None))
            rss_bytes = _safe_int(process.memory_info().rss)
            child_count = 0
            for child in children:
                try:
                    process_cpu += _safe_float(child.cpu_percent(interval=None))
                    rss_bytes += _safe_int(child.memory_info().rss)
                    child_count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            virtual_memory = psutil.virtual_memory()
            cgroup_current, cgroup_limit = _read_cgroup_memory(self.cgroup_root)
            system_available = _safe_int(getattr(virtual_memory, "available", 0))
            system_total = _safe_int(getattr(virtual_memory, "total", 0))
            memory_headroom = None
            if cgroup_limit and cgroup_limit > 0:
                memory_headroom = max(0, cgroup_limit - (cgroup_current or 0))
            elif system_available > 0:
                memory_headroom = system_available

            snapshot = {
                "available": True,
                "sampled_at": utc_now(),
                "runtime_mode": _runtime_mode(self.cgroup_root),
                "active_job_count": _queue_count(self.queue, "active_job_count"),
                "queue_depth": _queue_count(self.queue, "queue_size"),
                "process_cpu_percent": process_cpu,
                "process_rss_mb": _mb(rss_bytes),
                "process_children_count": child_count,
                "system_cpu_percent": _safe_float(psutil.cpu_percent(interval=None)),
                "system_memory_used_mb": _mb(system_total - system_available) if system_total else None,
                "system_memory_total_mb": _mb(system_total) if system_total else None,
                "container_memory_current_mb": _mb(cgroup_current) if cgroup_current is not None else None,
                "container_memory_limit_mb": _mb(cgroup_limit) if cgroup_limit is not None else None,
                "memory_headroom_mb": _mb(memory_headroom) if memory_headroom is not None else None,
            }
            with self._lock:
                self._snapshot = snapshot
        except Exception as exc:
            self._set_unavailable(exc.__class__.__name__)

    def _set_unavailable(self, reason: str) -> None:
        with self._lock:
            self._snapshot = {
                "available": False,
                "reason": reason,
                "sampled_at": utc_now(),
                "runtime_mode": _runtime_mode(self.cgroup_root),
                "active_job_count": _queue_count(self.queue, "active_job_count"),
                "queue_depth": _queue_count(self.queue, "queue_size"),
            }


def _read_cgroup_memory(root: Path) -> tuple[int | None, int | None]:
    current = _read_int(root / "memory.current")
    limit = _read_limit(root / "memory.max")
    if current is not None:
        return current, limit
    current = _read_int(root / "memory" / "memory.usage_in_bytes")
    limit = _read_limit(root / "memory" / "memory.limit_in_bytes")
    return current, limit


def _read_int(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _read_limit(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if raw.lower() == "max":
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0 or value >= 2**60:
        return None
    return value


def _runtime_mode(cgroup_root: Path) -> str:
    if Path("/.dockerenv").exists() or (cgroup_root / "memory.current").exists():
        return "docker"
    return "local"


def _queue_count(queue: Any, method_name: str) -> int:
    method = getattr(queue, method_name, None)
    if not callable(method):
        return 0
    try:
        return int(method())
    except Exception:
        return 0


def _mb(value: int | float | None) -> float | None:
    if value is None:
        return None
    return float(value) / 1024 / 1024


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
