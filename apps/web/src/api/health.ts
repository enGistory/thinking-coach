export interface HealthCheck {
  ok: boolean;
  message: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  request_id: string;
  checks: Record<"app" | "database" | "audio_root", HealthCheck>;
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const init: RequestInit = signal ? { signal } : {};
  const response = await fetch("/api/v1/health", init);
  if (!response.ok) {
    throw new Error(`Health check failed with ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}

export function healthStatusText(status: HealthResponse["status"] | "error" | "unknown"): string {
  switch (status) {
    case "ok":
      return "服务可用";
    case "degraded":
      return "部分检查未通过";
    case "error":
      return "无法连接后端";
    case "unknown":
      return "等待检查";
  }
}
