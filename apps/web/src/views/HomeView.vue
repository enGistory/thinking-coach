<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { login, refreshAuth, type TokenPair } from "../api/auth";
import { ApiError } from "../api/client";
import {
  abandonTraining,
  acceptTraining,
  createDuplicateComplaint,
  createTrainingAppeal,
  deferTraining,
  fetchCurrentTraining,
  createVoiceAttempt,
  fetchAttemptAudio,
  fetchAttemptTranscript,
  fetchTrainingAppeals,
  fetchTrainingProvenance,
  fetchTrainingReport,
  fetchTrainingState,
  resumeTraining,
  uploadAttemptAudio,
  type AppealType,
  type AttemptTranscriptResponse,
  type DuplicateComplaintResponse,
  type DuplicateType,
  type TrainingAppealStatusResponse,
  type TrainingProvenanceResponse,
  type TrainingReportResponse,
  type TranscriptSegmentResponse,
  type TrainingSessionResponse,
  type TrainingStateResponse,
  type VoiceAttemptResponse,
} from "../api/training";
import {
  deleteAccount,
  deleteTraining,
  exportPersonalData,
  fetchDeletionStatus,
  fetchWeeklyReports,
  type AccountDeletionResponse,
  type DeletionStatusResponse,
  type WeeklyReportResponse,
} from "../api/privacy";
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
  clearPendingAudioBestEffort,
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
type AppealTargetKind = "issue" | "defect" | "segment" | "source" | "claim";

interface AppealTargetOption {
  kind: AppealTargetKind;
  value: string;
  label: string;
}

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
const trainingReport = ref<TrainingReportResponse | null>(null);
const trainingAppeals = ref<TrainingAppealStatusResponse[]>([]);
const weeklyReports = ref<WeeklyReportResponse[]>([]);
const duplicateType = ref<DuplicateType>("other");
const duplicateReason = ref("");
const duplicateComplaint = ref<DuplicateComplaintResponse | null>(null);
const duplicateSubmitting = ref(false);
const appealType = ref<AppealType>("evaluation");
const appealTargetValue = ref("");
const appealReason = ref("");
const appealSubmitting = ref(false);
const privacyBusy = ref(false);
const accountDeletion = ref<AccountDeletionResponse | null>(null);
const deletionStatusRequestId = ref("");
const deletionStatusProof = ref("");
const deletionStatus = ref<DeletionStatusResponse | null>(null);
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
const canSubmitAppeal = computed(
  () =>
    trainingState.value?.stage === "COMPLETED" &&
    selectedAppealTarget.value !== null &&
    appealReason.value.trim().length > 0 &&
    !appealSubmitting.value,
);
const appealTargetOptions = computed<AppealTargetOption[]>(() => {
  if (appealType.value === "evaluation") {
    return (trainingReport.value?.issues ?? []).map((issue) => ({
      kind: "issue",
      value: issue.id,
      label: `${issue.category} / ${issue.code} / ${issue.quote}`,
    }));
  }
  if (appealType.value === "defect_classification") {
    return (trainingReport.value?.issues ?? []).map((issue) => ({
      kind: "defect",
      value: issue.code,
      label: `${issue.code} / ${issue.quote}`,
    }));
  }
  if (appealType.value === "transcript") {
    return (transcript.value?.segments ?? []).map((segment) => ({
      kind: "segment",
      value: segment.id,
      label: `${(segment.start_ms / 1000).toFixed(1)}s / ${segment.corrected_text}`,
    }));
  }
  return (provenance.value?.sources ?? []).flatMap((source) => [
    {
      kind: "source" as const,
      value: source.id,
      label: `${source.publisher} / ${source.title}`,
    },
    ...source.claims.map((claim) => ({
      kind: "claim" as const,
      value: claim.id,
      label: `${claim.locator} / ${claim.excerpt}`,
    })),
  ]);
});
const selectedAppealTarget = computed(() => {
  return (
    appealTargetOptions.value.find((option) => option.value === appealTargetValue.value) ??
    appealTargetOptions.value[0] ??
    null
  );
});

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
    await loadReportAndAppeals(state.id);
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
  await loadWeeklyReports();
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

