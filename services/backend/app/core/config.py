from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven runtime settings.

    P00 intentionally does not read a real .env file. Docker Compose points at
    .env.example for local defaults, and real deployments should inject env vars.
    """

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    app_env: str = "dev"
    app_name: str = "thinking-coach"
    app_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:5173"
    tz: str = "America/New_York"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://thinking:thinking@127.0.0.1:5432/thinking"
    database_sync_url: str = "postgresql+psycopg://thinking:thinking@127.0.0.1:5432/thinking"

    jwt_secret: SecretStr | None = None
    jwt_access_minutes: int = 30
    jwt_refresh_days: int = 30
    langgraph_aes_key: SecretStr | None = None
    web_push_vapid_public_key: str = ""
    web_push_vapid_private_key: SecretStr | None = None

    audio_root: Path = Path("/data/audio")
    audio_retention_days: int = 30
    max_audio_seconds: int = 180
    max_audio_mb: int = 20

    ai_provider: str = "aliyun"
    ai_provider_mode: str = "aliyun"
    dashscope_api_key: SecretStr | None = None
    dashscope_base_url: str = ""

    qwen_dialog_model: str = ""
    qwen_question_model: str = ""
    qwen_review_model: str = ""
    qwen_verify_model: str = ""
    qwen_fallback_model: str = ""
    aliyun_asr_model: str = ""
    aliyun_tts_model: str = ""
    aliyun_embedding_model: str = ""

    llm_timeout_seconds: int = 120
    llm_max_retries: int = 3
    llm_temperature_dialog: float = 0.2
    llm_temperature_question: float = 0.7
    llm_temperature_review: float = 0.0
    qwen_enable_thinking_dialog: bool = False
    qwen_enable_thinking_question: bool = True
    qwen_enable_thinking_review: bool = True

    aliyun_oss_endpoint: str = ""
    aliyun_oss_bucket: str = ""
    aliyun_oss_access_key_id: str = ""
    aliyun_oss_access_key_secret: SecretStr | None = None
    aliyun_oss_signed_url_ttl_seconds: int = 900

    search_provider: str = "web_search"

    @property
    def audio_root_resolved(self) -> Path:
        return self.audio_root.expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
