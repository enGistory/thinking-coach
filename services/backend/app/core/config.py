from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = (
    _BACKEND_ROOT.parent.parent if _BACKEND_ROOT.parent.name == "services" else _BACKEND_ROOT
)
_DOTENV_FILES = (str(_REPO_ROOT / ".env"), str(_BACKEND_ROOT / ".env"))


class ConfigurationError(RuntimeError):
    """Raised when environment-driven startup configuration is invalid."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


class AISettingsSummary(BaseModel):
    provider: str
    mode: str
    dashscope_key_configured: bool
    dashscope_base_url: str
    dashscope_http_base_url: str
    dashscope_websocket_base_url: str
    qwen_dialog_model: str
    qwen_question_model: str
    qwen_review_model: str
    qwen_verify_model: str
    qwen_fallback_model: str
    aliyun_asr_model: str
    aliyun_tts_model: str
    aliyun_tts_voice: str
    aliyun_embedding_model: str
    aliyun_embedding_dimensions: int
    search_provider: str
    bocha_key_configured: bool
    bocha_search_endpoint: str
    bocha_search_count: int
    bocha_freshness: str


class Settings(BaseSettings):
    """Environment-driven runtime settings.

    Local runs may use repository or backend .env files; deployments should
    inject the same names through the process environment.
    """

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=_DOTENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
    )

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
    web_push_allow_fake_ip_hosts: str = ""
    strike_notification_ttl_minutes: int = 5

    audio_root: Path = Path("/data/audio")
    audio_retention_days: int = 30
    max_audio_seconds: int = 180
    max_audio_mb: int = 20

    ai_provider: str = "aliyun"
    ai_provider_mode: str = "aliyun"
    dashscope_api_key: SecretStr | None = None
    dashscope_base_url: str = ""
    dashscope_http_base_url: str = ""
    dashscope_websocket_base_url: str = ""

    qwen_dialog_model: str = ""
    qwen_question_model: str = ""
    qwen_review_model: str = ""
    qwen_verify_model: str = ""
    qwen_fallback_model: str = ""
    aliyun_asr_model: str = ""
    aliyun_tts_model: str = ""
    aliyun_tts_voice: str = ""
    aliyun_embedding_model: str = ""
    aliyun_embedding_dimensions: int = 0

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

    search_provider: str = "bocha"
    bocha_api_key: SecretStr | None = None
    bocha_search_endpoint: str = "https://api.bochaai.com/v1/web-search"
    bocha_search_count: int = 8
    bocha_freshness: str = "oneYear"
    run_live_search_tests: bool = False

    @property
    def audio_root_resolved(self) -> Path:
        return self.audio_root.expanduser().resolve()

    @property
    def ai_provider_mode_normalized(self) -> str:
        return self.ai_provider_mode.strip().lower()

    @property
    def search_provider_normalized(self) -> str:
        return self.search_provider.strip().lower()

    @property
    def web_push_fake_ip_host_allowlist(self) -> set[str]:
        return {
            host.strip().lower().rstrip(".")
            for host in self.web_push_allow_fake_ip_hosts.split(",")
            if host.strip()
        }

    def validate_ai(self) -> None:
        """Validate AI startup configuration without exposing secret values."""

        if self.ai_provider.strip().lower() != "aliyun":
            raise ConfigurationError(
                "AI_PROVIDER_UNSUPPORTED",
                "P0 only supports AI_PROVIDER=aliyun",
            )

        mode = self.ai_provider_mode_normalized
        if mode not in {"aliyun", "mock"}:
            raise ConfigurationError(
                "AI_PROVIDER_MODE_INVALID",
                "AI_PROVIDER_MODE must be either aliyun or mock",
            )
        if mode == "mock":
            return

        missing = self._missing_aliyun_settings()
        if missing:
            raise ConfigurationError(
                "AI_CONFIG_MISSING",
                f"Missing required Aliyun AI settings: {', '.join(missing)}",
            )

        self._validate_endpoint("DASHSCOPE_BASE_URL", self.dashscope_base_url, require_wss=False)
        self._validate_endpoint(
            "DASHSCOPE_HTTP_BASE_URL",
            self.dashscope_http_base_url,
            require_wss=False,
        )
        self._validate_endpoint(
            "DASHSCOPE_WEBSOCKET_BASE_URL",
            self.dashscope_websocket_base_url,
            require_wss=True,
        )

    def safe_ai_summary(self) -> AISettingsSummary:
        return AISettingsSummary(
            provider=self.ai_provider,
            mode=self.ai_provider_mode_normalized,
            dashscope_key_configured=self._secret_has_value(self.dashscope_api_key),
            dashscope_base_url=self.dashscope_base_url,
            dashscope_http_base_url=self.dashscope_http_base_url,
            dashscope_websocket_base_url=self.dashscope_websocket_base_url,
            qwen_dialog_model=self.qwen_dialog_model,
            qwen_question_model=self.qwen_question_model,
            qwen_review_model=self.qwen_review_model,
            qwen_verify_model=self.qwen_verify_model,
            qwen_fallback_model=self.qwen_fallback_model,
            aliyun_asr_model=self.aliyun_asr_model,
            aliyun_tts_model=self.aliyun_tts_model,
            aliyun_tts_voice=self.aliyun_tts_voice,
            aliyun_embedding_model=self.aliyun_embedding_model,
            aliyun_embedding_dimensions=self.aliyun_embedding_dimensions,
            search_provider=self.search_provider_normalized,
            bocha_key_configured=self._secret_has_value(self.bocha_api_key),
            bocha_search_endpoint=self.bocha_search_endpoint,
            bocha_search_count=self.bocha_search_count,
            bocha_freshness=self.bocha_freshness,
        )

    def validate_search(self) -> None:
        provider = self.search_provider_normalized
        if provider not in {"bocha", "mock"}:
            raise ConfigurationError(
                "SEARCH_PROVIDER_UNSUPPORTED",
                "SEARCH_PROVIDER must be either bocha or mock",
            )
        if provider == "mock":
            return
        if not self._secret_has_value(self.bocha_api_key):
            raise ConfigurationError(
                "SEARCH_CONFIG_MISSING",
                "BOCHA_API_KEY must be configured when SEARCH_PROVIDER=bocha",
            )
        self._validate_endpoint(
            "BOCHA_SEARCH_ENDPOINT",
            self.bocha_search_endpoint,
            require_wss=False,
        )
        if self.bocha_search_count < 1 or self.bocha_search_count > 50:
            raise ConfigurationError(
                "SEARCH_COUNT_INVALID",
                "BOCHA_SEARCH_COUNT must be between 1 and 50",
            )

    def validate_push(self) -> None:
        if not self.web_push_vapid_public_key.strip():
            raise ConfigurationError(
                "WEB_PUSH_PUBLIC_KEY_MISSING",
                "WEB_PUSH_VAPID_PUBLIC_KEY must be configured",
            )
        if not self._secret_has_value(self.web_push_vapid_private_key):
            raise ConfigurationError(
                "WEB_PUSH_PRIVATE_KEY_MISSING",
                "WEB_PUSH_VAPID_PRIVATE_KEY must be configured",
            )
        if self.strike_notification_ttl_minutes < 1 or self.strike_notification_ttl_minutes > 60:
            raise ConfigurationError(
                "STRIKE_NOTIFICATION_TTL_INVALID",
                "STRIKE_NOTIFICATION_TTL_MINUTES must be between 1 and 60",
            )
        invalid_allowlist_hosts = [
            host
            for host in self.web_push_fake_ip_host_allowlist
            if "/" in host or ":" in host or host == "localhost" or host.endswith(".local")
        ]
        if invalid_allowlist_hosts:
            raise ConfigurationError(
                "WEB_PUSH_FAKE_IP_ALLOWLIST_INVALID",
                "WEB_PUSH_ALLOW_FAKE_IP_HOSTS must contain exact public hostnames",
            )

    def _missing_aliyun_settings(self) -> list[str]:
        required_strings = {
            "DASHSCOPE_BASE_URL": self.dashscope_base_url,
            "DASHSCOPE_HTTP_BASE_URL": self.dashscope_http_base_url,
            "DASHSCOPE_WEBSOCKET_BASE_URL": self.dashscope_websocket_base_url,
            "QWEN_DIALOG_MODEL": self.qwen_dialog_model,
            "QWEN_QUESTION_MODEL": self.qwen_question_model,
            "QWEN_REVIEW_MODEL": self.qwen_review_model,
            "QWEN_VERIFY_MODEL": self.qwen_verify_model,
            "QWEN_FALLBACK_MODEL": self.qwen_fallback_model,
            "ALIYUN_ASR_MODEL": self.aliyun_asr_model,
            "ALIYUN_TTS_MODEL": self.aliyun_tts_model,
            "ALIYUN_TTS_VOICE": self.aliyun_tts_voice,
            "ALIYUN_EMBEDDING_MODEL": self.aliyun_embedding_model,
        }
        missing = [
            name for name, value in required_strings.items() if not value or not value.strip()
        ]
        if not self._secret_has_value(self.dashscope_api_key):
            missing.append("DASHSCOPE_API_KEY")
        if self.aliyun_embedding_dimensions <= 0:
            missing.append("ALIYUN_EMBEDDING_DIMENSIONS")
        return missing

    @staticmethod
    def _secret_has_value(secret: SecretStr | None) -> bool:
        return bool(secret and secret.get_secret_value().strip())

    @staticmethod
    def _validate_endpoint(name: str, value: str, *, require_wss: bool) -> None:
        stripped = value.strip()
        allowed_prefixes = ("wss://",) if require_wss else ("https://",)
        if not stripped.startswith(allowed_prefixes):
            raise ConfigurationError(
                "AI_BASE_URL_INVALID",
                f"{name} must start with {allowed_prefixes[0]}",
            )
        if "<WorkspaceId>" in stripped or "{WorkspaceId}" in stripped:
            raise ConfigurationError(
                "AI_BASE_URL_NOT_RESOLVED",
                f"{name} still contains an unresolved WorkspaceId placeholder",
            )

    def validate_auth(self) -> None:
        """Validate authentication startup configuration without exposing secrets."""

        if not self._secret_has_value(self.jwt_secret):
            raise ConfigurationError(
                "JWT_SECRET_MISSING",
                "JWT_SECRET must be configured",
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
