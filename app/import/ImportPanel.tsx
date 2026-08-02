"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import styles from "./import.module.css";
import type { EpubPreview, ImportDiff } from "@/lib/types";

type Tab = "goodreads" | "epub";

export function ImportPanel() {
  const [tab, setTab] = useState<Tab>("goodreads");

  return (
    <div>
      <div className={styles.tabs}>
        <button
          type="button"
          className={tab === "goodreads" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
          onClick={() => setTab("goodreads")}
        >
          Goodreads export
        </button>
        <button
          type="button"
          className={tab === "epub" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
          onClick={() => setTab("epub")}
        >
          EPUB
        </button>
      </div>
      {tab === "goodreads" ? <GoodreadsImport /> : <EpubImport />}
    </div>
  );
}

function GoodreadsImport() {
  const [csvText, setCsvText] = useState<string | null>(null);
  const [diff, setDiff] = useState<ImportDiff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [committed, setCommitted] = useState(false);

  async function handleFile(file: File) {
    const text = await file.text();
    setCsvText(text);
    setDiff(null);
    setCommitted(false);
    setError(null);
    setPending(true);
    try {
      const response = await fetch("/imports/goodreads/preview", {
        method: "POST",
        headers: { "Content-Type": "text/csv" },
        body: text,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.detail ?? `Preview failed (${response.status}).`);
        return;
      }
      setDiff((await response.json()) as ImportDiff);
    } catch {
      setError("Couldn't reach the server.");
    } finally {
      setPending(false);
    }
  }

  async function handleCommit() {
    if (!csvText) return;
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/imports/goodreads/commit", {
        method: "POST",
        headers: { "Content-Type": "text/csv" },
        body: csvText,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.detail ?? `Import failed (${response.status}).`);
        return;
      }
      setCommitted(true);
    } catch {
      setError("Couldn't reach the server.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.dropzone}>
        <p>Upload your Goodreads library export CSV.</p>
        <input
          className={styles.fileInput}
          type="file"
          accept=".csv,text/csv"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleFile(file);
          }}
        />
      </div>
      {error ? <p className={styles.error}>{error}</p> : null}
      {diff ? (
        <div className={styles.diff}>
          <div className={styles.diffSection}>
            <p className={styles.diffSectionTitle}>New ({diff.to_create.length})</p>
            {diff.to_create.map((book) => (
              <p key={book.dedupe_key} className={styles.diffRow}>
                {book.title} — {book.author}
              </p>
            ))}
          </div>
          <div className={styles.diffSection}>
            <p className={styles.diffSectionTitle}>Updated ({diff.to_update.length})</p>
            {diff.to_update.map((book) => (
              <p key={book.id} className={styles.diffRow}>
                {book.title} ({book.changes.length} field{book.changes.length === 1 ? "" : "s"})
              </p>
            ))}
          </div>
          <p className={styles.diffSectionTitle}>
            {diff.unchanged_count} unchanged, {diff.skipped.length} skipped
          </p>
          {committed ? (
            <p className={styles.success}>Imported. Head back to your library to see it.</p>
          ) : (
            <button type="button" className={styles.action} onClick={handleCommit} disabled={pending}>
              {pending ? "Importing…" : "Confirm import"}
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}

function EpubImport() {
  const router = useRouter();
  const [bytes, setBytes] = useState<ArrayBuffer | null>(null);
  const [preview, setPreview] = useState<EpubPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function handleFile(file: File) {
    const buffer = await file.arrayBuffer();
    setBytes(buffer);
    setPreview(null);
    setError(null);
    setPending(true);
    try {
      const response = await fetch("/books/epub/preview", {
        method: "POST",
        headers: { "Content-Type": "application/epub+zip" },
        body: buffer,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.detail ?? `Preview failed (${response.status}).`);
        return;
      }
      setPreview((await response.json()) as EpubPreview);
    } catch {
      setError("Couldn't reach the server.");
    } finally {
      setPending(false);
    }
  }

  async function handleCommit() {
    if (!bytes) return;
    setPending(true);
    setError(null);
    try {
      const response = await fetch("/books/epub/commit", {
        method: "POST",
        headers: { "Content-Type": "application/epub+zip" },
        body: bytes,
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.detail ?? `Import failed (${response.status}).`);
        return;
      }
      const structure = (await response.json()) as { media_item_id: string };
      router.push(`/library/${structure.media_item_id}/verify`);
    } catch {
      setError("Couldn't reach the server.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className={styles.panel}>
      <div className={styles.dropzone}>
        <p>Upload an EPUB. You&apos;ll confirm its chapter structure next.</p>
        <input
          className={styles.fileInput}
          type="file"
          accept=".epub,application/epub+zip"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void handleFile(file);
          }}
        />
      </div>
      {error ? <p className={styles.error}>{error}</p> : null}
      {preview ? (
        <div className={styles.diff}>
          <p className={styles.diffSectionTitle}>
            {preview.title ?? "Untitled"} — {preview.author ?? "unknown author"}
          </p>
          <p className={styles.diffRow}>{preview.units.length} proposed chapters</p>
          <button type="button" className={styles.action} onClick={handleCommit} disabled={pending}>
            {pending ? "Importing…" : "Add to library"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
