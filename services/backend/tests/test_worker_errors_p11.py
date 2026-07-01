from __future__ import annotations

import pytest

from app.workers.main import _error_code


class ProviderFailure(RuntimeError):
    def __init__(self, *, code: str | None = None, error_code: str | None = None) -> None:
        if code is not None:
            self.code = code
        if error_code is not None:
            self.error_code = error_code
        super().__init__("provider failure")


def test_worker_error_code_preserves_safe_business_code() -> None:
    assert _error_code(ProviderFailure(code="DELETION_REQUEST_NOT_FOUND")) == (
        "DELETION_REQUEST_NOT_FOUND"
    )


@pytest.mark.parametrize(
    "unsafe_code",
    [
        "proof=one-time-proof-code",
        "token=refresh-token-value",
        "https://private.example.com/audio.wav?X-Amz-Signature=secret",
        "audio_path=/data/audio/private.wav",
        "DASHSCOPE_API_KEY=sk-secret",
    ],
)
def test_worker_error_code_rejects_sensitive_exception_code(unsafe_code: str) -> None:
    error_code = _error_code(ProviderFailure(code=unsafe_code))

    assert error_code == "PROVIDERFAILURE"
    assert unsafe_code not in error_code


def test_worker_error_code_rejects_sensitive_exception_error_code() -> None:
    unsafe_error_code = "signed_url=https://private.example.com/audio.wav?Signature=secret"

    error_code = _error_code(ProviderFailure(error_code=unsafe_error_code))

    assert error_code == "PROVIDERFAILURE"
    assert unsafe_error_code not in error_code
