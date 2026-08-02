"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import styles from "./verify.module.css";
import type { StructureUnit } from "@/lib/types";

interface Row {
  key: string;
  id: string | null;
  label: string;
  first_lines: string | null;
}

function toRows(units: StructureUnit[]): Row[] {
  return units.map((unit) => ({
    key: unit.id,
    id: unit.id,
    label: unit.label,
    first_lines: unit.first_lines,
  }));
}

export function StructureEditor({
  mediaItemId,
  title,
  units,
}: {
  mediaItemId: string;
  title: string;
  units: StructureUnit[];
}) {
  const router = useRouter();
  const [rows, setRows] = useState<Row[]>(() => toRows(units));
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  function move(index: number, direction: -1 | 1) {
    setRows((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  function relabel(index: number, label: string) {
    setRows((current) => current.map((row, i) => (i === index ? { ...row, label } : row)));
  }

  function remove(index: number) {
    setRows((current) => current.filter((_, i) => i !== index));
  }

  function split(index: number) {
    setRows((current) => {
      const next = [...current];
      next.splice(index + 1, 0, {
        key: crypto.randomUUID(),
        id: null,
        label: "New chapter",
        first_lines: null,
      });
      return next;
    });
  }

  async function handleSave() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`/books/${mediaItemId}/structure`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          rows.map((row) => ({ id: row.id, label: row.label, first_lines: row.first_lines })),
        ),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.detail ?? `Couldn't verify (${response.status}).`);
        return;
      }
      router.push(`/library/${mediaItemId}`);
      router.refresh();
    } catch {
      setError("Couldn't reach the server.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div>
      <p className={styles.hint}>
        Confirm {title}&apos;s chapter boundaries. Reorder, rename, split, or remove rows — this
        can only be done once, before anything is indexed.
      </p>
      <ol className={styles.rows}>
        {rows.map((row, index) => (
          <li key={row.key} className={styles.row}>
            <span className="ordinal">{index + 1}</span>
            <div className={styles.rowMain}>
              <input
                className={styles.labelInput}
                value={row.label}
                onChange={(event) => relabel(index, event.target.value)}
              />
              {row.first_lines ? <p className={styles.firstLines}>{row.first_lines}</p> : null}
            </div>
            <div className={styles.rowActions}>
              <button type="button" onClick={() => move(index, -1)} disabled={index === 0}>
                ↑
              </button>
              <button
                type="button"
                onClick={() => move(index, 1)}
                disabled={index === rows.length - 1}
              >
                ↓
              </button>
              <button type="button" onClick={() => split(index)}>
                Split
              </button>
              <button type="button" onClick={() => remove(index)} disabled={rows.length === 1}>
                Remove
              </button>
            </div>
          </li>
        ))}
      </ol>
      {error ? <p className={styles.error}>{error}</p> : null}
      <button type="button" className={styles.save} onClick={handleSave} disabled={pending}>
        {pending ? "Saving…" : "Confirm structure"}
      </button>
    </div>
  );
}
