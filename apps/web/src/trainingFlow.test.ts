import { describe, expect, it } from "vitest";

import type { TrainingStateResponse } from "./api/training";
import { shouldContinueTrainingStatePolling, syncTrainingStatePolling } from "./trainingFlow";

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
});

function trainingState(
  stage: string,
  awaiting: TrainingStateResponse["awaiting"] = null,
): TrainingStateResponse {
  return {
    id: "session-1",
    thread_id: "thread-1",
    stage,
    awaiting,
    current_attempt: null,
    created_at: "2026-06-22T00:00:00Z",
    updated_at: "2026-06-22T00:00:00Z",
    completed_at: stage === "COMPLETED" ? "2026-06-22T00:00:01Z" : null,
  };
}
