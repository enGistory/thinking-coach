import { afterEach, describe, expect, it, vi } from "vitest";

import { createVoiceAttempt, fetchAttemptTranscript, uploadAttemptAudio } from "./training";

interface FetchCall {
  input: RequestInfo | URL;
  init: RequestInit | undefined;
}

describe("training API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a first voice attempt with bearer auth", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          id: "attempt-1",
          session_id: "session-1",
          stage: "FIRST",
          round: 1,
          upload_status: "PENDING",
          mime_type: null,
          duration_ms: null,
          size_bytes: null,
          checksum_sha256: null,
          uploaded_at: null,
        }),
        { status: 201 },
      );
    });

    const response = await createVoiceAttempt("token-1", "session-1");

    expect(response.id).toBe("attempt-1");
    expect(calls[0]?.input).toBe("/api/v1/trainings/session-1/attempts");
    expect(calls[0]?.init?.headers).toEqual({
      Authorization: "Bearer token-1",
      "Content-Type": "application/json",
    });
    expect(calls[0]?.init?.body).toBe(JSON.stringify({ stage: "FIRST", round: 1 }));
  });

  it("uploads audio as multipart form data", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          id: "attempt-1",
          session_id: "session-1",
          stage: "FIRST",
          round: 1,
          upload_status: "UPLOADED",
          mime_type: "audio/webm",
          duration_ms: 1200,
          size_bytes: 5,
          checksum_sha256: "a".repeat(64),
          uploaded_at: "2026-06-21T00:00:00Z",
        }),
        { status: 200 },
      );
    });

    await uploadAttemptAudio(
      "token-1",
      "attempt-1",
      new Blob(["audio"], { type: "audio/webm" }),
      1200,
      "a".repeat(64),
    );

    expect(calls[0]?.input).toBe("/api/v1/attempts/attempt-1/audio");
    expect(calls[0]?.init?.headers).toEqual({ Authorization: "Bearer token-1" });
    const body = calls[0]?.init?.body;
    expect(body).toBeInstanceOf(FormData);
    const formData = body as FormData;
    expect(formData.get("duration_ms")).toBe("1200");
    expect(formData.get("checksum_sha256")).toBe("a".repeat(64));
    expect(formData.get("audio")).toBeInstanceOf(File);
  });

  it("fetches timestamped transcript with bearer auth", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          attempt_id: "attempt-1",
          status: "SUCCEEDED",
          raw_text: "你好",
          corrected_text: "你好",
          language: "zh",
          error_code: null,
          metrics: { segment_count: 1 },
          segments: [
            {
              id: "segment-1",
              segment_index: 0,
              start_ms: 0,
              end_ms: 1000,
              raw_text: "你好",
              corrected_text: "你好",
              words: [{ text: "你好", start_ms: 0, end_ms: 1000, confidence: null }],
            },
          ],
        }),
        { status: 200 },
      );
    });

    const response = await fetchAttemptTranscript("token-1", "attempt-1");

    expect(response.segments[0]?.start_ms).toBe(0);
    expect(calls[0]?.input).toBe("/api/v1/attempts/attempt-1/transcript");
    expect(calls[0]?.init?.headers).toEqual({ Authorization: "Bearer token-1" });
  });
});
