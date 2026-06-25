<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { login, refreshAuth, type TokenPair } from "../api/auth";
import { ApiError } from "../api/client";
import {
  abandonTraining,
  acceptTraining,
  createDuplicateComplaint,
  deferTraining,
  fetchCurrentTraining,
  createVoiceAttempt,
  fetchAttemptAudio,
  fetchAttemptTranscript,
  fetchTrainingProvenance,
  fetchTrainingState,
  resumeTraining,
  uploadAttemptAudio,
  type AttemptTranscriptResponse,
  type DuplicateComplaintResponse,
  type DuplicateType,
  type TrainingProvenanceResponse,
  type TranscriptSegmentResponse,
  type TrainingSessionResponse,
  type TrainingStateResponse,
  type VoiceAttemptResponse,
} from "../api/training";
import { sha256Hex } from "../audio/checksum";
import { seekPlaybackToSegment, type SeekablePlayback } from "../audio/playbackSeek";
import {
  AUTO_STOP_AUDIO_SECONDS,
  buildRecorderOptions,
  isRecordingSupported,
  MAX_AUDIO_BYTES,
  MAX_AUDIO_DURATION_MS,
  MAX_AUDIO_SECONDS,
  selectSupportedMimeType,
} from "../audio/recorder";
import {
  isPendingAudioStoreAvailable,
  loadPendingAudio,
  savePendingAudioBestEffort,
  deletePendingAudioBestEffort,
  type PendingAudioRecord,
} from "../audio/pendingAudioStore";
import {
  restorableSessionIdFromHref,
  shouldContinueTrainingStatePolling,
  shouldFetchTrainingProvenance,
  shouldRestoreStoredTrainingState,
  syncTrainingStatePolling,
} from "../trainingFlow";
import { setupPushNotifications, type PushSetupResult } from "../pushNotifications";

type RecorderState = "idle" | "recording" | "uploading" | "pending" | "uploaded";

const ACCESS_TOKEN_KEY = "thinkingCoachAccessToken";
const REFRESH_TOKEN_KEY = "thinkingCoachRefreshToken";
const ACTIVE_SESSION_KEY = "thinkingCoachActiveSessionId";
const PENDING_ATTEMPT_KEY = "thinkingCoachPendingAttemptId";

const nickname = ref("");
const password = ref("");
const accessToken = ref(readSessionValue(ACCESS_TOKEN_KEY));
const trainingSession = ref<TrainingSessionResponse | null>(null);
const trainingState = ref<TrainingStateResponse | null>(null);
const attempt = ref<VoiceAttemptResponse | null>(null);
const recorderState = ref<RecorderState>("idle");
const statusMessage = ref("等待登录");
const errorMessage = ref("");
const notificationStatus = ref("");
const remainingSeconds = ref(MAX_AUDIO_SECONDS);
const playbackUrl = ref("");
const transcript = ref<AttemptTranscriptResponse | null>(null);
const provenance = ref<TrainingProvenanceResponse | null>(null);
const duplicateType = ref<DuplicateType>("other");
const duplicateReason = ref("");
const duplicateComplaint = ref<DuplicateComplaintResponse | null>(null);
const duplicateSubmitting = ref(false);
const activeSessionId = ref(readRestorableSessionId());
const pendingAttemptId = ref(readLocalValue(PENDING_ATTEMPT_KEY));
const playbackAudio = ref<SeekablePlayback | null>(null);

