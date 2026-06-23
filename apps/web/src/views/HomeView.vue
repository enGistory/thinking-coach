<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { login } from "../api/auth";
import {
  createCurrentTraining,
  createVoiceAttempt,
  fetchAttemptAudio,
  fetchAttemptTranscript,
  fetchTrainingState,
  resumeTraining,
  uploadAttemptAudio,
  type AttemptTranscriptResponse,
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
import { shouldContinueTrainingStatePolling, syncTrainingStatePolling } from "../trainingFlow";

type RecorderState = "idle" | "recording" | "uploading" | "pending" | "uploaded";

const ACCESS_TOKEN_KEY = "thinkingCoachAccessToken";
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
const remainingSeconds = ref(MAX_AUDIO_SECONDS);
const playbackUrl = ref("");
const transcript = ref<AttemptTranscriptResponse | null>(null);
const pendingAttemptId = ref(readLocalValue(PENDING_ATTEMPT_KEY));
const playbackAudio = ref<SeekablePlayback | null>(null);

const isAuthenticated = computed(() => accessToken.value.length > 0);
const awaitingInput = computed(() => trainingState.value?.awaiting ?? null);
const canStartRecording = computed(
  () => isAuthenticated.value && recorderState.value === "idle" && awaitingInput.value !== null,
);
const hasPendingUpload = computed(() => recorderState.value === "pending" && pendingAttemptId.value.length > 0);

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
  if (isAuthenticated.value) {
    statusMessage.value = "已恢复登录状态";
    void restoreTrainingFlow();
  }
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
    accessToken.value = tokens.access_token;
    writeSessionValue(ACCESS_TOKEN_KEY, tokens.access_token);
    statusMessage.value = "登录成功";
    await restoreTrainingFlow();
  } catch (error) {
    errorMessage.value = errorToMessage(error, "登录失败");
  }
}

async function ensureTrainingSession(): Promise<TrainingSessionResponse> {
  if (!accessToken.value) {
    throw new Error("请先登录");
  }
  if (trainingSession.value !== null) {
    return trainingSession.value;
  }
  trainingSession.value = await createCurrentTraining(accessToken.value);
  return trainingSession.value;
}

async function refreshTrainingState(): Promise<TrainingStateResponse> {
  if (!accessToken.value) {
    throw new Error("请先登录");
  }
  const session = await ensureTrainingSession();
  trainingState.value = await fetchTrainingState(accessToken.value, session.id);
  attempt.value = trainingState.value.current_attempt;
  if (trainingState.value.stage === "COMPLETED") {
    statusMessage.value = "本轮答辩已完成";
    recorderState.value = "uploaded";
  } else if (trainingState.value.awaiting !== null && recorderState.value !== "pending") {
    statusMessage.value = stageStatusText(trainingState.value.awaiting.stage);
    recorderState.value = "idle";
  } else if (trainingState.value.awaiting === null && recorderState.value !== "pending") {
    statusMessage.value = "处理中";
  }
  syncTrainingStatePolling(trainingState.value, {
    start: startTrainingStatePolling,
    stop: stopTrainingStatePolling,
  });
  return trainingState.value;
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

async function startNextRecording() {
  clearMessages();
  stopTranscriptPolling();
  stopTrainingStatePolling();
  revokePlaybackUrl();
  trainingSession.value = null;
  trainingState.value = null;
  attempt.value = null;
  transcript.value = null;
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

function errorToMessage(error: unknown, fallback: string): string {
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

        <section
          v-if="awaitingInput"
          class="prompt-box"
          aria-label="当前题目"
        >
          <span>{{ awaitingInput.stage }}</span>
          <p>{{ awaitingInput.text }}</p>
        </section>

        <div class="controls">
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