async function loadReportAndAppeals(sessionId: string) {
  if (!accessToken.value) {
    return;
  }
  try {
    trainingReport.value = await fetchTrainingReport(accessToken.value, sessionId);
    trainingAppeals.value = trainingReport.value.appeals;
  } catch (error) {
    if (!isNoCurrentTraining(error)) {
      errorMessage.value = errorToMessage(error, "读取报告失败");
    }
  }
  try {
    trainingAppeals.value = await fetchTrainingAppeals(accessToken.value, sessionId);
  } catch {
    return;
  }
}

async function loadWeeklyReports() {
  if (!accessToken.value) {
    return;
  }
  try {
    weeklyReports.value = await fetchWeeklyReports(accessToken.value);
  } catch {
    weeklyReports.value = [];
  }
}

async function submitDuplicateComplaint() {
  clearMessages();
  if (!accessToken.value || trainingState.value?.stage !== "COMPLETED") {
    errorMessage.value = "需要已完成的训练";
    return;
  }
  const reason = duplicateReason.value.trim();
  if (!reason) {
    errorMessage.value = "请填写原因";
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
    statusMessage.value = "重复投诉已受理";
  } catch (error) {
    errorMessage.value = errorToMessage(error, "重复投诉失败");
  } finally {
    duplicateSubmitting.value = false;
  }
}

async function submitTrainingAppeal() {
  clearMessages();
  if (!accessToken.value || trainingState.value?.stage !== "COMPLETED") {
    errorMessage.value = "需要已完成的训练";
    return;
  }
  const target = selectedAppealTarget.value;
  if (target === null) {
    errorMessage.value = "请选择申诉对象";
    return;
  }
  const reason = appealReason.value.trim();
  if (!reason) {
    errorMessage.value = "请填写原因";
    return;
  }

  appealSubmitting.value = true;
  try {
    await createTrainingAppeal(accessToken.value, trainingState.value.id, {
      type: appealType.value,
      reason,
      issue_id: target.kind === "issue" ? target.value : null,
      defect_code: target.kind === "defect" ? target.value : null,
      segment_id: target.kind === "segment" ? target.value : null,
      source_id: target.kind === "source" ? target.value : null,
      claim_id: target.kind === "claim" ? target.value : null,
    });
    appealReason.value = "";
    trainingAppeals.value = await fetchTrainingAppeals(accessToken.value, trainingState.value.id);
    statusMessage.value = "申诉已提交";
  } catch (error) {
    errorMessage.value = errorToMessage(error, "提交申诉失败");
  } finally {
    appealSubmitting.value = false;
  }
}

