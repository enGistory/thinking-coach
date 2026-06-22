import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AUTO_STOP_AUDIO_SECONDS,
  buildRecorderOptions,
  isRecordingSupported,
  MAX_AUDIO_DURATION_MS,
  selectSupportedMimeType,
} from "./recorder";

describe("recorder helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("selects the first supported recording MIME type", () => {
    vi.stubGlobal("MediaRecorder", {
      isTypeSupported: (mimeType: string) => mimeType === "audio/mp4",
    });

    expect(selectSupportedMimeType()).toBe("audio/mp4");
  });

  it("detects whether browser recording APIs are available", () => {
    vi.stubGlobal("navigator", {
      mediaDevices: {
        getUserMedia: vi.fn(),
      },
    });
    vi.stubGlobal("MediaRecorder", {
      isTypeSupported: () => true,
    });

    expect(isRecordingSupported()).toBe(true);
  });

  it("keeps automatic stop below the backend maximum duration", () => {
    expect(AUTO_STOP_AUDIO_SECONDS * 1000).toBeLessThan(MAX_AUDIO_DURATION_MS);
  });

  it("omits MediaRecorder options when default MIME should be used", () => {
    expect(buildRecorderOptions(null)).toBeUndefined();
    expect(buildRecorderOptions("")).toBeUndefined();
    expect(buildRecorderOptions("audio/webm")).toEqual({ mimeType: "audio/webm" });
  });
});