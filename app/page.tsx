import Link from "next/link";
import { StatusPill } from "./components/StatusPill";
import styles from "./page.module.css";
import { apiGetJson } from "@/lib/server-api";
import type { BookSummary } from "@/lib/types";

export default async function LibraryPage() {
  const { books } = await apiGetJson<{ books: BookSummary[] }>("/books");

  return (
    <div className="page-settle">
      <p className="stamp" style={{ color: "var(--brass)" }}>
        Library
      </p>
      <h1 className={styles.heading}>Your shelf</h1>

      {books.length === 0 ? (
        <p className={styles.empty}>
          Nothing here yet.{" "}
          <Link href="/import" className={styles.emptyLink}>
            Import a Goodreads export or an EPUB
          </Link>{" "}
          to begin.
        </p>
      ) : (
        <ul className={styles.grid}>
          {books.map((book) => (
            <li key={book.id}>
              <Link
                href={book.structure_verified ? `/library/${book.id}` : `/library/${book.id}/verify`}
                className={styles.card}
              >
                <div className={styles.cardTop}>
                  <StatusPill book={book} />
                  {book.structure_verified ? (
                    <span className={`ordinal ${styles.chapterCount}`}>
                      {book.chapter_count} ch.
                    </span>
                  ) : null}
                </div>
                <h2 className={styles.cardTitle}>{book.title}</h2>
                {book.author ? <p className={styles.cardAuthor}>{book.author}</p> : null}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
