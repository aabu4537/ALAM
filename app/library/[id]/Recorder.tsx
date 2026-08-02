"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./hub.module.css";
import { enqueueCapture, listQueuedCaptures, removeQueuedCapture } from "@/lib/captureQueue";
import type { QueuedCapture } from "@/lib/captureQueue";
import type { Capture } from "@/lib/types";

type Phase = "idle" | "recording" | "uploading" | "queued" | "error";

async function upload(
  mediaItemId: string,
  entry: Pick<QueuedCapture, "structureUnitId" | "blob">,
): Promise<Capture> {
  const response = await fetch(
    `/books/${mediaItemId}/captures?structure_unit_id=${entry.structureUnitId}`,
    { method: "POST", headers: { "Content-Type": "audio/webm" }, body: entry.blob },
  );
  if (!response.ok) {
    throw new Error(`upload failed (${response.status})`);
  }
  return (await response.json()) as Capture;
}

export function Recorder({
  mediaItemId,
  structureUnitId,
  label,
  onCaptured,
}: {
  mediaItemId: string;
  structureUnitId: string;
  label: string;
  onCaptured?: (capture: Capture) => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [pendingCount, setPendingCount] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  useEffect(() => {
    let cancelled = false;
    async function flush() {
      const queued = await listQueuedCaptures(mediaItemId);
      if (cancelled) return;
      setPendingCount(queued.length);
      for (const entry of queued) {
        try {
          const capture = await upload(mediaItemId, entry);
          await removeQueuedCapture(entry.id);
          if (!cancelled) {
            setPendingCount((count) => Math.max(0, count - 1));
            onCaptured?.(capture);
          }
        } catch {
          // Still queued — will retry on next mount/flush.
        }
      }
    }
    void flush();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mediaItemId]);

  async function startRecording() {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        void handleStopped();
      };
      mediaRecorderRef.current = recorder;
      recorder.start();
      setPhase("recording");
    } catch {
      setError("Couldn't access the microphone.");
      setPhase("error");
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
  }

  async function handleStopped() {
    const blob = new Blob(chunksRef.current, { type: "audio/webm" });
    const entry: QueuedCapture = {
      id: crypto.randomUUID(),
      mediaItemId,
      structureUnitId,
      blob,
      createdAt: Date.now(),
    };
    await enqueueCapture(entry);
    setPhase("uploading");
    try {
      const capture = await upload(mediaItemId, entry);
      await removeQueuedCapture(entry.id);
      setPhase("idle");
      onCaptured?.(capture);
    } catch {
      setPhase("queued");
      setPendingCount((count) => count + 1);
    }
  }

  return (
    <div className={styles.recorder}>
      <p className={styles.recorderLabel}>Reflect on {label}</p>
      {phase === "recording" ? (
        <button type="button" className={styles.recordButtonActive} onClick={stopRecording}>
          ● Stop
        </button>
      ) : (
        <button
          type="button"
          className={styles.recordButton}
          onClick={startRecording}
          disabled={phase === "uploading"}
        >
          {phase === "uploading" ? "Saving…" : "Record a reflection"}
        </button>
      )}
      {phase === "queued" ? (
        <p className={styles.recorderNote}>
          Saved on this device — couldn&apos;t reach the server yet. It&apos;ll retry next time
          this page loads.
        </p>
      ) : null}
      {pendingCount > 0 && phase !== "queued" ? (
        <p className={styles.recorderNote}>
          {pendingCount} earlier reflection{pendingCount === 1 ? "" : "s"} still uploading…
        </p>
      ) : null}
      {error ? <p className={styles.error}>{error}</p> : null}
    </div>
  );
}
