from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.metrics.resources import ResourceSampler, _read_cgroup_memory


class FakeQueue:
    def active_job_count(self) -> int:
        return 2

    def queue_size(self) -> int:
        return 3


def test_resource_sampler_samples_process_and_cgroup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.current").write_text(str(512 * 1024 * 1024), encoding="utf-8")
    (cgroup / "memory.max").write_text(str(2048 * 1024 * 1024), encoding="utf-8")

    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def children(self, recursive: bool = True) -> list:
            return []

        def cpu_percent(self, interval=None) -> float:
            return 12.5

        def memory_info(self):
            return SimpleNamespace(rss=256 * 1024 * 1024)

    fake_psutil = SimpleNamespace(
        Process=FakeProcess,
        NoSuchProcess=RuntimeError,
        AccessDenied=PermissionError,
        virtual_memory=lambda: SimpleNamespace(
            total=8192 * 1024 * 1024,
            available=4096 * 1024 * 1024,
        ),
        cpu_percent=lambda interval=None: 25.0,
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    sampler = ResourceSampler(
        Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json"),
        FakeQueue(),
        cgroup_root=cgroup,
    )
    sampler._sample_once()
    snapshot = sampler.current_snapshot()

    assert snapshot["available"] is True
    assert snapshot["runtime_mode"] == "docker"
    assert snapshot["active_job_count"] == 2
    assert snapshot["queue_depth"] == 3
    assert snapshot["process_rss_mb"] == 256
    assert snapshot["container_memory_current_mb"] == 512
    assert snapshot["container_memory_limit_mb"] == 2048
    assert snapshot["memory_headroom_mb"] == 1536


def test_resource_sampler_reports_unavailable_without_psutil(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "psutil", None)
    sampler = ResourceSampler(
        Settings(app_data_dir=tmp_path, terms_path=tmp_path / "terms.json"),
        FakeQueue(),
        cgroup_root=tmp_path / "missing",
    )

    sampler._sample_once()

    snapshot = sampler.current_snapshot()
    assert snapshot["available"] is False
    assert snapshot["reason"] == "psutil_not_installed"


def test_read_cgroup_v1_memory(tmp_path: Path) -> None:
    memory = tmp_path / "memory"
    memory.mkdir()
    (memory / "memory.usage_in_bytes").write_text("100", encoding="utf-8")
    (memory / "memory.limit_in_bytes").write_text("200", encoding="utf-8")

    assert _read_cgroup_memory(tmp_path) == (100, 200)
