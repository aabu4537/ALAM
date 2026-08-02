import type { Metadata } from "next";
import { ImportPanel } from "./ImportPanel";
import styles from "./import.module.css";

export const metadata: Metadata = {
  title: "Import — ALAM",
};

export default function ImportPage() {
  return (
    <div className="page-settle">
      <h1 className={styles.heading}>Add to your library</h1>
      <ImportPanel />
    </div>
  );
}
