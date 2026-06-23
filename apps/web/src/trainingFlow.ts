import type { TrainingStateResponse } from "./api/training";

const PROCESSING_TRAINING_STAGES = new Set(["PROCESS_FIRST", "PROCESS_FOLLOWUP", "EVALUATING"]);

export interface TrainingStatePollingControls {
  start: () => void;
  stop: () => void;
}

export function shouldContinueTrainingStatePolling(state: TrainingStateResponse): boolean {
  return state.awaiting === null && PROCESSING_TRAINING_STAGES.has(state.stage);
}

export function syncTrainingStatePolling(
  state: TrainingStateResponse,
  controls: TrainingStatePollingControls,
): void {
  if (shouldContinueTrainingStatePolling(state)) {
    controls.start();
    return;
  }
  controls.stop();
}
