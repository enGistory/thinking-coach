from __future__ import annotations

import argparse
import ipaddress
import sys
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import ConfigurationError, Settings

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_FILE = REPO_ROOT / "infra" / "env.production"

REQUIRED_RAW_ENV = {
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "APP_ENV",
    "APP_BASE_URL",
    "WEB_BASE_URL",
    "JWT_SECRET",
    "LANGGRAPH_AES_KEY",
    "AI_PROVIDER",
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
    "SEARCH_PROVIDER",
    "BOCHA_API_KEY",
    "BOCHA_SEARCH_ENDPOINT",
    "WEB_PUSH_VAPID_PUBLIC_KEY",
    "WEB_PUSH_VAPID_PRIVATE_KEY",
}

PLACEHOLDER_MARKERS = (
    "change-me",
    "changeme",
    "replace-with",
    "placeholder",
    "example.com",
    "<workspaceid>",
    "{workspaceid}",
)

RELEASE_HTTPS_URL_ENV = (
    "APP_BASE_URL",
    "WEB_BASE_URL",
)

RELEASE_SECRET_MIN_LENGTHS = {
    "POSTGRES_PASSWORD": 16,
    "JWT_SECRET": 32,
    "LANGGRAPH_AES_KEY": 32,
    "WEB_PUSH_VAPID_PRIVATE_KEY": 32,
}
UTF8_BOM = b"\xef\xbb\xbf"


def validate_release_env(env_file: Path) -> list[str]:
    if not env_file.exists():
        return [f"{env_file} does not exist"]
    if not env_file.is_file():
        return [f"{env_file} is not a file"]

    values, parse_errors = _parse_env_file(env_file)
    if parse_errors:
        return parse_errors

    errors = _validate_raw_values(values)
    errors.extend(_validate_release_values(values))

    settings = _settings_from_raw_values(values)
    for validator_name, validator in (
        ("auth", settings.validate_auth),
        ("ai", settings.validate_ai),
        ("search", settings.validate_search),
        ("push", settings.validate_push),
    ):
        try:
            validator()
        except ConfigurationError as exc:
            errors.append(f"{validator_name}: {exc.code}")

    if settings.app_env.strip().lower() != "production":
        errors.append("APP_ENV must be production for release env validation")
    if settings.ai_provider_mode_normalized != "aliyun":
        errors.append("AI_PROVIDER_MODE must be aliyun for release env validation")
    if settings.search_provider_normalized != "bocha":
        errors.append("SEARCH_PROVIDER must be bocha for release env validation")

    return sorted(set(errors))


def _parse_env_file(env_file: Path) -> tuple[dict[str, str], list[str]]:
    raw_content = env_file.read_bytes()
    if raw_content.startswith(UTF8_BOM):
        return {}, [f"{env_file} must be UTF-8 without BOM"]

    try:
        text = raw_content.decode("utf-8")
    except UnicodeDecodeError:
        return {}, [f"{env_file} must be valid UTF-8"]

    values: dict[str, str] = {}
    seen_names: set[str] = set()
    duplicate_names: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            return {}, [f"{env_file} contains malformed env line: {line_number}"]
        name, value = line.split("=", 1)
        env_name = name.strip()
        if not _is_valid_env_name(env_name):
            return {}, [f"{env_file} contains invalid variable name on line {line_number}"]
        if env_name in seen_names:
            duplicate_names.add(env_name)
        seen_names.add(env_name)
        values[env_name] = value.strip().strip("'\"")

    if duplicate_names:
        return {}, [
            f"{env_file} contains duplicate variable: {name}" for name in sorted(duplicate_names)
        ]
    return values, []


def _is_valid_env_name(name: str) -> bool:
    if not name:
        return False
    first = name[0]
    if not (first.isalpha() or first == "_"):
        return False
    return all(character.isalnum() or character == "_" for character in name)


def _settings_from_raw_values(values: dict[str, str]) -> Settings:
    fields = set(Settings.model_fields)
    return Settings.model_validate(
        {
            name.strip().lower(): value
            for name, value in values.items()
            if name.strip().lower() in fields
        }
    )


def _validate_raw_values(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for name in sorted(REQUIRED_RAW_ENV):
        value = values.get(name)
        if value is None or not value.strip():
            errors.append(f"{name} is required")
            continue
        lowered = value.strip().lower()
        if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            errors.append(f"{name} still uses a placeholder value")
    return errors


def _validate_release_values(values: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for name in RELEASE_HTTPS_URL_ENV:
        errors.extend(_validate_release_public_url(name, values.get(name, "")))
    for name, min_length in RELEASE_SECRET_MIN_LENGTHS.items():
        value = values.get(name, "").strip()
        if value and len(value) < min_length:
            errors.append(f"{name} is too short for release env validation")

    if values.get("WEB_PUSH_ALLOW_FAKE_IP_HOSTS", "").strip():
        errors.append("WEB_PUSH_ALLOW_FAKE_IP_HOSTS must be empty for release env validation")

    return errors


def _validate_release_public_url(name: str, value: str) -> list[str]:
    errors: list[str] = []
    stripped = value.strip()
    if not stripped:
        return errors

    parsed = urlparse(stripped)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return [f"{name} must use https:// for release env validation"]
    if parsed.username or parsed.password:
        errors.append(f"{name} must not include userinfo for release env validation")

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        errors.append(f"{name} must use a public hostname for release env validation")
        return errors
    if hostname == "localhost" or hostname.endswith(".local"):
        errors.append(f"{name} must use a public hostname for release env validation")
        return errors

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return errors

    errors.append(f"{name} must use a public hostname for release env validation")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a real production env file before release.",
    )
    parser.add_argument(
        "env_file",
        nargs="?",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Path to the real env file. Defaults to infra/env.production.",
    )
    args = parser.parse_args(argv)

    errors = validate_release_env(args.env_file)
    if errors:
        print("Release environment validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Release environment validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
