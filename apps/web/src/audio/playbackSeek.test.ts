import { describe, expect, it, vi } from "vitest";

import { seekPlaybackToSegment, type SeekablePlayback } from "./playbackSeek";

describe("playback seek", () => {
  it("seeks audio to the transcript segment start time", () => {
    const audio: SeekablePlayback = {
      currentTime: 0,
      play: vi.fn(async () => undefined),
    };

    seekPlaybackToSegment(audio, { start_ms: 2350 });

    expect(audio.currentTime).toBe(2.35);
    expect(audio.play).toHaveBeenCalledOnce();
  });

  it("ignores missing audio element", () => {
    expect(() => seekPlaybackToSegment(null, { start_ms: 1000 })).not.toThrow();
  });
});
