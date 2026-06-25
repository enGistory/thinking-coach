import { authHeaders, requestJson } from "./client";

export interface PushPublicKeyResponse {
  public_key: string;
}

export interface PushSubscriptionResponse {
  id: string;
  endpoint: string;
  active: boolean;
  created_at: string;
}

export async function fetchPushPublicKey(): Promise<PushPublicKeyResponse> {
  return requestJson<PushPublicKeyResponse>("/api/v1/push/public-key");
}

export async function savePushSubscription(
  accessToken: string,
  subscription: PushSubscriptionJSON,
): Promise<PushSubscriptionResponse> {
  return requestJson<PushSubscriptionResponse>("/api/v1/push/subscriptions", {
    method: "POST",
    headers: {
      ...authHeaders(accessToken),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      endpoint: subscription.endpoint,
      keys: subscription.keys,
      user_agent: globalThis.navigator?.userAgent ?? "",
    }),
  });
}
