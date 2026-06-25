import { fetchPushPublicKey, savePushSubscription } from "./api/push";

export type PushSetupResult = "subscribed" | "unsupported" | "denied" | "unconfigured";

export function isPushSupported(): boolean {
  return (
    "serviceWorker" in globalThis.navigator &&
    "PushManager" in globalThis &&
    "Notification" in globalThis
  );
}

export async function setupPushNotifications(accessToken: string): Promise<PushSetupResult> {
  if (!isPushSupported()) {
    return "unsupported";
  }
  const permission = await globalThis.Notification.requestPermission();
  if (permission !== "granted") {
    return "denied";
  }

  let publicKey = "";
  try {
    publicKey = (await fetchPushPublicKey()).public_key;
  } catch {
    return "unconfigured";
  }
  let subscription: PushSubscription | null = null;
  try {
    const registration = await globalThis.navigator.serviceWorker.ready;
    const existing = await registration.pushManager.getSubscription();
    subscription =
      existing ??
      (await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToArrayBuffer(publicKey),
      })) ??
      (await registration.pushManager.getSubscription());
  } catch {
    return "unsupported";
  }
  if (!subscription) {
    return "unsupported";
  }
  const json = subscription.toJSON();
  if (!json.endpoint || !json.keys?.p256dh || !json.keys.auth) {
    return "unsupported";
  }
  await savePushSubscription(accessToken, json);
  return "subscribed";
}

function urlBase64ToArrayBuffer(value: string): ArrayBuffer {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const base64 = `${value}${padding}`.replace(/-/g, "+").replace(/_/g, "/");
  const raw = globalThis.atob(base64);
  const buffer = new ArrayBuffer(raw.length);
  const output = new Uint8Array(buffer);
  for (let index = 0; index < raw.length; index += 1) {
    output[index] = raw.charCodeAt(index);
  }
  return buffer;
}
