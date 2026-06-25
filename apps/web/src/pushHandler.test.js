import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

import { describe, expect, it, vi } from "vitest";

describe("push notification handler", () => {
  it("navigates an existing PWA window to the notification URL and focuses it", async () => {
    const navigatedClient = { focus: vi.fn().mockResolvedValue(undefined) };
    const client = {
      navigate: vi.fn().mockResolvedValue(navigatedClient),
      focus: vi.fn().mockResolvedValue(undefined),
    };
    const { listener, clients } = loadNotificationClickListener([client]);
    let pending;

    listener({
      notification: { data: { url: "/?session=session-1" }, close: vi.fn() },
      waitUntil: (promise) => {
        pending = promise;
      },
    });
    await pending;

    expect(client.navigate).toHaveBeenCalledWith("http://localhost:5182/?session=session-1");
    expect(navigatedClient.focus).toHaveBeenCalled();
    expect(clients.openWindow).not.toHaveBeenCalled();
  });

  it("opens a new PWA window when navigating an existing client fails", async () => {
    const client = {
      navigate: vi.fn().mockRejectedValue(new Error("navigate failed")),
      focus: vi.fn().mockResolvedValue(undefined),
    };
    const { listener, clients } = loadNotificationClickListener([client]);
    let pending;

    listener({
      notification: { data: { url: "/?session=session-2" }, close: vi.fn() },
      waitUntil: (promise) => {
        pending = promise;
      },
    });
    await pending;

    expect(clients.openWindow).toHaveBeenCalledWith("http://localhost:5182/?session=session-2");
  });

  it("does not open off-origin notification URLs", async () => {
    const { listener, clients } = loadNotificationClickListener([]);
    let pending;

    listener({
      notification: { data: { url: "https://example.invalid/phishing" }, close: vi.fn() },
      waitUntil: (promise) => {
        pending = promise;
      },
    });
    await pending;

    expect(clients.openWindow).toHaveBeenCalledWith("http://localhost:5182/");
  });
});

function loadNotificationClickListener(clientsToReturn) {
  const listeners = new Map();
  const clients = {
    matchAll: vi.fn().mockResolvedValue(clientsToReturn),
    openWindow: vi.fn().mockResolvedValue(undefined),
  };
  const serviceWorker = {
    addEventListener: (type, listener) => {
      listeners.set(type, listener);
    },
    registration: {
      scope: "http://localhost:5182/",
      showNotification: vi.fn().mockResolvedValue(undefined),
    },
    clients,
  };

  runInNewContext(readFileSync(new URL("../public/push-handler.js", import.meta.url), "utf8"), {
    self: serviceWorker,
    URL,
  });

  const listener = listeners.get("notificationclick");
  if (listener === undefined) {
    throw new Error("notificationclick listener was not registered");
  }
  return { listener, clients };
}
