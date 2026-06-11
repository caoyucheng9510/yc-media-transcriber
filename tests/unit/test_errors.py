from __future__ import annotations

from app.errors import AppError, normalize_error


def test_normalize_error_hides_unhandled_exception_detail() -> None:
    error = normalize_error(RuntimeError("secret low-level stack output"), "transcribing")

    assert error == {
        "code": "internal_error",
        "message": "任务处理失败，请查看服务日志。",
        "stage": "transcribing",
    }


def test_app_error_message_is_public_and_bounded() -> None:
    message = "download failed " + "x" * 200

    error = normalize_error(AppError("download_failed", message, "downloading"), "processing")

    assert error["code"] == "download_failed"
    assert error["stage"] == "downloading"
    assert len(error["message"]) <= 123
    assert error["message"].endswith("...")