const isAuthenticated = computed(() => accessToken.value.length > 0);
const awaitingInput = computed(() => trainingState.value?.awaiting ?? null);
const hasNotifiedStrike = computed(() => isLiveNotifiedSession(trainingSession.value));
const canStartRecording = computed(
  () => isAuthenticated.value && recorderState.value === "idle" && awaitingInput.value !== null,
);
const canAcceptStrike = computed(() => isAuthenticated.value && hasNotifiedStrike.value);
const canDeferStrike = computed(() => isAuthenticated.value && hasNotifiedStrike.value);
const canAbandonTraining = computed(
  () =>
    isAuthenticated.value &&
    trainingState.value !== null &&
    [
      "ACCEPTED",
      "QUESTION_EXPOSED",
      "WAIT_FIRST_AUDIO",
      "WAIT_FOLLOWUP_AUDIO",
      "WAIT_FINAL_AUDIO",
    ].includes(trainingState.value.stage),
);
const hasPendingUpload = computed(() => recorderState.value === "pending" && pendingAttemptId.value.length > 0);
const canSubmitDuplicateComplaint = computed(
  () =>
    trainingState.value?.stage === "COMPLETED" &&
    provenance.value !== null &&
    duplicateReason.value.trim().length > 0 &&
    duplicateComplaint.value === null &&
    !duplicateSubmitting.value,
);

let mediaRecorder: MediaRecorder | null = null;
let mediaStream: MediaStream | null = null;
let chunks: Blob[] = [];
let recordingStartedAt = 0;
let countdownTimer: number | undefined;
let autoStopTimer: number | undefined;
let transcriptPollTimer: number | undefined;
let trainingStatePollTimer: number | undefined;
let inMemoryPendingRecord: PendingAudioRecord | null = null;

onMounted(() => {
  void restoreAuthSession();
});

onBeforeUnmount(() => {
  clearRecordingTimers();
  stopTranscriptPolling();
  stopTrainingStatePolling();
  stopMediaTracks();
  revokePlaybackUrl();
});

async function submitLogin() {
  clearMessages();
  try {
    const tokens = await login({
      nickname: nickname.value,
      password: password.value,
    });
    rememberTokenPair(tokens);
    statusMessage.value = "登录成功";
    await restoreTrainingFlow();
  } catch (error) {
    errorMessage.value = errorToMessage(error, "登录失败");
  }
}

async function restoreAuthSession() {
  if (isAuthenticated.value) {
    statusMessage.value = "已恢复登录状态";
    await restoreTrainingFlow();
    return;
  }
  const refreshToken = readLocalValue(REFRESH_TOKEN_KEY);
  if (!refreshToken) {
    return;
  }
  statusMessage.value = "正在恢复登录";
  try {
    rememberTokenPair(await refreshAuth({ refresh_token: refreshToken }));
    statusMessage.value = "已恢复登录状态";
    await restoreTrainingFlow();
  } catch {
    forgetAuthTokens();
    statusMessage.value = "等待登录";
  }
}

async function ensureTrainingSession(): Promise<TrainingSessionResponse> {
  if (!accessToken.value) {
    throw new Error("请先登录");
  }
  if (trainingSession.value !== null) {
    return trainingSession.value;
  }
  trainingSession.value = await fetchCurrentTraining(accessToken.value);
  rememberActiveSessionId(trainingSession.value.id);
  return trainingSession.value;
}

async function refreshTrainingState(): Promise<TrainingStateResponse> {
  if (!accessToken.value) {
    throw new Error("请先登录");
  }
  let session: TrainingSessionResponse;
  try {
    session = await ensureTrainingSession();
  } catch (error) {
    if (isNoCurrentTraining(error)) {
      const restored = await restoreCompletedTrainingState();
      if (restored !== null) {
        return restored;
      }
      clearCurrentTraining();
      return emptyTrainingState();
    }
    throw error;
  }
  if (session.stage === "NOTIFIED" && !isLiveNotifiedSession(session)) {
    clearCurrentTraining();
    return emptyTrainingState();
  }
  return await loadAndApplyTrainingState(session.id, session.stage);
}

async function restoreCompletedTrainingState(): Promise<TrainingStateResponse | null> {
  if (!accessToken.value || !activeSessionId.value) {
    return null;
  }
  let restored: TrainingStateResponse;
  try {
    restored = await fetchTrainingState(accessToken.value, activeSessionId.value);
  } catch (error) {
    if (isNoCurrentTraining(error)) {
      forgetActiveSessionId();
      return null;
    }
    throw error;
  }
  if (!shouldRestoreStoredTrainingState(restored)) {
    forgetActiveSessionId();
    return null;
  }
  trainingSession.value = null;
  trainingState.value = restored;
  attempt.value = restored.current_attempt;
  await applyTrainingStateStatus(restored, null);
  return restored;
}

