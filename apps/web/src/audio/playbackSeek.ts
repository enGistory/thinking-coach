import type { TranscriptSegmentResponse } from "../api/training";

export interface SeekablePlayback {
  currentTime: number;
  play: () => Promise<void>;
}

export function seekPlaybackToSegment(
  audio: SeekablePlayback | null,
  segment: Pick<TranscriptSegmentResponse, "start_ms">,
): void {
  if (audio === null) {
    return;
  }
  audio.currentTime = segment.start_ms / 1000;
  void audio.play();
}
