const DB_NAME = "thinking-coach-audio";
const STORE_NAME = "pending-audio";
const DB_VERSION = 1;

export interface PendingAudioRecord {
  attemptId: string;
  blob: Blob;
  mimeType: string;
  durationMs: number;
  checksumSha256: string;
  createdAt: string;
}

export function isPendingAudioStoreAvailable(): boolean {
  return typeof globalThis.indexedDB !== "undefined";
}

export async function savePendingAudio(record: PendingAudioRecord): Promise<void> {
  const db = await openDatabase();
  try {
    await requestToPromise(db.transaction(STORE_NAME, "readwrite").objectStore(STORE_NAME).put(record));
  } finally {
    db.close();
  }
}

export async function loadPendingAudio(attemptId: string): Promise<PendingAudioRecord | null> {
  const db = await openDatabase();
  try {
    const result = await requestToPromise(
      db.transaction(STORE_NAME, "readonly").objectStore(STORE_NAME).get(attemptId),
    );
    return isPendingAudioRecord(result) ? result : null;
  } finally {
    db.close();
  }
}

export async function deletePendingAudio(attemptId: string): Promise<void> {
  const db = await openDatabase();
  try {
    await requestToPromise(
      db.transaction(STORE_NAME, "readwrite").objectStore(STORE_NAME).delete(attemptId),
    );
  } finally {
    db.close();
  }
}

export async function clearPendingAudio(): Promise<void> {
  const db = await openDatabase();
  try {
    await requestToPromise(db.transaction(STORE_NAME, "readwrite").objectStore(STORE_NAME).clear());
  } finally {
    db.close();
  }
}

export async function savePendingAudioBestEffort(
  record: PendingAudioRecord,
  save: (record: PendingAudioRecord) => Promise<void> = savePendingAudio,
): Promise<boolean> {
  if (!isPendingAudioStoreAvailable()) {
    return false;
  }
  try {
    await save(record);
    return true;
  } catch {
    return false;
  }
}

export async function deletePendingAudioBestEffort(
  attemptId: string,
  remove: (attemptId: string) => Promise<void> = deletePendingAudio,
): Promise<boolean> {
  if (!isPendingAudioStoreAvailable()) {
    return false;
  }
  try {
    await remove(attemptId);
    return true;
  } catch {
    return false;
  }
}

export async function clearPendingAudioBestEffort(
  clear: () => Promise<void> = clearPendingAudio,
): Promise<boolean> {
  if (!isPendingAudioStoreAvailable()) {
    return false;
  }
  try {
    await clear();
    return true;
  } catch {
    return false;
  }
}

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!isPendingAudioStoreAvailable()) {
      reject(new Error("当前浏览器不支持本地音频缓存"));
      return;
    }

    const request = globalThis.indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "attemptId" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("打开本地音频缓存失败"));
  });
}

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error("本地音频缓存操作失败"));
  });
}

function isPendingAudioRecord(value: unknown): value is PendingAudioRecord {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<PendingAudioRecord>;
  return (
    typeof candidate.attemptId === "string" &&
    candidate.blob instanceof Blob &&
    typeof candidate.mimeType === "string" &&
    typeof candidate.durationMs === "number" &&
    typeof candidate.checksumSha256 === "string" &&
    typeof candidate.createdAt === "string"
  );
}