async function loadAndApplyTrainingState(
  sessionId: string,
  sessionStage: string | null,
): Promise<TrainingStateResponse> {
  trainingState.value = await fetchTrainingState(accessToken.value, sessionId);
  attempt.value = trainingState.value.current_attempt;
  await applyTrainingStateStatus(trainingState.value, sessionStage);
  return trainingState.value;
}

async function applyTrainingStateStatus(
  state: TrainingStateResponse,
  sessionStage: string | null,
) {
  if (sessionStage === "NOTIFIED") {
    statusMessage.value = "突击已到达";
    recorderState.value = "idle";
  } else if (state.stage === "COMPLETED") {
    statusMessage.value = "本轮答辩已完成";
    recorderState.value = "uploaded";
    if (shouldFetchTrainingProvenance(state)) {
      await loadProvenance(state.id);
    } else {
      provenance.value = null;
    }
  } else if (state.awaiting !== null && recorderState.value !== "pending") {
    statusMessage.value = stageStatusText(state.awaiting.stage);
    recorderState.value = "idle";
  } else if (state.awaiting === null && recorderState.value !== "pending") {
    statusMessage.value = "处理中";
  }
  syncTrainingStatePolling(state, {
    start: startTrainingStatePolling,
    stop: stopTrainingStatePolling,
  });
}

async function ensureCurrentAttempt(): Promise<VoiceAttemptResponse> {
  if (!accessToken.value) {
    throw new Error("请先登录");
  }
  const state = trainingState.value ?? (await refreshTrainingState());
  if (state.awaiting === null) {
    throw new Error("当前没有等待录音的阶段");
  }
  if (
    attempt.value !== null &&
    attempt.value.stage === state.awaiting.stage &&
    attempt.value.round === state.awaiting.round
  ) {
    return attempt.value;
  }
  attempt.value = await createVoiceAttempt(
    accessToken.value,
    state.id,
    state.awaiting.stage,
    state.awaiting.round,
  );
  return attempt.value;
}

async function restoreTrainingFlow() {
  await refreshTrainingState();
  await restorePendingUpload();
}

async function enableNotifications() {
  clearMessages();
  if (!accessToken.value) {
    errorMessage.value = "请先登录";
    return;
  }
  try {
    notificationStatus.value = notificationStatusText(await setupPushNotifications(accessToken.value));
  } catch (error) {
    errorMessage.value = errorToMessage(error, "通知订阅失败");
  }
}

async function acceptCurrentStrike() {
  clearMessages();
  if (!accessToken.value || trainingSession.value === null) {
    errorMessage.value = "当前没有待接受突击";
    return;
  }
  try {
    trainingSession.value = await acceptTraining(accessToken.value, trainingSession.value.id);
    rememberActiveSessionId(trainingSession.value.id);
    await refreshTrainingState();
  } catch (error) {
    errorMessage.value = errorToMessage(error, "接受突击失败");
  }
}

async function deferCurrentStrike() {
  clearMessages();
  if (!accessToken.value || trainingSession.value === null) {
    errorMessage.value = "当前没有可延期突击";
    return;
  }
  try {
    await deferTraining(accessToken.value, trainingSession.value.id);
    clearCurrentTraining("已延期");
    statusMessage.value = "已延期";
  } catch (error) {
    errorMessage.value = errorToMessage(error, "延期失败");
  }
}

async function abandonCurrentTraining() {
  clearMessages();
  if (!accessToken.value || trainingState.value === null) {
    errorMessage.value = "当前没有可退出训练";
    return;
  }
  try {
    await abandonTraining(accessToken.value, trainingState.value.id);
    transcript.value = null;
    provenance.value = null;
    clearCurrentTraining("已退出本题");
  } catch (error) {
    errorMessage.value = errorToMessage(error, "退出失败");
  }
}

