import Link from "next/link";
import type { Metadata } from "next";
import styles from "./recommendations.module.css";
import { apiGetJson } from "@/lib/server-api";
import type { Recommendations } from "@/lib/types";

export const metadata: Metadata = {
  title: "Recommendations — ALAM",
};

const CITE_LABELS: Record<string, string> = {
  preference_fact: "your taste",
  memory: "your reflection",
  catalog: "catalog",
};

export default async function RecommendationsPage() {
  const { recommendations, generated_at: generatedAt } =
    await apiGetJson<Recommendations>("/recommendations");

  return (
    <div className="page-settle">
      <p className="stamp" style={{ color: "var(--brass)" }}>
        Recommendations
      </p>
      <h1 className={styles.heading}>From your own to-read shelf</h1>
      {generatedAt ? (
        <p className={styles.generated}>Generated {new Date(generatedAt).toLocaleDateString()}</p>
      ) : null}

      {recommendations.length === 0 ? (
        <p className={styles.empty}>
          Nothing to recommend yet — add books to your to-read shelf and record a few
          reflections first.
        </p>
      ) : (
        <ul className={styles.grid}>
          {recommendations.map((candidate) => (
            <li key={candidate.media_item_id} className={styles.card}>
              <Link href={`/library/${candidate.media_item_id}`} className={styles.cardTitle}>
                {candidate.title}
              </Link>
              <ul className={styles.claims}>
                {candidate.claims.map((claim) => (
                  <li key={claim.cites_id} className={styles.claim}>
                    <p className={styles.claimText}>&ldquo;{claim.text}&rdquo;</p>
                    <span className={styles.claimSource}>
                      — {CITE_LABELS[claim.cites_type] ?? claim.cites_type}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
