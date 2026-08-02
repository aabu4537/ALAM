// A recording that fails to upload is not lost — IndexedDB holds the blob
// until a retry succeeds. Deliberately not a full offline/background-sync
// PWA (no service worker): just "don't lose the recording if the request
// fails," which is what M2's milestone note deferred to this session.
const DB_NAME = "alam-capture-queue";
const STORE = "pending-captures";

export interface QueuedCapture {
  id: string;
  mediaItemId: string;
  structureUnitId: string;
  blob: Blob;
  createdAt: number;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(STORE, { keyPath: "id" });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export async function enqueueCapture(entry: QueuedCapture): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(entry);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

export async function listQueuedCaptures(mediaItemId: string): Promise<QueuedCapture[]> {
  const db = await openDb();
  const all = await new Promise<QueuedCapture[]>((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const request = tx.objectStore(STORE).getAll();
    request.onsuccess = () => resolve(request.result as QueuedCapture[]);
    request.onerror = () => reject(request.error);
  });
  db.close();
  return all.filter((entry) => entry.mediaItemId === mediaItemId);
}

export async function removeQueuedCapture(id: string): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}