async function startRecording() {
  clearMessages();
  if (!isRecordingSupported()) {
    errorMessage.value = "当前浏览器不支持录音";
    return;
  }
  if (hasPendingUpload.value) {
    errorMessage.value = "请先上传已缓存的录音";
    return;
  }

  const selectedMimeType = selectSupportedMimeType();
  if (selectedMimeType === null) {
    errorMessage.value = "当前浏览器不支持 MediaRecorder";
    return;
  }

  try {
    const stream = await globalThis.navigator.mediaDevices.getUserMedia({ audio: true });
    const currentAttempt = await ensureCurrentAttempt();
    mediaStream = stream;
    chunks = [];
    mediaRecorder = new MediaRecorder(stream, buildRecorderOptions(selectedMimeType));
    mediaRecorder.ondataavailable = (event: BlobEvent) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    };
    mediaRecorder.onerror = () => {
      errorMessage.value = "录音中断";
      stopRecording();
    };
    mediaRecorder.onstop = () => {
      void handleRecordingStopped(currentAttempt.id, selectedMimeType);
    };

    recordingStartedAt = Date.now();
    remainingSeconds.value = MAX_AUDIO_SECONDS;
    recorderState.value = "recording";
    statusMessage.value = "录音中";
    mediaRecorder.start();
    startRecordingTimers();
  } catch (error) {
    stopMediaTracks();
    errorMessage.value = errorToMessage(error, "无法开始录音");
  }
}

function stopRecording() {
  clearRecordingTimers();
  if (mediaRecorder !== null && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
    return;
  }
  stopMediaTracks();
}

async function handleRecordingStopped(attemptId: string, selectedMimeType: string) {
  clearRecordingTimers();
  stopMediaTracks();
  const durationMs = Math.max(Date.now() - recordingStartedAt, 1);
  const mimeType = mediaRecorder?.mimeType || selectedMimeType || "audio/webm";
  const blob = new Blob(chunks, { type: mimeType });
  mediaRecorder = null;
  chunks = [];

  if (durationMs > MAX_AUDIO_DURATION_MS) {
    recorderState.value = "idle";
    errorMessage.value = "录音时长超过限制，请重新录制";
    return;
  }
  if (blob.size <= 0) {
    recorderState.value = "idle";
    errorMessage.value = "录音文件为空";
    return;
  }
  if (blob.size > MAX_AUDIO_BYTES) {
    recorderState.value = "idle";
    errorMessage.value = "录音文件超过大小限制";
    return;
  }

  const checksumSha256 = await sha256Hex(blob);
  const pendingRecord: PendingAudioRecord = {
    attemptId,
    blob,
    mimeType,
    durationMs,
    checksumSha256,
    createdAt: new Date().toISOString(),
  };
  inMemoryPendingRecord = pendingRecord;
  pendingAttemptId.value = attemptId;
  writeLocalValue(PENDING_ATTEMPT_KEY, attemptId);

  try {
    await cachePendingRecord(pendingRecord);
    await uploadPendingRecord(pendingRecord);
  } catch (error) {
    recorderState.value = "pending";
    statusMessage.value = "录音已缓存";
    errorMessage.value = errorToMessage(error, "上传失败，可重试");
  }
}

async function retryPendingUpload() {
  clearMessages();
  const pending = await getPendingRecord();
  if (pending === null) {
    errorMessage.value = "没有可重试的本地录音";
    return;
  }
  try {
    await uploadPendingRecord(pending);
  } catch (error) {
    recorderState.value = "pending";
    errorMessage.value = errorToMessage(error, "上传失败，可重试");
  }
}

async function uploadPendingRecord(record: PendingAudioRecord) {
  if (!accessToken.value) {
    throw new Error("请先登录");
  }
  recorderState.value = "uploading";
  statusMessage.value = "上传中";
  const uploaded = await uploadAttemptAudio(
    accessToken.value,
    record.attemptId,
    record.blob,
    record.durationMs,
    record.checksumSha256,
  );
  attempt.value = uploaded;
  await resumeTraining(accessToken.value, uploaded.session_id, uploaded);
  await forgetPendingRecord(record.attemptId);
  recorderState.value = "uploaded";
  statusMessage.value = "上传成功，处理中";
  await loadPlayback(record.attemptId);
  startTranscriptPolling(record.attemptId);
  await refreshTrainingState();
}

