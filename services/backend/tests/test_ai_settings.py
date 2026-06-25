from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import ConfigurationError, Settings

AI_ENV_NAMES = (
    "AI_PROVIDER_MODE",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_BASE_URL",
    "DASHSCOPE_HTTP_BASE_URL",
    "DASHSCOPE_WEBSOCKET_BASE_URL",
    "QWEN_DIALOG_MODEL",
    "QWEN_QUESTION_MODEL",
    "QWEN_REVIEW_MODEL",
    "QWEN_VERIFY_MODEL",
    "QWEN_FALLBACK_MODEL",
    "ALIYUN_ASR_MODEL",
    "ALIYUN_TTS_MODEL",
    "ALIYUN_TTS_VOICE",
    "ALIYUN_EMBEDDING_MODEL",
    "ALIYUN_EMBEDDING_DIMENSIONS",
)


def clear_ai_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AI_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def valid_aliyun_settings(**overrides: object) -> Settings:
    values = {
        "_env_file": None,
        "ai_provider_mode": "aliyun",
        "dashscope_api_key": SecretStr("sk-test-secret"),
        "dashscope_base_url": "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        "dashscope_http_base_url": "https://dashscope.aliyuncs.com/api/v1",
        "dashscope_websocket_base_url": "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
        "qwen_dialog_model": "qwen-dialog-test",
        "qwen_question_model": "qwen-question-test",
        "qwen_review_model": "qwen-review-test",
        "qwen_verify_model": "qwen-verify-test",
        "qwen_fallback_model": "qwen-fallback-test",
        "aliyun_asr_model": "fun-asr-test",
        "aliyun_tts_model": "cosyvoice-test",
        "aliyun_tts_voice": "voice-test",
        "aliyun_embedding_model": "embedding-test",
        "aliyun_embedding_dimensions": 16,
    }
    values.update(overrides)
    return Settings(**values)


def test_settings_config_loads_dotenv_files() -> None:
    env_file = Settings.model_config.get("env_file")

    assert isinstance(env_file, tuple)
    assert len(env_file) >= 2
    assert all(str(path).endswith(".env") for path in env_file)


def test_env_example_uses_tts_smoke_compatible_system_voice() -> None:
    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    values: dict[str, str] = {}
    for line in env_example.read_text(encoding="utf-8").splitlines():
        if line.startswith("ALIYUN_TTS_MODEL=") or line.startswith("ALIYUN_TTS_VOICE="):
            name, value = line.split("=", 1)
            values[name] = value

    assert values["ALIYUN_TTS_MODEL"] == "cosyvoice-v3-flash"
    assert values["ALIYUN_TTS_VOICE"] == "longanyang"


def test_default_mode_requires_aliyun_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_ai_env(monkeypatch)
    settings = Settings(_env_file=None, dashscope_api_key=None, dashscope_base_url="")

    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_ai()

    assert settings.ai_provider_mode_normalized == "aliyun"
    assert exc_info.value.code == "AI_CONFIG_MISSING"


def test_mock_mode_starts_without_dashscope_key() -> None:
    settings = Settings(
        _env_file=None,
        ai_provider_mode="mock",
        dashscope_api_key=None,
        dashscope_base_url="",
    )

    settings.validate_ai()

    summary = settings.safe_ai_summary()
    assert summary.mode == "mock"
    assert summary.dashscope_key_configured is False


def test_aliyun_mode_requires_key_and_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_ai_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        ai_provider_mode="aliyun",
        dashscope_api_key=None,
        dashscope_base_url="",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_ai()

    assert exc_info.value.code == "AI_CONFIG_MISSING"
    assert "DASHSCOPE_API_KEY" in str(exc_info.value)
    assert "DASHSCOPE_BASE_URL" in str(exc_info.value)


def test_aliyun_mode_requires_explicit_model_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_ai_env(monkeypatch)
    settings = Settings(
        _env_file=None,
        ai_provider_mode="aliyun",
        dashscope_api_key=SecretStr("sk-test-secret"),
        dashscope_base_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        dashscope_http_base_url="https://dashscope.aliyuncs.com/api/v1",
        dashscope_websocket_base_url="wss://dashscope.aliyuncs.com/api-ws/v1/inference",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_ai()

    assert exc_info.value.code == "AI_CONFIG_MISSING"
    assert "QWEN_DIALOG_MODEL" in str(exc_info.value)
    assert "ALIYUN_ASR_MODEL" in str(exc_info.value)
    assert "ALIYUN_EMBEDDING_DIMENSIONS" in str(exc_info.value)


def test_aliyun_mode_rejects_unresolved_workspace_placeholder() -> None:
    settings = valid_aliyun_settings(
        dashscope_base_url="https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )

    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_ai()

    assert exc_info.value.code == "AI_BASE_URL_NOT_RESOLVED"


def test_safe_ai_summary_does_not_expose_secret() -> None:
    settings = valid_aliyun_settings(
        dashscope_api_key=SecretStr("sk-real-secret"),
    )

    settings.validate_ai()
    summary_text = settings.safe_ai_summary().model_dump_json()

    assert "sk-real-secret" not in summary_text
    assert "dashscope_api_key" not in summary_text
    assert '"dashscope_key_configured":true' in summary_text


def test_auth_requires_jwt_secret() -> None:
    settings = Settings(_env_file=None, jwt_secret=None)

    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_auth()

    assert exc_info.value.code == "JWT_SECRET_MISSING"


def test_auth_accepts_configured_jwt_secret() -> None:
    settings = Settings(
        _env_file=None,
        jwt_secret=SecretStr("test-jwt-secret-that-is-long-enough"),
    )

    settings.validate_auth()


def test_push_requires_vapid_keypair() -> None:
    settings = Settings(
        _env_file=None,
        web_push_vapid_public_key="",
        web_push_vapid_private_key=None,
    )

    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_push()

    assert exc_info.value.code == "WEB_PUSH_PUBLIC_KEY_MISSING"


def test_push_accepts_configured_vapid_keypair() -> None:
    settings = Settings(
        _env_file=None,
        web_push_vapid_public_key="test-public-key",
        web_push_vapid_private_key=SecretStr("test-private-key"),
        strike_notification_ttl_minutes=5,
    )

    settings.validate_push()


def test_push_fake_ip_allowlist_normalizes_exact_hosts() -> None:
    settings = Settings(
        _env_file=None,
        web_push_vapid_public_key="test-public-key",
        web_push_vapid_private_key=SecretStr("test-private-key"),
        web_push_allow_fake_ip_hosts=" FCM.GoogleApis.com. , updates.push.services.mozilla.com ",
        strike_notification_ttl_minutes=5,
    )

    settings.validate_push()

    assert settings.web_push_fake_ip_host_allowlist == {
        "fcm.googleapis.com",
        "updates.push.services.mozilla.com",
    }


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "push.local",
        "https://fcm.googleapis.com",
        "fcm.googleapis.com:443",
    ],
)
def test_push_fake_ip_allowlist_rejects_non_exact_public_hosts(host: str) -> None:
    settings = Settings(
        _env_file=None,
        web_push_vapid_public_key="test-public-key",
        web_push_vapid_private_key=SecretStr("test-private-key"),
        web_push_allow_fake_ip_hosts=host,
        strike_notification_ttl_minutes=5,
    )

    with pytest.raises(ConfigurationError) as exc_info:
        settings.validate_push()

    assert exc_info.value.code == "WEB_PUSH_FAKE_IP_ALLOWLIST_INVALID"
