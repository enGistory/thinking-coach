/* global self */

self.addEventListener("push", (event) => {
  let payload = {};
  if (event.data) {
    try {
      payload = event.data.json();
    } catch {
      payload = {};
    }
  }
  const title = "突击审核已到达";
  const options = {
    body: typeof payload.body === "string" ? payload.body : "预计用时约 3 分钟",
    tag: typeof payload.tag === "string" ? payload.tag : "thinking-coach-strike",
    data: {
      url: typeof payload.url === "string" ? payload.url : "/",
      session_id: typeof payload.session_id === "string" ? payload.session_id : "",
    },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = notificationTargetUrl(
    event.notification.data && event.notification.data.url
      ? event.notification.data.url
      : "/",
  );
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then(async (clients) => {
      for (const client of clients) {
        if ("navigate" in client && "focus" in client) {
          try {
            const navigatedClient = await client.navigate(targetUrl);
            const targetClient = navigatedClient || client;
            return targetClient.focus();
          } catch {
            break;
          }
        }
      }
      return self.clients.openWindow(targetUrl);
    }),
  );
});

function notificationTargetUrl(rawUrl) {
  const scopeUrl = new URL(self.registration.scope);
  try {
    const targetUrl = new URL(rawUrl, scopeUrl);
    if (targetUrl.origin === scopeUrl.origin) {
      return targetUrl.href;
    }
  } catch {
    // Fall through to the service worker scope.
  }
  return scopeUrl.href;
}
