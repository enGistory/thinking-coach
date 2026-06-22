import { afterEach, describe, expect, it, vi } from "vitest";

import {
  deletePendingAudioBestEffort,
  savePendingAudioBestEffort,
  type PendingAudioRecord,
} from "./pendingAudioStore";

function pendingRecord(): PendingAudioRecord {
  return {
    attemptId: "attempt-1",
    blob: new Blob(["audio"], { type: "audio/webm" }),
    mimeType: "audio/webm",
    durationMs: 1200,
    checksumSha256: "a".repeat(64),
    createdAt: "2026-06-21T00:00:00Z",
  };
}

describe("pending audio best-effort helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("does not fail recording flow when local save fails", async () => {
    vi.stubGlobal("indexedDB", {});
    const save = vi.fn(async () => {
      throw new Error("quota exceeded");
    });

    await expect(savePendingAudioBestEffort(pendingRecord(), save)).resolves.toBe(false);
    expect(save).toHaveBeenCalledOnce();
  });

  it("does not fail uploaded state when local delete fails", async () => {
    vi.stubGlobal("indexedDB", {});
    const remove = vi.fn(async () => {
      throw new Error("delete failed");
    });

    await expect(deletePendingAudioBestEffort("attempt-1", remove)).resolves.toBe(false);
    expect(remove).toHaveBeenCalledWith("attempt-1");
  });
});
