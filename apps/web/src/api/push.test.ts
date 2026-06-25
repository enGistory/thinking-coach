import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchPushPublicKey, savePushSubscription } from "./push";

interface FetchCall {
  input: RequestInfo | URL;
  init: RequestInit | undefined;
}

describe("push API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches the VAPID public key", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(JSON.stringify({ public_key: "public-key-1" }), { status: 200 });
    });

    const response = await fetchPushPublicKey();

    expect(response.public_key).toBe("public-key-1");
    expect(calls[0]?.input).toBe("/api/v1/push/public-key");
    expect(calls[0]?.init).toEqual({});
  });

  it("saves a browser push subscription with bearer auth", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(
        JSON.stringify({
          id: "subscription-1",
          endpoint: "https://push.example/subscription/1",
          active: true,
          created_at: "2026-06-24T00:00:00Z",
        }),
        { status: 201 },
      );
    });

    const response = await savePushSubscription("token-1", {
      endpoint: "https://push.example/subscription/1",
      keys: { p256dh: "p256dh-key", auth: "auth-key" },
      expirationTime: null,
    });

    expect(response.active).toBe(true);
    expect(calls[0]?.input).toBe("/api/v1/push/subscriptions");
    expect(calls[0]?.init?.method).toBe("POST");
    expect(calls[0]?.init?.headers).toEqual({
      Authorization: "Bearer token-1",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(calls[0]?.init?.body))).toMatchObject({
      endpoint: "https://push.example/subscription/1",
      keys: { p256dh: "p256dh-key", auth: "auth-key" },
    });
  });
});