async function loadPlayback(attemptId: string) {
  if (!accessToken.value) {
    return;
  }
  revokePlaybackUrl();
  const audioBlob = await fetchAttemptAudio(accessToken.value, attemptId);
  playbackUrl.value = URL.createObjectURL(audioBlob);
}

async function loadProvenance(sessionId: string) {
  if (!accessToken.value || provenance.value?.session_id === sessionId) {
    return;
  }
  provenance.value = await fetchTrainingProvenance(accessToken.value, sessionId);
}

async function submitDuplicateComplaint() {
  clearMessages();
  if (!accessToken.value || trainingState.value?.stage !== "COMPLETED") {
    errorMessage.value = "Completed session required";
    return;
  }
  const reason = duplicateReason.value.trim();
  if (!reason) {
    errorMessage.value = "Reason required";
    return;
  }

  duplicateSubmitting.value = true;
  try {
    duplicateComplaint.value = await createDuplicateComplaint(
      accessToken.value,
      trainingState.value.id,
      {
        reason,
        duplicate_type: duplicateType.value,
      },
    );
    statusMessage.value = "Duplicate complaint accepted";
  } catch (error) {
    errorMessage.value = errorToMessage(error, "Duplicate complaint failed");
  } finally {
    duplicateSubmitting.value = false;
  }
}

async function startNextRecording() {
  clearMessages();
  stopTranscriptPolling();
  stopTrainingStatePolling();
  revokePlaybackUrl();
  trainingSession.value = null;
  trainingState.value = null;
  attempt.value = null;
  transcript.value = null;
  provenance.value = null;
  duplicateType.value = "other";
  duplicateReason.value = "";
  duplicateComplaint.value = null;
  forgetActiveSessionId();
  recorderState.value = "idle";
  statusMessage.value = "可开始下一条录音";
  await refreshTrainingState();
}

async function restorePendingUpload() {
  const pending = await getPendingRecord();
  if (pending !== null) {
    recorderState.value = "pending";
    statusMessage.value = "发现未上传录音";
  }
}

async function getPendingRecord(): Promise<PendingAudioRecord | null> {
  if (!pendingAttemptId.value) {
    return null;
  }
  if (inMemoryPendingRecord?.attemptId === pendingAttemptId.value) {
    return inMemoryPendingRecord;
  }
  if (!isPendingAudioStoreAvailable()) {
    return null;
  }
  return await loadPendingAudio(pendingAttemptId.value);
}

async function cachePendingRecord(record: PendingAudioRecord) {
  await savePendingAudioBestEffort(record);
}

async function forgetPendingRecord(attemptId: string) {
  pendingAttemptId.value = "";
  removeLocalValue(PENDING_ATTEMPT_KEY);
  inMemoryPendingRecord = null;
  if (!isPendingAudioStoreAvailable()) {
    return;
  }
  await deletePendingAudioBestEffort(attemptId);
}

function startRecordingTimers() {
  countdownTimer = globalThis.setInterval(() => {
    const elapsedSeconds = Math.floor((Date.now() - recordingStartedAt) / 1000);
    remainingSeconds.value = Math.max(MAX_AUDIO_SECONDS - elapsedSeconds, 0);
  }, 250);
  autoStopTimer = globalThis.setTimeout(() => {
    stopRecording();
  }, AUTO_STOP_AUDIO_SECONDS * 1000);
}

function clearRecordingTimers() {
  if (countdownTimer !== undefined) {
    globalThis.clearInterval(countdownTimer);
    countdownTimer = undefined;
  }
  if (autoStopTimer !== undefined) {
    globalThis.clearTimeout(autoStopTimer);
    autoStopTimer = undefined;
  }
}

function startTranscriptPolling(attemptId: string) {
  stopTranscriptPolling();
  void pollTranscript(attemptId);
  transcriptPollTimer = globalThis.setInterval(() => {
    void pollTranscript(attemptId);
  }, 2000);
}

