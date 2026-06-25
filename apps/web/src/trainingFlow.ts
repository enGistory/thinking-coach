import type { TrainingStateResponse } from "./api/training";

const PROCESSING_TRAINING_STAGES = new Set(["PROCESS_FIRST", "PROCESS_FOLLOWUP", "EVALUATING"]);

export interface TrainingStatePollingControls {
  start: () => void;
  stop: () => void;
}

export function shouldContinueTrainingStatePolling(state: TrainingStateResponse): boolean {
  return state.awaiting === null && PROCESSING_TRAINING_STAGES.has(state.stage);
}

export function shouldFetchTrainingProvenance(state: TrainingStateResponse): boolean {
  return state.stage === "COMPLETED" && state.source_summary !== null;
}

export function shouldRestoreStoredTrainingState(state: TrainingStateResponse): boolean {
  return state.stage === "COMPLETED";
}

export function restorableSessionIdFromHref(href: string | undefined, storedSessionId: string): string {
  try {
    const sessionId = new URL(href ?? "").searchParams.get("session");
    return sessionId || storedSessionId;
  } catch {
    return storedSessionId;
  }
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
