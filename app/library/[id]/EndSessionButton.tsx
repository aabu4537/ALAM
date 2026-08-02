"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import styles from "./hub.module.css";

export function EndSessionButton({
  mediaItemId,
  readingSessionId,
}: {
  mediaItemId: string;
  readingSessionId: string;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function end(status: "completed" | "abandoned") {
    setPending(true);
    try {
      await fetch(
        `/books/${mediaItemId}/reading-sessions/${readingSessionId}/end?end_status=${status}`,
        { method: "POST" },
      );
      router.refresh();
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={styles.endSession}>
      <button type="button" onClick={() => end("completed")} disabled={pending}>
        Mark finished
      </button>
      <button type="button" onClick={() => end("abandoned")} disabled={pending}>
        Set aside
      </button>
    </div>
  );
}
