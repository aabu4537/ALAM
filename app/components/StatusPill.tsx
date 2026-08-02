import type { BookSummary } from "@/lib/types";
import styles from "./StatusPill.module.css";

const SHELF_LABELS: Record<string, string> = {
  "to-read": "To read",
  "currently-reading": "Currently reading",
  read: "Read",
};

export function StatusPill({ book }: { book: BookSummary }) {
  if (!book.structure_verified) {
    return <span className={`${styles.pill} ${styles.neutral}`}>Unverified</span>;
  }
  if (book.has_active_reading_session) {
    return <span className={`${styles.pill} ${styles.active}`}>Reading</span>;
  }
  const label = book.exclusive_shelf ? (SHELF_LABELS[book.exclusive_shelf] ?? book.exclusive_shelf) : "Verified";
  return <span className={`${styles.pill} ${styles.quiet}`}>{label}</span>;
}
