import type { Metadata } from "next";
import styles from "./preferences.module.css";
import { apiGetJson } from "@/lib/server-api";
import type { TasteDrift } from "@/lib/types";

export const metadata: Metadata = {
  title: "Preferences — ALAM",
};

export default async function PreferencesPage() {
  const { chains } = await apiGetJson<TasteDrift>("/preferences/taste-drift");

  return (
    <div className="page-settle">
      <p className="stamp" style={{ color: "var(--brass)" }}>
        Taste drift
      </p>
      <h1 className={styles.heading}>What you seem to want</h1>

      {chains.length === 0 ? (
        <p className={styles.empty}>
          Nothing consolidated yet. Preferences build up as you record reflections and the
          weekly consolidation job runs.
        </p>
      ) : (
        <ul className={styles.chains}>
          {chains.map((chain, chainIndex) => (
            // A chain has no stable id of its own; its own contents don't reorder.
            <li key={chainIndex} className={styles.chain}>
              {chain.history.map((entry) => (
                <div
                  key={entry.id}
                  className={entry.active ? `${styles.entry} ${styles.entryActive}` : styles.entry}
                >
                  <p className={styles.statement}>{entry.statement}</p>
                  <div className={styles.confidenceTrack}>
                    <div
                      className={styles.confidenceFill}
                      style={{ width: `${Math.round(entry.confidence * 100)}%` }}
                    />
                  </div>
                  <p className={styles.meta}>
                    <span className="ordinal">{Math.round(entry.confidence * 100)}%</span>{" "}
                    confidence · seen {entry.observation_count}×
                    {entry.superseded_at ? " · superseded" : ""}
                  </p>
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
