import { authHeaders, requestJson } from "./client";

export interface WeeklyReportResponse {
  id: string;
  week_start: string;
  week_end: string;
  metrics: Record<string, unknown> & {
    completed_session_count?: number;
  };
  summary: string;
  created_at: string;
  updated_at: string;
}

export interface PersonalDataExportResponse {
  generated_at: string;
  user: Record<string, unknown>;
  training_policy: Record<string, unknown> | null;
  sessions: Record<string, unknown>[];
  defect_profiles: Record<string, unknown>[];
  weekly_reports: Record<string, unknown>[];
  appeals: Record<string, unknown>[];
  duplicate_complaints: Record<string, unknown>[];
  privacy_audit_events: Record<string, unknown>[];
}

export interface TrainingDeletionResponse {
  session_id: string;
  deleted: boolean;
  counts: Record<string, number>;
}

export interface AccountDeletionResponse {
  request_id: string;
  proof_code: string;
  status: "QUEUED";
}

export interface DeletionStatusResponse {
  request_id: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  counts: Record<string, unknown>;
  error_code: string | null;
  requested_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export async function fetchWeeklyReports(accessToken: string): Promise<WeeklyReportResponse[]> {
  return requestJson<WeeklyReportResponse[]>("/api/v1/me/weekly-reports", {
    headers: authHeaders(accessToken),
  });
}

export async function exportPersonalData(
  accessToken: string,
): Promise<PersonalDataExportResponse> {
  return requestJson<PersonalDataExportResponse>("/api/v1/me/export", {
    headers: authHeaders(accessToken),
  });
}

export async function deleteTraining(
  accessToken: string,
  sessionId: string,
): Promise<TrainingDeletionResponse> {
  return requestJson<TrainingDeletionResponse>(`/api/v1/me/trainings/${sessionId}`, {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });
}

export async function deleteAccount(accessToken: string): Promise<AccountDeletionResponse> {
  return requestJson<AccountDeletionResponse>("/api/v1/me", {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });
}

export async function fetchDeletionStatus(
  requestId: string,
  proofCode: string,
): Promise<DeletionStatusResponse> {
  return requestJson<DeletionStatusResponse>("/api/v1/privacy/deletion-status", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ request_id: requestId, proof_code: proofCode }),
  });
}