function startTrainingStatePolling() {
  if (trainingStatePollTimer !== undefined) {
    return;
  }
  trainingStatePollTimer = globalThis.setInterval(() => {
    void pollTrainingState();
  }, 2000);
}

async function pollTrainingState() {
  if (!accessToken.value) {
    return;
  }
  try {
    await refreshTrainingState();
  } catch (error) {
    if (trainingState.value?.awaiting === null || recorderState.value === "uploaded") {
      errorMessage.value = errorToMessage(error, "读取训练状态失败");
    }
  }
}

async function pollTranscript(attemptId: string) {
  if (!accessToken.value) {
    return;
  }
  try {
    transcript.value = await fetchAttemptTranscript(accessToken.value, attemptId);
    if (transcript.value.status === "SUCCEEDED" || transcript.value.status === "FAILED") {
      const state = await refreshTrainingState();
      if (!shouldContinueTrainingStatePolling(state)) {
        stopTranscriptPolling();
      }
    }
  } catch (error) {
    if (recorderState.value === "uploaded") {
      errorMessage.value = errorToMessage(error, "读取转写失败");
    }
  }
}

function stopTranscriptPolling() {
  if (transcriptPollTimer !== undefined) {
    globalThis.clearInterval(transcriptPollTimer);
    transcriptPollTimer = undefined;
  }
}

function stopTrainingStatePolling() {
  if (trainingStatePollTimer !== undefined) {
    globalThis.clearInterval(trainingStatePollTimer);
    trainingStatePollTimer = undefined;
  }
}

function seekToSegment(segment: TranscriptSegmentResponse) {
  seekPlaybackToSegment(playbackAudio.value, segment);
}

function stopMediaTracks() {
  if (mediaStream !== null) {
    mediaStream.getTracks().forEach((track) => {
      track.stop();
    });
    mediaStream = null;
  }
}

function revokePlaybackUrl() {
  if (playbackUrl.value) {
    URL.revokeObjectURL(playbackUrl.value);
    playbackUrl.value = "";
  }
}

function clearMessages() {
  errorMessage.value = "";
}

function clearCurrentTraining(message = "等待突击") {
  trainingSession.value = null;
  trainingState.value = null;
  attempt.value = null;
  forgetActiveSessionId();
  statusMessage.value = message;
  recorderState.value = "idle";
}

