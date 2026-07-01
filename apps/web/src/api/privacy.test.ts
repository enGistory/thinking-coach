import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deleteAccount,
  deleteTraining,
  exportPersonalData,
  fetchDeletionStatus,
  fetchWeeklyReports,
} from "./privacy";

interface FetchCall {
  input: RequestInfo | URL;
  init: RequestInit | undefined;
}

describe("privacy API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches weekly reports and export data with bearer auth", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      if (String(input).endsWith("/weekly-reports")) {
        return new Response(
          JSON.stringify([
            {
              id: "weekly-1",
              week_start: "2026-06-15",
              week_end: "2026-06-21",
              metrics: { completed_session_count: 2 },
              summary: "Two completed sessions.",
              created_at: "2026-06-25T00:00:00Z",
              updated_at: "2026-06-25T00:00:00Z",
            },
          ]),
          { status: 200 },
        );
      }
      return new Response(
        JSON.stringify({
          generated_at: "2026-06-25T00:00:00Z",
          user: { id: "user-1" },
          training_policy: null,
          sessions: [{ id: "session-1" }],
          defect_profiles: [],
          weekly_reports: [],
          appeals: [],
          duplicate_complaints: [],
          privacy_audit_events: [{ event_type: "EXPORT_TEST_AUDIT" }],
        }),
        { status: 200 },
      );
    });

    const weekly = await fetchWeeklyReports("token-1");
    const exported = await exportPersonalData("token-1");

    expect(weekly[0]?.metrics.completed_session_count).toBe(2);
    expect(exported.sessions[0]?.id).toBe("session-1");
    expect(exported.privacy_audit_events[0]?.event_type).toBe("EXPORT_TEST_AUDIT");
    expect(calls.map((call) => call.input)).toEqual([
      "/api/v1/me/weekly-reports",
      "/api/v1/me/export",
    ]);
    for (const call of calls) {
      expect(call.init?.headers).toEqual({ Authorization: "Bearer token-1" });
    }
  });

  it("deletes a single training and requests account deletion with bearer auth", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      if (String(input).includes("/trainings/")) {
        return new Response(
          JSON.stringify({
            session_id: "session-1",
            deleted: true,
            counts: { sessions: 1, audio_files: 1, checkpoint_rows: 3 },
          }),
          { status: 200 },
        );
      }
      return new Response(
        JSON.stringify({
          request_id: "request-1",
          proof_code: "proof-1",
          status: "QUEUED",
        }),
        { status: 202 },
      );
    });

    const training = await deleteTraining("token-1", "session-1");
    const account = await deleteAccount("token-1");

    expect(training.counts.audio_files).toBe(1);
    expect(account.proof_code).toBe("proof-1");
    expect(calls.map((call) => call.input)).toEqual([
      "/api/v1/me/trainings/session-1",
      "/api/v1/me",
    ]);
    expect(calls.map((call) => call.init?.method)).toEqual(["DELETE", "DELETE"]);
    for (const call of calls) {
      expect(call.init?.headers).toEqual({ Authorization: "Bearer token-1" });
    }
  });

  it("checks deletion status with proof code and without bearer auth", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          request_id: "request-1",
          status: "SUCCEEDED",
          counts: { users: 1 },
          error_code: null,
          requested_at: "2026-06-25T00:00:00Z",
          started_at: "2026-06-25T00:01:00Z",
          completed_at: "2026-06-25T00:02:00Z",
        }),
        { status: 200 },
      );
    });

    const status = await fetchDeletionStatus("request-1", "proof-1");

    expect(status.status).toBe("SUCCEEDED");
    expect(calls[0]?.input).toBe("/api/v1/privacy/deletion-status");
    expect(String(calls[0]?.input)).not.toContain("proof-1");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(calls[0]?.init?.body).toBe(
      JSON.stringify({ request_id: "request-1", proof_code: "proof-1" }),
    );
  });
});
