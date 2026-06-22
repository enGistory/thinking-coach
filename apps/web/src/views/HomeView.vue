<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { login } from "../api/auth";
import {
  createCurrentTraining,
  createVoiceAttempt,
  fetchAttemptAudio,
  uploadAttemptAudio,
  type TrainingSessionResponse,
  type VoiceAttemptResponse,
} from "../api/training";
import { sha256Hex } from "../audio/checksum";
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

type RecorderState = "idle" | "recording" | "uploading" | "pending" | "uploaded";

const ACCESS_TOKEN_KEY = "thinkingCoachAccessToken";
const PENDING_ATTEMPT_KEY = "thinkingCoachPendingAttemptId";

const nickname = ref("");
const password = ref("");
const accessToken = ref(readSessionValue(ACCESS_TOKEN_KEY));
const trainingSession = ref<TrainingSessionResponse | null>(null);
const attempt = ref<VoiceAttemptResponse | null>(null);
const recorderState = ref<RecorderState>("idle");
const statusMessage = ref("等待登录");
const errorMessage = ref("");
const remainingSeconds = ref(MAX_AUDIO_SECONDS);
const playbackUrl = ref("");
const pendingAttemptId = ref(readLocalValue(PENDING_ATTEMPT_KEY));

const isAuthenticated = computed(() => accessToken.value.length > 0);
const canStartRecording = computed(
  () => isAuthenticated.value && recorderState.value === "idle" && attempt.value?.upload_status !== "UPLOADED",
);
const hasPendingUpload = computed(() => recorderState.value === "pending" && pendingAttemptId.value.length > 0);

let mediaRecorder: MediaRecorder | null = null;
let mediaStream: MediaStream | null = null;
let chunks: Blob[] = [];
let recordingStartedAt = 0;
let countdownTimer: number | undefined;
let autoStopTimer: number | undefined;
let inMemoryPendingRecord: PendingAudioRecord | null = null;

onMounted(() => {
  if (isAuthenticated.value) {
    statusMessage.value = "已恢复登录状态";
    void restorePendingUpload();
  }
});

onBeforeUnmount(() => {
  clearRecordingTimers();
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
    await ensureTrainingSession();
    await restorePendingUpload();
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
  statusMessage.value = "录音会话已就绪";
  return trainingSession.value;
}

async function ensureFirstAttempt(): Promise<VoiceAttemptResponse> {
  if (!accessToken.value) {
    throw new Error("请先登录");
  }
  if (attempt.value !== null) {
    return attempt.value;
  }
  const session = await ensureTrainingSession();
  attempt.value = await createVoiceAttempt(accessToken.value, session.id);
  return attempt.value;
}

async function startRecording() {
  clearMessages();
  if (!isRecordingSupported()) {
    errorMessage.value = "当前浏览器不支持录音";
    return;
  }
  if (hasPendingUpload.value) {
    errorMessage.value = "请先上传已缓存的第一答";
    return;
  }

  const selectedMimeType = selectSupportedMimeType();
  if (selectedMimeType === null) {
    errorMessage.value = "当前浏览器不支持 MediaRecorder";
    return;
  }

  try {
    const stream = await globalThis.navigator.mediaDevices.getUserMedia({ audio: true });
    const currentAttempt = await ensureFirstAttempt();
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
  await forgetPendingRecord(record.attemptId);
  recorderState.value = "uploaded";
  statusMessage.value = "上传成功";
  await loadPlayback(record.attemptId);
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
  revokePlaybackUrl();
  trainingSession.value = null;
  attempt.value = null;
  recorderState.value = "idle";
  statusMessage.value = "可开始下一条录音";
  await ensureTrainingSession();
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
        P03 语音切片
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
            :disabled="recorderState !== 'uploaded'"
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
          :src="playbackUrl"
          class="playback"
          controls
        />
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
