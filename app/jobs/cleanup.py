from __future__ import annotations

import shutil
import time
from pathlib import Path


def cleanup_old_temp_dirs(temp_dir: Path, retention_hours: int) -> int:
    if not temp_dir.exists():
        return 0
    cutoff = time.time() - max(1, retention_hours) * 3600
    removed = 0
    for child in temp_dir.iterdir():
        if not child.is_dir():
            continue
        try:
            if child.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        except OSError:
            continue
    return removed
