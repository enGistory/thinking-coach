from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import oss2

from app.core.config import Settings
from app.db.models import VoiceAttempt
from app.services.audio_storage import AudioStorageError, resolve_stored_audio_path


class AudioAccessError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class TranscriptionAudioAccess:
    url: str
    object_name: str | None = None


async def build_transcription_audio_url(
    *,
    settings: Settings,
    attempt: VoiceAttempt,
    user_id: UUID,
) -> str:
    access = await build_transcription_audio_access(
        settings=settings,
        attempt=attempt,
        user_id=user_id,
    )
    return access.url


async def build_transcription_audio_access(
    *,
    settings: Settings,
    attempt: VoiceAttempt,
    user_id: UUID,
) -> TranscriptionAudioAccess:
    if settings.ai_provider_mode_normalized == "mock":
        return TranscriptionAudioAccess(url=f"mock://attempt/{attempt.id}")
    return await asyncio.to_thread(
        _build_aliyun_transcription_audio_access,
        settings=settings,
        attempt=attempt,
        user_id=user_id,
    )


async def cleanup_transcription_audio_access(
    *,
    settings: Settings,
    access: TranscriptionAudioAccess,
) -> None:
    if settings.ai_provider_mode_normalized == "mock" or access.object_name is None:
        return
    await asyncio.to_thread(
        _delete_aliyun_transcription_audio_object,
        settings=settings,
        object_name=access.object_name,
    )


def _build_aliyun_transcription_audio_access(
    *,
    settings: Settings,
    attempt: VoiceAttempt,
    user_id: UUID,
) -> TranscriptionAudioAccess:
    if attempt.audio_path is None:
        raise AudioAccessError("AUDIO_NOT_UPLOADED", "Attempt has no uploaded audio")

    try:
        audio_path = resolve_stored_audio_path(settings.audio_root_resolved, attempt.audio_path)
    except AudioStorageError as exc:
        raise AudioAccessError(exc.code, str(exc)) from exc
    if not audio_path.exists() or not audio_path.is_file():
        raise AudioAccessError("AUDIO_FILE_MISSING", "Uploaded audio file is missing")

    _validate_oss_settings(settings)
    object_name = _oss_object_name(user_id=user_id, attempt_id=attempt.id, audio_path=audio_path)
    secret = settings.aliyun_oss_access_key_secret
    if secret is None:
        raise AudioAccessError("OSS_CONFIG_MISSING", "ALIYUN_OSS_ACCESS_KEY_SECRET is missing")

    auth = oss2.Auth(settings.aliyun_oss_access_key_id, secret.get_secret_value())
    bucket = oss2.Bucket(auth, settings.aliyun_oss_endpoint, settings.aliyun_oss_bucket)
    try:
        bucket.put_object_from_file(object_name, str(audio_path))
        return TranscriptionAudioAccess(
            url=str(bucket.sign_url("GET", object_name, _signed_url_ttl_seconds(settings))),
            object_name=object_name,
        )
    except Exception as exc:
        raise AudioAccessError(
            "OSS_UPLOAD_FAILED",
            "Failed to prepare private audio object for ASR",
        ) from exc


def _delete_aliyun_transcription_audio_object(*, settings: Settings, object_name: str) -> None:
    _validate_oss_settings(settings)
    secret = settings.aliyun_oss_access_key_secret
    if secret is None:
        raise AudioAccessError("OSS_CONFIG_MISSING", "ALIYUN_OSS_ACCESS_KEY_SECRET is missing")

    auth = oss2.Auth(settings.aliyun_oss_access_key_id, secret.get_secret_value())
    bucket = oss2.Bucket(auth, settings.aliyun_oss_endpoint, settings.aliyun_oss_bucket)
    try:
        bucket.delete_object(object_name)
    except Exception as exc:
        raise AudioAccessError(
            "OSS_CLEANUP_FAILED",
            "Failed to clean up private audio object for ASR",
        ) from exc


def _validate_oss_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in {
            "ALIYUN_OSS_ENDPOINT": settings.aliyun_oss_endpoint,
            "ALIYUN_OSS_BUCKET": settings.aliyun_oss_bucket,
            "ALIYUN_OSS_ACCESS_KEY_ID": settings.aliyun_oss_access_key_id,
        }.items()
        if not value.strip()
    ]
    if (
        not settings.aliyun_oss_access_key_secret
        or not settings.aliyun_oss_access_key_secret.get_secret_value().strip()
    ):
        missing.append("ALIYUN_OSS_ACCESS_KEY_SECRET")
    if missing:
        raise AudioAccessError(
            "OSS_CONFIG_MISSING",
            f"Missing required OSS settings: {', '.join(missing)}",
        )


def _oss_object_name(*, user_id: UUID, attempt_id: UUID, audio_path: Path) -> str:
    return f"asr-temp/{user_id}/{attempt_id}/{audio_path.name}"


def _signed_url_ttl_seconds(settings: Settings) -> int:
    return max(1, min(settings.aliyun_oss_signed_url_ttl_seconds, 900))
