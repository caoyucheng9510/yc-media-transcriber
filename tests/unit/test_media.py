from __future__ import annotations

from pathlib import Path

from app.media import normalize_audio, probe_media


def test_probe_and_normalize_audio(sample_wav: Path, tmp_path: Path) -> None:
    info = probe_media(sample_wav)
    assert info.has_audio is True
    assert info.duration > 0

    output = tmp_path / "out.wav"
    normalized_info = normalize_audio(sample_wav, output)
    assert normalized_info.has_audio is True
    assert output.exists()
    assert output.stat().st_size > 0