function errorToMessage(error: unknown, fallback: string): string {
  if (isNoCurrentTraining(error)) {
    return "当前没有待处理突击";
  }
  if (error instanceof ApiError && error.status === 409) {
    return "当前状态暂不可执行";
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

function stageStatusText(stage: string): string {
  if (stage === "FIRST") {
    return "等待第一答";
  }
  if (stage === "FOLLOWUP") {
    return "等待追问回答";
  }
  if (stage === "FINAL") {
    return "等待最终答";
  }
  return "等待录音";
}

function notificationStatusText(result: PushSetupResult): string {
  if (result === "subscribed") {
    return "通知已开启";
  }
  if (result === "denied") {
    return "通知权限未开启";
  }
  if (result === "unconfigured") {
    return "通知服务未配置";
  }
  return "当前浏览器不支持通知";
}

function isNoCurrentTraining(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

function isLiveNotifiedSession(session: TrainingSessionResponse | null): boolean {
  if (session?.stage !== "NOTIFIED" || session.notification_expires_at === null) {
    return false;
  }
  return Date.parse(session.notification_expires_at) > Date.now();
}

function emptyTrainingState(): TrainingStateResponse {
  return {
    id: "",
    thread_id: "",
    stage: "NONE",
    awaiting: null,
    current_attempt: null,
    source_summary: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    completed_at: null,
  };
}

function readSessionValue(key: string): string {
  try {
    return globalThis.sessionStorage?.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeSessionValue(key: string, value: string) {
  try {
    globalThis.sessionStorage?.setItem(key, value);
  } catch {
    return;
  }
}

function removeSessionValue(key: string) {
  try {
    globalThis.sessionStorage?.removeItem(key);
  } catch {
    return;
  }
}

function readLocalValue(key: string): string {
  try {
    return globalThis.localStorage?.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeLocalValue(key: string, value: string) {
  try {
    globalThis.localStorage?.setItem(key, value);
  } catch {
    return;
  }
}

function removeLocalValue(key: string) {
  try {
    globalThis.localStorage?.removeItem(key);
  } catch {
    return;
  }
}

function readRestorableSessionId(): string {
  return restorableSessionIdFromHref(globalThis.location?.href, readLocalValue(ACTIVE_SESSION_KEY));
}

function rememberActiveSessionId(sessionId: string) {
  activeSessionId.value = sessionId;
  writeLocalValue(ACTIVE_SESSION_KEY, sessionId);
}

function forgetActiveSessionId() {
  activeSessionId.value = "";
  removeLocalValue(ACTIVE_SESSION_KEY);
}

function rememberTokenPair(tokens: TokenPair) {
  accessToken.value = tokens.access_token;
  writeSessionValue(ACCESS_TOKEN_KEY, tokens.access_token);
  writeLocalValue(REFRESH_TOKEN_KEY, tokens.refresh_token);
}

function forgetAuthTokens() {
  accessToken.value = "";
  removeSessionValue(ACCESS_TOKEN_KEY);
  removeLocalValue(REFRESH_TOKEN_KEY);
}
</script>

<template>
  <main class="shell">
    <section
      class="panel"
      aria-labelledby="app-title"
    >
      <p class="eyebrow">
        P05 语音答辩
      </p>
      <h1 id="app-title">
        Thinking Coach
      </h1>

      <form
        v-if="!isAuthenticated"
        class="login-form"
        @submit.prevent="submitLogin"
      >
        <label>
          <span>昵称</span>
          <input
            v-model="nickname"
            autocomplete="username"
            required
          >
        </label>
        <label>
          <span>密码</span>
          <input
            v-model="password"
            autocomplete="current-password"
            required
            type="password"
          >
        </label>
        <button type="submit">
          登录
        </button>
      </form>

      <div
        v-else
        class="recorder"
      >
        <div class="status-row">
          <span>{{ statusMessage }}</span>
          <strong v-if="recorderState === 'recording'">
            {{ remainingSeconds }}s
          </strong>
        </div>
        <p
          v-if="notificationStatus"
          class="inline-status"
        >
          {{ notificationStatus }}
        </p>

        <section
          v-if="awaitingInput"
          class="prompt-box"
          aria-label="当前题目"
        >
          <span>{{ awaitingInput.stage }}</span>
          <p>{{ awaitingInput.text }}</p>
          <dl
            v-if="trainingState?.source_summary"
            class="source-summary"
          >
            <div>
              <dt>sources</dt>
              <dd>{{ trainingState.source_summary.source_count }}</dd>
            </div>
            <div>
              <dt>level</dt>
              <dd>{{ trainingState.source_summary.highest_source_level ?? "—" }}</dd>
            </div>
            <div>
              <dt>credential</dt>
              <dd>{{ trainingState.source_summary.credential }}</dd>
            </div>
          </dl>
        </section>

        <div class="controls">
          <button
            type="button"
            @click="enableNotifications"
          >
            开启通知
          </button>
          <button
            :disabled="!canAcceptStrike"
            type="button"
            @click="acceptCurrentStrike"
          >
            接受突击
          </button>
          <button
            :disabled="!canDeferStrike"
            type="button"
            @click="deferCurrentStrike"
          >
            延期
          </button>
          <button
            v-if="recorderState !== 'recording'"
            :disabled="!canStartRecording"
            type="button"
            @click="startRecording"
          >
            开始录音
          </button>
          <button
            v-else
            type="button"
            @click="stopRecording"
          >
            停止录音
          </button>
          <button
            :disabled="!hasPendingUpload"
            type="button"
            @click="retryPendingUpload"
          >
            重试上传
          </button>
          <button
            :disabled="!canAbandonTraining"
            type="button"
            @click="abandonCurrentTraining"
          >
            退出本题
          </button>
          <button
            :disabled="trainingState?.stage !== 'COMPLETED'"
            type="button"
            @click="startNextRecording"
          >
            下一条
          </button>
        </div>

        <dl
          v-if="trainingSession || attempt"
          class="meta"
        >
          <div v-if="trainingSession">
            <dt>session</dt>
            <dd>{{ trainingSession.id }}</dd>
          </div>
          <div v-if="attempt">
            <dt>attempt</dt>
            <dd>{{ attempt.id }}</dd>
          </div>
          <div v-if="attempt">
            <dt>status</dt>
            <dd>{{ attempt.upload_status }}</dd>
          </div>
        </dl>

        <audio
          v-if="playbackUrl"
          ref="playbackAudio"
          :src="playbackUrl"
          class="playback"
          controls
        />

        <section
          v-if="transcript"
          class="transcript"
          aria-labelledby="transcript-title"
        >
          <div class="transcript-header">
            <h2 id="transcript-title">
              转写片段
            </h2>
            <span>{{ transcript.status }}</span>
          </div>
          <dl
            v-if="transcript.metrics"
            class="metric-grid"
          >
            <div>
              <dt>语音</dt>
              <dd>{{ transcript.metrics.effective_speech_ms ?? 0 }}ms</dd>
            </div>
            <div>
              <dt>语速</dt>
              <dd>{{ transcript.metrics.speech_rate_cpm ?? "—" }}</dd>
            </div>
            <div>
              <dt>停顿</dt>
              <dd>{{ Array.isArray(transcript.metrics.long_pauses) ? transcript.metrics.long_pauses.length : 0 }}</dd>
            </div>
          </dl>
          <div class="segment-list">
            <button
              v-for="segment in transcript.segments"
              :key="segment.id"
              class="segment-button"
              type="button"
              @click="seekToSegment(segment)"
            >
              <span>{{ (segment.start_ms / 1000).toFixed(1) }}s</span>
              <strong>{{ segment.corrected_text }}</strong>
            </button>
          </div>
        </section>

        <section
          v-if="provenance"
          class="provenance"
          aria-labelledby="provenance-title"
        >
          <div class="transcript-header">
            <h2 id="provenance-title">
              来源
            </h2>
            <span>{{ provenance.source_summary.credential }}</span>
          </div>
          <div class="source-list">
            <article
              v-for="source in provenance.sources"
              :key="source.id"
            >
              <a
                :href="source.url"
                rel="noreferrer"
                target="_blank"
              >{{ source.title }}</a>
              <span>{{ source.publisher }} · {{ source.level }}</span>
              <ul>
                <li
                  v-for="claim in source.claims"
                  :key="claim.id"
                >
                  <strong>{{ claim.locator }}</strong>
                  <span>{{ claim.excerpt }}</span>
                </li>
              </ul>
            </article>
          </div>
          <form
            class="duplicate-form"
            @submit.prevent="submitDuplicateComplaint"
          >
            <label>
              <span>Duplicate type</span>
              <select v-model="duplicateType">
                <option value="other">
                  Other
                </option>
                <option value="text">
                  Text
                </option>
                <option value="semantic">
                  Semantic
                </option>
                <option value="parameter">
                  Parameter skin
                </option>
                <option value="role">
                  Role skin
                </option>
                <option value="structure">
                  Structure
                </option>
                <option value="answer_skeleton">
                  Answer skeleton
                </option>
                <option value="same_event">
                  Same event
                </option>
              </select>
            </label>
            <label>
              <span>Reason</span>
              <textarea
                v-model="duplicateReason"
                maxlength="1000"
                rows="3"
              />
            </label>
            <button
              :disabled="!canSubmitDuplicateComplaint"
              type="submit"
            >
              Report duplicate
            </button>
            <p
              v-if="duplicateComplaint"
              class="inline-status"
            >
              Accepted, replacement job {{ duplicateComplaint.replacement_job_id }}
            </p>
          </form>
        </section>
      </div>

      <p
        v-if="errorMessage"
        class="error"
        role="alert"
      >
        {{ errorMessage }}
      </p>
    </section>
  </main>
</template>
