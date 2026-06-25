import { describe, expect, it } from "vitest";

import type { TrainingStateResponse } from "./api/training";
import {
  restorableSessionIdFromHref,
  shouldContinueTrainingStatePolling,
  shouldFetchTrainingProvenance,
  shouldRestoreStoredTrainingState,
  syncTrainingStatePolling,
} from "./trainingFlow";

describe("training flow state polling", () => {
  it("continues polling while the graph is processing after transcript completion", () => {
    expect(shouldContinueTrainingStatePolling(trainingState("PROCESS_FIRST"))).toBe(true);
    expect(shouldContinueTrainingStatePolling(trainingState("PROCESS_FOLLOWUP"))).toBe(true);
    expect(shouldContinueTrainingStatePolling(trainingState("EVALUATING"))).toBe(true);
  });

  it("stops polling when the graph is waiting for user input or terminal", () => {
    expect(
      shouldContinueTrainingStatePolling(
        trainingState("WAIT_FOLLOWUP_AUDIO", {
          type: "FOLLOWUP_QUESTION",
          stage: "FOLLOWUP",
          round: 1,
          text: "question",
        }),
      ),
    ).toBe(false);
    expect(shouldContinueTrainingStatePolling(trainingState("COMPLETED"))).toBe(false);
    expect(shouldContinueTrainingStatePolling(trainingState("FAILED_RETRYABLE"))).toBe(false);
  });

  it("starts state polling after browser restore into a processing graph stage", () => {
    const calls: string[] = [];

    syncTrainingStatePolling(trainingState("PROCESS_FIRST"), {
      start: () => calls.push("start"),
      stop: () => calls.push("stop"),
    });
    syncTrainingStatePolling(
      trainingState("WAIT_FOLLOWUP_AUDIO", {
        type: "FOLLOWUP_QUESTION",
        stage: "FOLLOWUP",
        round: 1,
        text: "question",
      }),
      {
        start: () => calls.push("start"),
        stop: () => calls.push("stop"),
      },
    );

    expect(calls).toEqual(["start", "stop"]);
  });

  it("fetches provenance only for completed source-backed sessions", () => {
    expect(
      shouldFetchTrainingProvenance(
        trainingState("COMPLETED", null, {
          source_count: 1,
          highest_source_level: "A",
          credential: "SRC-TEST",
        }),
      ),
    ).toBe(true);
    expect(shouldFetchTrainingProvenance(trainingState("COMPLETED"))).toBe(false);
    expect(
      shouldFetchTrainingProvenance(
        trainingState("WAIT_FIRST_AUDIO", null, {
          source_count: 1,
          highest_source_level: "A",
          credential: "SRC-TEST",
        }),
      ),
    ).toBe(false);
  });

  it("uses notification URL session id before a stored session id", () => {
    expect(restorableSessionIdFromHref("http://localhost:5182/?session=session-from-url", "stored")).toBe(
      "session-from-url",
    );
    expect(restorableSessionIdFromHref("http://localhost:5182/", "stored")).toBe("stored");
    expect(restorableSessionIdFromHref("not a url", "stored")).toBe("stored");
  });

  it("restores only completed stored sessions after current session lookup misses", () => {
    expect(shouldRestoreStoredTrainingState(trainingState("COMPLETED"))).toBe(true);
    expect(shouldRestoreStoredTrainingState(trainingState("WAIT_FIRST_AUDIO"))).toBe(false);
    expect(shouldRestoreStoredTrainingState(trainingState("EXPIRED"))).toBe(false);
  });
});

function trainingState(
  stage: string,
  awaiting: TrainingStateResponse["awaiting"] = null,
  sourceSummary: TrainingStateResponse["source_summary"] = null,
): TrainingStateResponse {
  return {
    id: "session-1",
    thread_id: "thread-1",
    stage,
    awaiting,
    current_attempt: null,
    source_summary: sourceSummary,
    created_at: "2026-06-22T00:00:00Z",
    updated_at: "2026-06-22T00:00:00Z",
    completed_at: stage === "COMPLETED" ? "2026-06-22T00:00:01Z" : null,
  };
}
