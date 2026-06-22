from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import aiofiles  # type: ignore[import-untyped]
from fastapi import UploadFile

ALLOWED_AUDIO_MIME_TYPES = {
    "audio/aac": "aac",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
}
CHUNK_SIZE = 1024 * 1024


class AudioStorageError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class StoredAudio:
    relative_path: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str


def normalize_audio_mime(content_type: str | None) -> str:
    mime_type = (content_type or "").split(";", 1)[0].strip().lower()
    if mime_type not in ALLOWED_AUDIO_MIME_TYPES:
        raise AudioStorageError("AUDIO_MIME_UNSUPPORTED", "Unsupported audio MIME type")
    return mime_type


async def save_audio_upload(
    *,
    audio_root: Path,
    upload: UploadFile,
    user_id: UUID,
    session_id: UUID,
    attempt_id: UUID,
    expected_checksum: str,
    max_bytes: int,
) -> StoredAudio:
    mime_type = normalize_audio_mime(upload.content_type)
    extension = ALLOWED_AUDIO_MIME_TYPES[mime_type]
    attempt_dir = audio_root / str(user_id) / str(session_id)
    final_path = attempt_dir / f"{attempt_id}.{extension}"
    temp_path = attempt_dir / f"{attempt_id}.{extension}.tmp"

    attempt_dir.mkdir(parents=True, exist_ok=True)
    checksum = hashlib.sha256()
    size_bytes = 0

    try:
        async with aiofiles.open(temp_path, "wb") as output:
            while chunk := await upload.read(CHUNK_SIZE):
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise AudioStorageError("AUDIO_TOO_LARGE", "Audio file is too large")
                checksum.update(chunk)
                await output.write(chunk)

        if size_bytes <= 0:
            raise AudioStorageError("AUDIO_EMPTY", "Audio file is empty")

        actual_checksum = checksum.hexdigest()
        if actual_checksum != expected_checksum:
            raise AudioStorageError("AUDIO_CHECKSUM_MISMATCH", "Audio checksum mismatch")

        os.replace(temp_path, final_path)
        return StoredAudio(
            relative_path=_relative_audio_path(audio_root, final_path),
            mime_type=mime_type,
            size_bytes=size_bytes,
            checksum_sha256=actual_checksum,
        )
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    finally:
        await upload.close()


def resolve_stored_audio_path(audio_root: Path, relative_path: str) -> Path:
    candidate = (audio_root / relative_path).resolve()
    root = audio_root.resolve()
    if root != candidate and root not in candidate.parents:
        raise AudioStorageError("AUDIO_PATH_INVALID", "Audio path is outside the audio root")
    return candidate


def _relative_audio_path(audio_root: Path, path: Path) -> str:
    return path.resolve().relative_to(audio_root.resolve()).as_posix()
