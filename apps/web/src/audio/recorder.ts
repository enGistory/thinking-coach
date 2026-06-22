export const RECORDING_MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/aac",
  "audio/ogg",
] as const;

export const MAX_AUDIO_SECONDS = 180;
export const MAX_AUDIO_DURATION_MS = MAX_AUDIO_SECONDS * 1000;
export const AUTO_STOP_AUDIO_SECONDS = MAX_AUDIO_SECONDS - 1;
export const MAX_AUDIO_BYTES = 20 * 1024 * 1024;

export function isRecordingSupported(): boolean {
  return (
    typeof globalThis.navigator !== "undefined" &&
    Boolean(globalThis.navigator.mediaDevices?.getUserMedia) &&
    typeof globalThis.MediaRecorder !== "undefined"
  );
}

export function selectSupportedMimeType(): string | null {
  if (typeof globalThis.MediaRecorder === "undefined") {
    return null;
  }

  const supported = RECORDING_MIME_CANDIDATES.find((mimeType) =>
    globalThis.MediaRecorder.isTypeSupported(mimeType),
  );
  return supported ?? "";
}

export function buildRecorderOptions(mimeType: string | null): MediaRecorderOptions | undefined {
  if (mimeType === null) {
    return undefined;
  }
  if (mimeType === "") {
    return undefined;
  }
  return { mimeType };
}