async function downloadPersonalData() {
  clearMessages();
  if (!accessToken.value) {
    errorMessage.value = "请先登录";
    return;
  }
  privacyBusy.value = true;
  try {
    const payload = await exportPersonalData(accessToken.value);
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = globalThis.document.createElement("a");
    link.href = url;
    link.download = `thinking-coach-export-${payload.generated_at.slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    statusMessage.value = "导出文件已生成";
  } catch (error) {
    errorMessage.value = errorToMessage(error, "导出失败");
  } finally {
    privacyBusy.value = false;
  }
}

async function deleteCurrentTraining() {
  clearMessages();
  if (!accessToken.value || !trainingState.value?.id) {
    errorMessage.value = "当前没有可删除的训练";
    return;
  }
  if (!globalThis.confirm("删除本次训练及其音频、转写和报告数据？")) {
    return;
  }
  privacyBusy.value = true;
  try {
    await deleteTraining(accessToken.value, trainingState.value.id);
    await forgetAllPendingAudio();
    transcript.value = null;
    provenance.value = null;
    trainingReport.value = null;
    trainingAppeals.value = [];
    clearCurrentTraining("本次训练已删除");
  } catch (error) {
    errorMessage.value = errorToMessage(error, "删除训练失败");
  } finally {
    privacyBusy.value = false;
  }
}

async function requestAccountDeletion() {
  clearMessages();
  if (!accessToken.value) {
    errorMessage.value = "请先登录";
    return;
  }
  if (!globalThis.confirm("禁用账号并排队删除全部个人数据？")) {
    return;
  }
  privacyBusy.value = true;
  try {
    accountDeletion.value = await deleteAccount(accessToken.value);
    deletionStatusRequestId.value = accountDeletion.value.request_id;
    deletionStatusProof.value = accountDeletion.value.proof_code;
    await forgetAllPendingAudio();
    forgetAuthTokens();
    clearCurrentTraining("账号删除已排队");
    statusMessage.value = "账号删除已排队";
  } catch (error) {
    errorMessage.value = errorToMessage(error, "删除账号失败");
  } finally {
    privacyBusy.value = false;
  }
}

async function checkDeletionStatus() {
  clearMessages();
  if (!deletionStatusRequestId.value || !deletionStatusProof.value) {
    errorMessage.value = "请填写请求 ID 和证明码";
    return;
  }
  try {
    deletionStatus.value = await fetchDeletionStatus(
      deletionStatusRequestId.value,
      deletionStatusProof.value,
    );
  } catch (error) {
    errorMessage.value = errorToMessage(error, "查询删除进度失败");
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
  trainingReport.value = null;
  trainingAppeals.value = [];
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

async function forgetAllPendingAudio() {
  pendingAttemptId.value = "";
  removeLocalValue(PENDING_ATTEMPT_KEY);
  inMemoryPendingRecord = null;
  if (!isPendingAudioStoreAvailable()) {
    return;
  }
  await clearPendingAudioBestEffort();
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
  transcript.value = null;
  provenance.value = null;
  trainingReport.value = null;
  trainingAppeals.value = [];
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

function appealTypeText(type: string): string {
  if (type === "evaluation") {
    return "评审";
  }
  if (type === "defect_classification") {
    return "缺陷分类";
  }
  if (type === "transcript") {
    return "转写";
  }
  if (type === "source") {
    return "来源";
  }
  if (type === "duplicate") {
    return "重复题";
  }
  return type;
}

function appealStatusText(status: string): string {
  if (status === "OPEN") {
    return "待处理";
  }
  if (status === "ACCEPTED") {
    return "已接受";
  }
  if (status === "REJECTED") {
    return "已驳回";
  }
  return status;
}

function deletionStatusText(status: string | null | undefined): string {
  if (status === "QUEUED") {
    return "已排队";
  }
  if (status === "RUNNING") {
    return "删除中";
  }
  if (status === "SUCCEEDED") {
    return "已完成";
  }
  if (status === "FAILED") {
    return "失败";
  }
  return "等待处理";
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
              <dt>来源数</dt>
              <dd>{{ trainingState.source_summary.source_count }}</dd>
            </div>
            <div>
              <dt>等级</dt>
              <dd>{{ trainingState.source_summary.highest_source_level ?? "—" }}</dd>
            </div>
            <div>
              <dt>凭证</dt>
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
          <button
            type="button"
            @click="loadWeeklyReports"
          >
            刷新周报
          </button>
          <button
            :disabled="privacyBusy"
            type="button"
            @click="downloadPersonalData"
          >
            导出数据
          </button>
          <button
            :disabled="privacyBusy || !trainingState?.id"
            type="button"
            @click="deleteCurrentTraining"
          >
            删除本次训练
          </button>
          <button
            :disabled="privacyBusy"
            type="button"
            @click="requestAccountDeletion"
          >
            删除账号
          </button>
        </div>

        <dl
          v-if="trainingSession || attempt"
          class="meta"
        >
          <div v-if="trainingSession">
            <dt>会话</dt>
            <dd>{{ trainingSession.id }}</dd>
          </div>
          <div v-if="attempt">
            <dt>回答</dt>
            <dd>{{ attempt.id }}</dd>
          </div>
          <div v-if="attempt">
            <dt>状态</dt>
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
          v-if="trainingReport"
          class="report"
          aria-labelledby="report-title"
        >
          <div class="transcript-header">
            <h2 id="report-title">
              本次报告
            </h2>
            <span>{{ trainingReport.total_score }}</span>
          </div>
          <dl class="metric-grid">
            <div>
              <dt>逻辑</dt>
              <dd>{{ trainingReport.logic_score }}</dd>
            </div>
            <div>
              <dt>口语</dt>
              <dd>{{ trainingReport.expression_score }}</dd>
            </div>
            <div>
              <dt>应变</dt>
              <dd>{{ trainingReport.adaptability_score }}</dd>
            </div>
          </dl>
          <p class="inline-status">
            {{ trainingReport.summary }}
          </p>
          <div class="source-list">
            <article
              v-for="issue in trainingReport.issues"
              :key="issue.id"
            >
              <strong>{{ issue.category }} / {{ issue.code }}</strong>
              <span>{{ issue.quote }} ({{ (issue.start_ms / 1000).toFixed(1) }}s)</span>
              <span>{{ issue.explanation }}</span>
            </article>
          </div>
          <form
            class="duplicate-form"
            @submit.prevent="submitTrainingAppeal"
          >
            <label>
              <span>申诉类型</span>
              <select v-model="appealType">
                <option value="evaluation">
                  评审误解
                </option>
                <option value="defect_classification">
                  缺陷分类
                </option>
                <option value="transcript">
                  转写错误
                </option>
                <option value="source">
                  来源错误
                </option>
              </select>
            </label>
            <label>
              <span>申诉对象</span>
              <select v-model="appealTargetValue">
                <option
                  v-for="option in appealTargetOptions"
                  :key="`${option.kind}:${option.value}`"
                  :value="option.value"
                >
                  {{ option.label }}
                </option>
              </select>
            </label>
            <label>
              <span>原因</span>
              <textarea
                v-model="appealReason"
                maxlength="1000"
                rows="3"
              />
            </label>
            <button
              :disabled="!canSubmitAppeal"
              type="submit"
            >
              提交申诉
            </button>
          </form>
          <div
            v-if="trainingAppeals.length"
            class="source-list"
          >
            <article
              v-for="appeal in trainingAppeals"
              :key="appeal.id"
            >
              <strong>{{ appealTypeText(appeal.type) }} / {{ appealStatusText(appeal.status) }}</strong>
              <span>{{ appeal.reason }}</span>
              <span v-if="appeal.resolution">{{ appeal.resolution }}</span>
            </article>
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
              <span>重复类型</span>
              <select v-model="duplicateType">
                <option value="other">
                  其他
                </option>
                <option value="text">
                  原题重复
                </option>
                <option value="semantic">
                  语义重复
                </option>
                <option value="parameter">
                  数字换皮
                </option>
                <option value="role">
                  角色换皮
                </option>
                <option value="structure">
                  结构换皮
                </option>
                <option value="answer_skeleton">
                  答案骨架重复
                </option>
                <option value="same_event">
                  同一事件
                </option>
              </select>
            </label>
            <label>
              <span>原因</span>
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
              提交重复投诉
            </button>
            <p
              v-if="duplicateComplaint"
              class="inline-status"
            >
              已受理，补题任务 {{ duplicateComplaint.replacement_job_id }}
            </p>
          </form>
        </section>

        <section
          v-if="weeklyReports.length"
          class="weekly"
          aria-labelledby="weekly-title"
        >
          <div class="transcript-header">
            <h2 id="weekly-title">
              周报
            </h2>
            <span>{{ weeklyReports[0]?.week_start }} - {{ weeklyReports[0]?.week_end }}</span>
          </div>
          <div class="source-list">
            <article
              v-for="report in weeklyReports"
              :key="report.id"
            >
              <strong>{{ report.week_start }} - {{ report.week_end }}</strong>
              <span>{{ report.summary }}</span>
              <span>完成训练 {{ report.metrics.completed_session_count ?? 0 }}</span>
            </article>
          </div>
        </section>

        <section
          v-if="accountDeletion || deletionStatusRequestId"
          class="privacy-status"
          aria-labelledby="privacy-title"
        >
          <div class="transcript-header">
            <h2 id="privacy-title">
              删除进度
            </h2>
            <span>{{ deletionStatusText(deletionStatus?.status ?? accountDeletion?.status) }}</span>
          </div>
          <dl
            v-if="accountDeletion"
            class="meta"
          >
            <div>
              <dt>请求</dt>
              <dd>{{ accountDeletion.request_id }}</dd>
            </div>
            <div>
              <dt>证明码</dt>
              <dd>{{ accountDeletion.proof_code }}</dd>
            </div>
          </dl>
          <form
            class="duplicate-form"
            @submit.prevent="checkDeletionStatus"
          >
            <label>
              <span>请求 ID</span>
              <input
                v-model="deletionStatusRequestId"
                autocomplete="off"
                spellcheck="false"
              >
            </label>
            <label>
              <span>证明码</span>
              <input
                v-model="deletionStatusProof"
                type="password"
                autocomplete="off"
                spellcheck="false"
              >
            </label>
            <button type="submit">
              查询进度
            </button>
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
