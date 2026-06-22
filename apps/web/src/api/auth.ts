import { requestJson } from "./client";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_in: number;
}

export interface LoginPayload {
  nickname: string;
  password: string;
}

export async function login(payload: LoginPayload): Promise<TokenPair> {
  return requestJson<TokenPair>("/api/v1/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}
