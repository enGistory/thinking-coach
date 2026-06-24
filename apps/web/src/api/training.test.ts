import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createDuplicateComplaint,
  createVoiceAttempt,
  fetchAttemptTranscript,
  fetchTrainingProvenance,
  fetchTrainingState,
  resumeTraining,
  uploadAttemptAudio,
} from "./training";

interface FetchCall {
  input: RequestInfo | URL;
  init: RequestInit | undefined;
}

describe("training API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a voice attempt for the requested slot with bearer auth", async () => {
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

    const response = await createVoiceAttempt("token-1", "session-1", "FOLLOWUP", 1);

    expect(response.id).toBe("attempt-1");
    expect(calls[0]?.input).toBe("/api/v1/trainings/session-1/attempts");
    expect(calls[0]?.init?.headers).toEqual({
      Authorization: "Bearer token-1",
      "Content-Type": "application/json",
    });
    expect(calls[0]?.init?.body).toBe(JSON.stringify({ stage: "FOLLOWUP", round: 1 }));
  });

  it("fetches training state with bearer auth", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          id: "session-1",
          thread_id: "session-1",
          stage: "WAIT_FOLLOWUP_AUDIO",
          awaiting: {
            type: "FOLLOWUP_QUESTION",
            stage: "FOLLOWUP",
            round: 1,
            text: "追问文本",
          },
          current_attempt: null,
          source_summary: null,
          created_at: "2026-06-22T00:00:00Z",
          updated_at: "2026-06-22T00:00:00Z",
          completed_at: null,
        }),
        { status: 200 },
      );
    });

    const response = await fetchTrainingState("token-1", "session-1");

    expect(response.awaiting?.stage).toBe("FOLLOWUP");
    expect(calls[0]?.input).toBe("/api/v1/trainings/session-1/state");
    expect(calls[0]?.init?.headers).toEqual({ Authorization: "Bearer token-1" });
  });

  it("fetches completed training provenance with bearer auth", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          session_id: "session-1",
          question_id: "question-1",
          prompt: "题目文本",
          source_summary: {
            source_count: 1,
            highest_source_level: "A",
            credential: "SRC-TEST",
          },
          sources: [
            {
              id: "source-1",
              title: "官方报告",
              publisher: "Example 官方",
              url: "https://example.com/report",
              level: "A",
              published_at: null,
              accessed_at: "2026-06-22T00:00:00Z",
              snapshot_hash: "a".repeat(64),
              claims: [
                {
                  id: "claim-1",
                  claim_text: "来源支持的事实",
                  locator: "paragraph 1",
                  excerpt: "来源支持的事实",
                  support_status: "VERIFIED",
                },
              ],
            },
          ],
          mappings: [
            {
              sentence_index: 0,
              sentence_text: "题目事实句",
              claim_ids: ["claim-1"],
            },
          ],
          hypothetical_assumptions: [],
        }),
        { status: 200 },
      );
    });

    const response = await fetchTrainingProvenance("token-1", "session-1");

    expect(response.sources[0]?.claims[0]?.support_status).toBe("VERIFIED");
    expect(calls[0]?.input).toBe("/api/v1/trainings/session-1/provenance");
    expect(calls[0]?.init?.headers).toEqual({ Authorization: "Bearer token-1" });
  });

  it("submits a duplicate complaint with reason and type", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          id: "complaint-1",
          session_id: "session-1",
          question_id: "question-1",
          template_family: "family-1",
          status: "ACCEPTED",
          replacement_job_id: "job-1",
          created_at: "2026-06-24T00:00:00Z",
        }),
        { status: 201 },
      );
    });

    const response = await createDuplicateComplaint("token-1", "session-1", {
      reason: "same answer skeleton",
      duplicate_type: "answer_skeleton",
    });

    expect(response.replacement_job_id).toBe("job-1");
    expect(calls[0]?.input).toBe("/api/v1/trainings/session-1/duplicate-complaints");
    expect(calls[0]?.init?.headers).toEqual({
      Authorization: "Bearer token-1",
      "Content-Type": "application/json",
    });
    expect(calls[0]?.init?.body).toBe(
      JSON.stringify({
        reason: "same answer skeleton",
        duplicate_type: "answer_skeleton",
      }),
    );
  });

  it("resumes a training session with the uploaded attempt slot", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          job_id: "job-1",
          session_stage: "PROCESS_FIRST",
        }),
        { status: 202 },
      );
    });

    const response = await resumeTraining("token-1", "session-1", {
      id: "attempt-1",
      session_id: "session-1",
      stage: "FIRST",
      round: 1,
      upload_status: "UPLOADED",
      mime_type: "audio/webm",
      duration_ms: 1200,
      size_bytes: 5,
      checksum_sha256: "a".repeat(64),
      uploaded_at: "2026-06-22T00:00:00Z",
    });

    expect(response.job_id).toBe("job-1");
    expect(calls[0]?.input).toBe("/api/v1/trainings/session-1/resume");
    expect(calls[0]?.init?.headers).toEqual({
      Authorization: "Bearer token-1",
      "Content-Type": "application/json",
    });
    expect(calls[0]?.init?.body).toBe(
      JSON.stringify({ stage: "FIRST", round: 1, attempt_id: "attempt-1" }),
    );
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
