import { notFound, redirect } from "next/navigation";
import { StructureEditor } from "./StructureEditor";
import styles from "./verify.module.css";
import { apiGetJson, ApiError } from "@/lib/server-api";
import type { BookStructure } from "@/lib/types";

export default async function VerifyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let structure: BookStructure;
  try {
    structure = await apiGetJson<BookStructure>(`/books/${id}/structure`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    if (error instanceof ApiError && error.status === 409) redirect(`/library/${id}`);
    throw error;
  }

  return (
    <div className="page-settle">
      <p className="stamp" style={{ color: "var(--brass)" }}>
        Verify structure
      </p>
      <h1 className={styles.heading}>{structure.title}</h1>
      <StructureEditor mediaItemId={id} title={structure.title} units={structure.units} />
    </div>
  );
}
