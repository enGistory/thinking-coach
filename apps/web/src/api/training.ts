import { authHeaders, requestJson } from "./client";

export type AttemptStage = "FIRST" | "FOLLOWUP" | "FINAL";

export interface TrainingSessionResponse {
  id: string;
  thread_id: string;
  stage: string;
  created_at: string;
}

export interface VoiceAttemptResponse {
  id: string;
  session_id: string;
  stage: AttemptStage;
  round: number;
  upload_status: "PENDING" | "UPLOADED" | "FAILED";
  mime_type: string | null;
  duration_ms: number | null;
  size_bytes: number | null;
  checksum_sha256: string | null;
  uploaded_at: string | null;
}

export async function createCurrentTraining(accessToken: string): Promise<TrainingSessionResponse> {
  return requestJson<TrainingSessionResponse>("/api/v1/trainings/current", {
    method: "POST",
    headers: authHeaders(accessToken),
  });
}

export async function createVoiceAttempt(
  accessToken: string,
  sessionId: string,
): Promise<VoiceAttemptResponse> {
  return requestJson<VoiceAttemptResponse>(`/api/v1/trainings/${sessionId}/attempts`, {
    method: "POST",
    headers: {
      ...authHeaders(accessToken),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ stage: "FIRST", round: 1 }),
  });
}

export async function uploadAttemptAudio(
  accessToken: string,
  attemptId: string,
  audio: Blob,
  durationMs: number,
  checksumSha256: string,
): Promise<VoiceAttemptResponse> {
  const body = new FormData();
  body.set("duration_ms", String(durationMs));
  body.set("checksum_sha256", checksumSha256);
  body.set("audio", audio, preferredFilename(audio.type));

  return requestJson<VoiceAttemptResponse>(`/api/v1/attempts/${attemptId}/audio`, {
    method: "PUT",
    headers: authHeaders(accessToken),
    body,
  });
}

export async function fetchAttemptAudio(accessToken: string, attemptId: string): Promise<Blob> {
  const response = await fetch(`/api/v1/attempts/${attemptId}/audio`, {
    headers: authHeaders(accessToken),
  });
  if (!response.ok) {
    throw new Error(`音频回放失败：${response.status}`);
  }
  return await response.blob();
}

function preferredFilename(mimeType: string): string {
  if (mimeType.includes("mp4") || mimeType.includes("aac")) {
    return "answer.m4a";
  }
  if (mimeType.includes("ogg")) {
    return "answer.ogg";
  }
  return "answer.webm";
}
