from __future__ import annotations

import json

from pydantic import SecretStr

from app.core.config import Settings
from app.scripts import smoke_ai


def test_smoke_ai_mock_output_is_redacted(monkeypatch, capsys) -> None:
    secret = "sk-do-not-print"

    def mock_settings() -> Settings:
        return Settings(
            _env_file=None,
            ai_provider_mode="mock",
            dashscope_api_key=SecretStr(secret),
        )

    monkeypatch.setattr(smoke_ai, "get_settings", mock_settings)

    assert smoke_ai.main(["--task", "llm"]) == 0

    output = capsys.readouterr().out
    body = json.loads(output)
    assert body["task"] == "llm"
    assert body["ok"] is True
    assert secret not in output


def test_smoke_ai_mock_asr_does_not_require_real_audio(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        smoke_ai,
        "get_settings",
        lambda: Settings(_env_file=None, ai_provider_mode="mock"),
    )

    assert smoke_ai.main(["--task", "asr"]) == 0

    body = json.loads(capsys.readouterr().out)
    assert body["task"] == "asr"
    assert body["segment_count"] == 1
