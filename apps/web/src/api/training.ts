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

export interface TrainingAwaitingInputResponse {
  type: string;
  stage: AttemptStage;
  round: number;
  text: string;
}

export interface TrainingStateResponse {
  id: string;
  thread_id: string;
  stage: string;
  awaiting: TrainingAwaitingInputResponse | null;
  current_attempt: VoiceAttemptResponse | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface ResumeTrainingResponse {
  job_id: string;
  session_stage: string;
}

export interface TranscriptWordResponse {
  text: string;
  start_ms: number;
  end_ms: number;
  confidence: number | null;
}

export interface TranscriptSegmentResponse {
  id: string;
  segment_index: number;
  start_ms: number;
  end_ms: number;
  raw_text: string;
  corrected_text: string;
  words: TranscriptWordResponse[];
}

export interface AttemptTranscriptResponse {
  attempt_id: string;
  status: "PENDING" | "RUNNING" | "SUCCEEDED" | "FAILED";
  raw_text: string;
  corrected_text: string;
  language: string | null;
  error_code: string | null;
  metrics: Record<string, unknown> | null;
  segments: TranscriptSegmentResponse[];
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
  stage: AttemptStage,
  round: number,
): Promise<VoiceAttemptResponse> {
  return requestJson<VoiceAttemptResponse>(`/api/v1/trainings/${sessionId}/attempts`, {
    method: "POST",
    headers: {
      ...authHeaders(accessToken),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ stage, round }),
  });
}

export async function fetchTrainingState(
  accessToken: string,
  sessionId: string,
): Promise<TrainingStateResponse> {
  return requestJson<TrainingStateResponse>(`/api/v1/trainings/${sessionId}/state`, {
    headers: authHeaders(accessToken),
  });
}

export async function resumeTraining(
  accessToken: string,
  sessionId: string,
  attempt: VoiceAttemptResponse,
): Promise<ResumeTrainingResponse> {
  return requestJson<ResumeTrainingResponse>(`/api/v1/trainings/${sessionId}/resume`, {
    method: "POST",
    headers: {
      ...authHeaders(accessToken),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      stage: attempt.stage,
      round: attempt.round,
      attempt_id: attempt.id,
    }),
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

export async function fetchAttemptTranscript(
  accessToken: string,
  attemptId: string,
): Promise<AttemptTranscriptResponse> {
  return requestJson<AttemptTranscriptResponse>(`/api/v1/attempts/${attemptId}/transcript`, {
    headers: authHeaders(accessToken),
  });
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
