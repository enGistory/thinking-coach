import { afterEach, describe, expect, it, vi } from "vitest";

import { login, refreshAuth } from "./auth";

interface FetchCall {
  input: RequestInfo | URL;
  init: RequestInit | undefined;
}

describe("auth API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("logs in with nickname and password", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(JSON.stringify(tokenPair()), { status: 200 });
    });

    const response = await login({ nickname: "user", password: "pass" });

    expect(response.access_token).toBe("access-1");
    expect(calls[0]?.input).toBe("/api/v1/auth/login");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(calls[0]?.init?.body).toBe(JSON.stringify({ nickname: "user", password: "pass" }));
  });

  it("refreshes an access token with the stored refresh token", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(JSON.stringify(tokenPair()), { status: 200 });
    });

    const response = await refreshAuth({ refresh_token: "refresh-old" });

    expect(response.refresh_token).toBe("refresh-1");
    expect(calls[0]?.input).toBe("/api/v1/auth/refresh");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.headers).toEqual({ "Content-Type": "application/json" });
    expect(calls[0]?.init?.body).toBe(JSON.stringify({ refresh_token: "refresh-old" }));
  });
});

function tokenPair() {
  return {
    access_token: "access-1",
    refresh_token: "refresh-1",
    token_type: "bearer",
    expires_in: 1800,
  };
}
