import { afterEach, describe, expect, it, vi } from "vitest";

import { setupPushNotifications } from "./pushNotifications";

const publicKey = "AQID";

interface FetchCall {
  input: RequestInfo | URL;
  init: RequestInit | undefined;
}

function stubPushGlobals(registration: ServiceWorkerRegistration): void {
  vi.stubGlobal("Notification", {
    requestPermission: vi.fn().mockResolvedValue("granted"),
  });
  vi.stubGlobal("PushManager", class {});
  vi.stubGlobal("atob", (value: string) => {
    expect(value).toBe(publicKey);
    return "\x01\x02\x03";
  });
  vi.stubGlobal("navigator", {
    serviceWorker: {
      ready: Promise.resolve(registration),
    },
    userAgent: "vitest",
  });
}

function fakeSubscription(): PushSubscription {
  return {
    toJSON: () => ({
      endpoint: "https://push.example/subscription/1",
      keys: { p256dh: "p256dh-key", auth: "auth-key" },
      expirationTime: null,
    }),
  } as unknown as PushSubscription;
}

describe("setupPushNotifications", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns unsupported when the browser grants permission but provides no subscription", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(JSON.stringify({ public_key: publicKey }), { status: 200 });
    });
    stubPushGlobals({
      pushManager: {
        getSubscription: vi.fn().mockResolvedValue(null),
        subscribe: vi.fn().mockResolvedValue(null),
      },
    } as unknown as ServiceWorkerRegistration);

    await expect(setupPushNotifications("token-1")).resolves.toBe("unsupported");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.input).toBe("/api/v1/push/public-key");
  });

  it("returns unsupported when push subscription registration rejects", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      return new Response(JSON.stringify({ public_key: publicKey }), { status: 200 });
    });
    stubPushGlobals({
      pushManager: {
        getSubscription: vi.fn().mockResolvedValue(null),
        subscribe: vi.fn().mockRejectedValue(new Error("Registration failed - push service error")),
      },
    } as unknown as ServiceWorkerRegistration);

    await expect(setupPushNotifications("token-1")).resolves.toBe("unsupported");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.input).toBe("/api/v1/push/public-key");
  });

  it("uses a subscription that becomes available after subscribe resolves empty", async () => {
    const calls: FetchCall[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ input, init });
      if (input === "/api/v1/push/public-key") {
        return new Response(JSON.stringify({ public_key: publicKey }), { status: 200 });
      }
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
    stubPushGlobals({
      pushManager: {
        getSubscription: vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce(fakeSubscription()),
        subscribe: vi.fn().mockResolvedValue(null),
      },
    } as unknown as ServiceWorkerRegistration);

    await expect(setupPushNotifications("token-1")).resolves.toBe("subscribed");
    expect(calls).toHaveLength(2);
    expect(JSON.parse(String(calls[1]?.init?.body))).toMatchObject({
      endpoint: "https://push.example/subscription/1",
      keys: { p256dh: "p256dh-key", auth: "auth-key" },
    });
  });
});
